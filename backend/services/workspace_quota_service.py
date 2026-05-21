"""Read-only quota snapshot for /workspace/quota (Step 7b).

The endpoint drives three frontend behaviors:

  * **Premium toggle gating** — `premium_available` is True only on
    tiers whose `premium_applications` cap is > 0, so the toggle can
    render disabled+tooltip on Free without a second lookup.
  * **Per-counter indicators** — each counter snapshot carries
    current / limit / remaining so the UI can show "you have N
    premium credits left this month" inline next to the toggle.
  * **Upgrade CTA target** — `upgrade_url` is read from the env so
    prod / staging / dev can each point at the right pricing page.

The endpoint is strictly read-only — calling it never increments a
counter, never writes to Supabase, never burns quota credit. It's safe
to call on every workspace mount + after every workflow run, which the
frontend does to keep the toggle's indicator in sync with the actual
backend state.

For period-keyed counters (tailored / premium applications, assistant
turns, resume parses, job searches), the snapshot reads from the
quota counters table via `quota.read_counter`. For lifetime counters
(Free-tier resume_builder_sessions), the same helper handles the
period_key swap. For persistent row-count caps (saved_jobs,
saved_workspaces) we read the existing row count from the
corresponding Supabase store and surface it as `current`.
"""
from __future__ import annotations

from typing import Any

from backend import quota
from backend.tiers import TIER_CAPS, UNLIMITED, Tier, resolve_user_tier
from backend.services.auth_session_service import resolve_authenticated_context
from src.errors import AppError
from src.saved_jobs_store import SavedJobsStore
from src.saved_workspace_store import SavedWorkspaceStore


class WorkspaceQuotaAuthRequired(RuntimeError):
    """Signaled by `get_workspace_quota_snapshot` when no usable auth
    context is available. The route converts this to a 401 -- the
    /workspace/quota response makes no sense for an anonymous caller.

    Local module-private exception type (not exported on src.errors)
    because it only carries information across the service/route
    boundary in one direction; the global QuotaExceededError handler
    chain has no role here. Naming makes the route's except branch
    self-documenting.
    """


# Per-counter metadata: which reset_period label to surface to the UI
# and whether the counter is lifetime-keyed for the Free tier.
#
# "monthly"    - calendar-month reset (period_key = YYYY-MM).
# "lifetime"   - Free tier only; resets never. Pro/Business use the
#                same counter name but the monthly partition.
# "persistent" - row count cap (saved_jobs, saved_workspaces). The
#                UI renders this as "saved N of M" without a reset
#                cadence.
_COUNTER_RESET_PERIODS: dict[str, str] = {
    "tailored_applications": "monthly",
    "premium_applications": "monthly",
    "resume_builder_sessions": "lifetime_or_monthly",
    "assistant_turns": "monthly",
    "resume_parses": "monthly",
    # llm_tokens is the unified token meter — an ISO-week reset for
    # every tier. NOT period-keyed monthly; the loop below reads it
    # via `quota.read_llm_token_usage` (weekly period key).
    "llm_tokens": "weekly",
    "job_searches": "monthly",
    "saved_jobs": "persistent",
    "saved_workspaces": "persistent",
}


# Counters that resolve to a lifetime period_key on Free tier and
# monthly on Pro / Business. The resume_builder_sessions gate inside
# its own service uses the same flag. We mirror that here so the
# /workspace/quota snapshot reads from the same row the gate writes.
_LIFETIME_ON_FREE: frozenset[str] = frozenset({"resume_builder_sessions"})


# Counters that are NOT period-keyed -- they track row counts in
# their own persistence store (saved_jobs / saved_workspaces tables).
# These bypass `quota.read_counter` entirely.
_PERSISTENT_COUNTERS: frozenset[str] = frozenset(
    {"saved_jobs", "saved_workspaces"}
)


def _reset_period_label(tier: Tier, counter_name: str) -> str:
    """Resolve the canonical reset-period string for a tier/counter
    pair. The frontend uses this to render "resets monthly" /
    "lifetime quota" / "persistent storage" copy below each
    indicator.

    Lifetime-on-Free counters get "lifetime" on Free and "monthly"
    on Pro / Business; persistent counters always return "persistent"
    regardless of tier; everything else is monthly.
    """
    raw_label = _COUNTER_RESET_PERIODS.get(counter_name, "monthly")
    if raw_label == "lifetime_or_monthly":
        return "lifetime" if tier == "free" else "monthly"
    return raw_label


def _is_lifetime_for_tier(tier: Tier, counter_name: str) -> bool:
    """Whether the period_key for this counter should be "lifetime"
    rather than the YYYY-MM partition. Mirrors the same decision the
    resume_builder_sessions gate makes inside its own service so the
    quota snapshot reads from the same row the gate writes."""
    if counter_name not in _LIFETIME_ON_FREE:
        return False
    return tier == "free"


def _build_counter_snapshot(
    *,
    counter_name: str,
    current: int,
    cap: int,
    reset_period: str,
) -> dict[str, Any]:
    """Pack a single counter's state into the UI-facing shape.

    UNLIMITED (-1) is surfaced as cap=-1 / remaining=-1 so the
    frontend's `cap < 0` check renders an "Unlimited" pill without
    needing a separate flag. `current` for an UNLIMITED counter is
    always 0 because we never write a row for one (see
    `quota.read_counter`'s short-circuit).
    """
    if cap == UNLIMITED:
        remaining = UNLIMITED
    else:
        remaining = max(cap - current, 0)
    return {
        "current": int(current),
        "limit": int(cap),
        "remaining": int(remaining),
        "reset_period": reset_period,
    }


def _persistent_count(
    *,
    counter_name: str,
    auth_context,
    access_token: str,
    refresh_token: str,
    cap: int,
) -> int:
    """Read the row count for a persistent counter (saved_jobs /
    saved_workspaces) from its store. Returns 0 when the cap is
    UNLIMITED (we never need the number) or when the store isn't
    configured (local-dev without Supabase). Best-effort: an outage
    in the store shouldn't break the /workspace/quota response."""
    if cap == UNLIMITED:
        return 0
    user_id = str(getattr(auth_context.app_user, "id", "") or "")
    if not user_id:
        return 0
    auth_service = auth_context.auth_service
    if counter_name == "saved_jobs":
        store = SavedJobsStore(auth_service)
        if not store.is_configured():
            return 0
        try:
            # +1 over cap so a runaway state still produces an
            # accurate "at-or-over" indicator instead of clipping
            # at the cap.
            rows = store.list_jobs(
                access_token,
                refresh_token,
                user_id,
                limit=cap + 1,
            )
        except Exception:  # noqa: BLE001 - read is best-effort
            return 0
        return len(rows)
    if counter_name == "saved_workspaces":
        store = SavedWorkspaceStore(auth_service)
        if not store.is_configured():
            return 0
        try:
            record, status = store.load_workspace(
                access_token,
                refresh_token,
                user_id,
            )
        except Exception:  # noqa: BLE001 - read is best-effort
            return 0
        # The store currently upserts on user_id so the row count is
        # always 0 or 1; we mirror the gate's behavior in
        # workspace_persistence_service which checks the same
        # "available" status.
        return 1 if status == "available" and record is not None else 0
    return 0


def get_workspace_quota_snapshot(
    *,
    access_token: str,
    refresh_token: str,
) -> dict[str, Any]:
    """Build the read-only quota snapshot for /workspace/quota.

    Anonymous callers (no auth tokens) raise AuthRequiredError so the
    route can surface a clean 401 — the snapshot only makes sense for
    an authenticated user. The route's exception handler turns the
    AppError into a 400; if we ever want a true 401 path we'd update
    the handler in lock-step with the route registration.

    The snapshot covers all eight counters from `TIER_CAPS` for the
    current tier. `premium_available` is True when the tier's
    `premium_applications` cap is > 0; the frontend reads this to
    decide whether the Premium toggle renders enabled or in the
    "Upgrade to unlock" disabled state.
    """
    if not (access_token and refresh_token):
        raise WorkspaceQuotaAuthRequired(
            "Sign in to view your workspace quota."
        )

    try:
        auth_context = resolve_authenticated_context(
            access_token=access_token,
            refresh_token=refresh_token,
        )
    except AppError as exc:
        # Token validation failed -- surface as auth required so the
        # frontend's 401 handler can prompt re-auth without rendering
        # a stale quota snapshot.
        raise WorkspaceQuotaAuthRequired(
            "Your session has expired. Sign in again to view quota."
        ) from exc

    tier = resolve_user_tier(auth_context.app_user)
    caps = TIER_CAPS[tier]
    quota_user_id = str(getattr(auth_context.app_user, "id", "") or "")

    counters: dict[str, dict[str, Any]] = {}
    for counter_name, cap in caps.items():
        if counter_name in _PERSISTENT_COUNTERS:
            current = _persistent_count(
                counter_name=counter_name,
                auth_context=auth_context,
                access_token=access_token,
                refresh_token=refresh_token,
                cap=cap,
            )
        elif counter_name == quota.LLM_TOKENS_COUNTER:
            # The unified token meter lives under an ISO-WEEK period
            # key — `read_counter` would read the monthly partition and
            # always report 0. Use the dedicated weekly reader.
            current = (
                quota.read_llm_token_usage(quota_user_id, tier)
                if quota_user_id
                else 0
            )
        elif quota_user_id:
            current = quota.read_counter(
                counter_name,
                quota_user_id,
                tier,
                lifetime=_is_lifetime_for_tier(tier, counter_name),
            )
        else:
            current = 0
        counters[counter_name] = _build_counter_snapshot(
            counter_name=counter_name,
            current=current,
            cap=cap,
            reset_period=_reset_period_label(tier, counter_name),
        )

    return {
        "tier": tier,
        "counters": counters,
        # Premium is "available" when the tier's premium_applications
        # cap is non-zero. Free has cap=0 so the toggle renders
        # disabled with an "Upgrade to Pro" tooltip; Pro/Business
        # both have non-zero caps and surface premium=True.
        "premium_available": caps["premium_applications"] > 0,
        "period_start": _period_start_iso(),
        # ISO date the weekly llm_tokens meter next resets on (the
        # coming Monday UTC). Drives the usage bar's "resets X" copy;
        # `period_start` stays first-of-month for the monthly counters.
        "llm_tokens_reset_at": _llm_token_week_reset_iso(),
        "upgrade_url": quota.UPGRADE_URL,
    }


def _period_start_iso() -> str:
    """First-of-month UTC date for the current monthly partition.

    Surfaced so the UI can render "resets on X" copy. Format is YYYY-MM-DD;
    callers parse it with Date.parse on the frontend. The frontend
    could derive this from period_key but having it pre-computed
    keeps the parsing surface uniform.
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return f"{now.year:04d}-{now.month:02d}-01"


def _llm_token_week_reset_iso() -> str:
    """ISO date (YYYY-MM-DD, UTC) the weekly llm_tokens meter next
    resets on — the coming Monday, since ISO weeks start Monday.

    ``weekday()`` is Mon=0..Sun=6, so ``7 - weekday()`` is the days to
    the next Monday (Mon → 7 = a full week out; Sun → 1 = tomorrow) —
    always the FOLLOWING Monday, never today, which matches "this
    week's allowance refills when the week rolls over."
    """
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    reset_date = (now + timedelta(days=7 - now.weekday())).date()
    return reset_date.isoformat()


__all__ = [
    "WorkspaceQuotaAuthRequired",
    "get_workspace_quota_snapshot",
]
