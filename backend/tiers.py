"""Tier resolution + cap matrix for AI Job Agent quota gates.

Single source of truth for which subscription tier an authenticated
user is on and what monthly / lifetime / persistent caps apply at that
tier. Every quota gate (tailored applications, premium applications,
resume-builder sessions, assistant turns, resume parses, job searches,
saved jobs, saved workspaces) reads from `TIER_CAPS` keyed by the tier
returned from `resolve_user_tier`. No other module should re-derive
the tier — that's the whole point of this indirection.

`resolve_user_tier` consults `backend.subscriptions.get_active_subscription`,
which reads from the Supabase `subscriptions` table populated by the
Lemon Squeezy webhook handler. The read is LRU-cached for up to 60
seconds (keyed by user_id + current UTC minute) so the gate never
blocks on a network round-trip. The webhook handler invalidates the
cache on every upsert so paid tier access kicks in within "one page
load" of a successful checkout.

Source of truth for the cap numbers is the landing-page pricing
matrix; if you change a value here, update the pricing UI in the same
PR. Numbers below mirror the locked table from the
`feat/tier-enforcement` brief:

    COUNTER                     PERIOD       FREE   PRO    BUSINESS
    tailored_applications       monthly      3      20     80
    premium_applications        monthly      0      5      25
    resume_builder_sessions     lifetime*    1      3      15
    assistant_turns             monthly      20     150    500
    resume_parses               monthly      3      25     100
    job_searches                monthly      50     ∞      ∞
    saved_jobs                  persistent   5      1000   ∞
    saved_workspaces            persistent   1      5      ∞

    * Free uses a lifetime counter; Pro and Business reset monthly.
      `check_and_increment` accepts a `lifetime=` flag so the call
      site, not this table, decides which period_key to use.

`UNLIMITED` (= -1) marks "no cap"; the quota helper short-circuits
when the cap equals this sentinel rather than performing an increment.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from src.schemas import AppUserRecord


Tier = Literal["free", "pro", "business"]


# Statuses that grant paid tier access while `current_period_end >
# now()`. Mirrors the Lemon Squeezy subscription state machine:
#   * "active":    fully paid, current_period_end is the next renewal.
#   * "cancelled": user clicked cancel but tier access continues until
#                  the end of the paid period (LS leaves the
#                  subscription at status='active' on the data
#                  payload and sets cancel_at_period_end=true; the
#                  webhook router maps that to status='cancelled' on
#                  our row so the resolver can branch on it
#                  explicitly).
#   * "past_due":  payment retry pending (dunning). LS retries 3x
#                  over ~14 days. We keep tier access during that
#                  window so a transient card decline doesn't
#                  immediately downgrade a paying user.
# "expired" / "paused" / unknown statuses always resolve to Free.
_PAID_STATUSES_DURING_PERIOD: frozenset[str] = frozenset(
    {"active", "cancelled", "past_due"}
)
# Tier values we accept from the subscription row. Anything else
# (typo, future tier we haven't shipped yet) resolves to Free
# defensively.
_PAID_TIERS: frozenset[str] = frozenset({"pro", "business"})


# Sentinel for "no cap on this counter at this tier". The
# `check_and_increment` helper does a single `cap < 0` test to decide
# whether to skip the upsert entirely. Using -1 (not None) keeps the
# inner dict uniformly typed as int so static analysis doesn't trip
# on Optional handling at every call site.
UNLIMITED = -1


# Per-tier caps. The outer key is the tier name returned by
# `resolve_user_tier`; the inner key is the counter name passed to
# `check_and_increment(counter_name, ...)`. Counter names are part of
# the on-disk Supabase schema (composite PK column value) — renaming a
# counter is a data migration, not a refactor.
#
# This table holds the FULL counter set even though Step 3 only wires
# tailored_applications + premium_applications. Steps 4-8 just need to
# call into the helper with the right counter name — they don't have
# to touch this table.
TIER_CAPS: dict[Tier, dict[str, int]] = {
    "free": {
        "tailored_applications": 3,
        "premium_applications": 0,
        "resume_builder_sessions": 1,
        "assistant_turns": 20,
        "resume_parses": 3,
        "job_searches": 50,
        "saved_jobs": 5,
        "saved_workspaces": 1,
    },
    "pro": {
        "tailored_applications": 20,
        "premium_applications": 5,
        "resume_builder_sessions": 3,
        "assistant_turns": 150,
        "resume_parses": 25,
        "job_searches": UNLIMITED,
        "saved_jobs": 1000,
        "saved_workspaces": 5,
    },
    "business": {
        "tailored_applications": 80,
        "premium_applications": 25,
        "resume_builder_sessions": 15,
        "assistant_turns": 500,
        "resume_parses": 100,
        "job_searches": UNLIMITED,
        "saved_jobs": UNLIMITED,
        "saved_workspaces": UNLIMITED,
    },
}


# Tier-aware retention for saved workspaces (Step 8). Free plans get a
# 7-day rolling retention window; Pro plans get 30 days; Business is
# unbounded. None is the "unbounded" sentinel rather than a large
# integer so callers can do a single `if days is None: continue` test
# without comparing against a "fake infinity" magic number.
#
# These numbers live HERE (not in TIER_CAPS) because retention is a
# duration, not a count -- conflating them would force a second
# TypedDict field whose semantics differ from every other cap. The
# sweeper reads from this table, the brief locks the values:
#
#     TIER       SAVED_WORKSPACE RETENTION
#     free       7 days
#     pro        30 days
#     business   unbounded (None)
#
# If marketing copy on the pricing page changes, update this mapping
# AND `frontend/src/components/landing/pricing.tsx` in the same PR.
_RETENTION_DAYS_BY_TIER: dict[Tier, int | None] = {
    "free": 7,
    "pro": 30,
    "business": None,
}


def retention_days_for_tier(tier: Tier) -> int | None:
    """Return the saved-workspace retention duration for a tier.

    Returns a positive integer for capped tiers (Free 7, Pro 30) and
    ``None`` for unbounded retention (Business). The sweeper treats
    None as "skip this row" -- the workspace stays forever until the
    user explicitly deletes it.

    Mirrors HelpmateAI's `TIER_LIMITS[tier]["retention_days"]` shape
    but lives in a separate mapping because:
      * Retention is a duration, not a count, so it doesn't belong
        next to the integer caps in TIER_CAPS.
      * The unbounded sentinel is `None` here; TIER_CAPS uses -1.
        Mixing both in one TypedDict would force every caller to
        carry both type-narrowing branches around.
    """
    return _RETENTION_DAYS_BY_TIER[tier]


# ── Export entitlement (pricing-truth gate) ─────────────────────────
# The pricing page promises Free "PDF export, Professional theme" and
# Pro / Business "PDF + DOCX export, all themes". That differentiation
# is an ENTITLEMENT, not a metered counter, so it lives here (tier
# policy) and is enforced via the same QuotaExceededError 429 path as
# the premium_applications gate (see
# `backend.quota.enforce_export_entitlement` /
# `_build_quota_exceeded_error`) -- the frontend then renders the
# identical upgrade nudge instead of a bespoke error shape.
#
# `professional_neutral` is also the product-wide DEFAULT theme (every
# request model defaults to it), so a Free user who never opens the
# theme picker exports their allowed combination without tripping the
# gate. `classic_ats` is the Pro/Business-only alternate.
#
# Keep these two constants in lockstep with the pricing copy in
# `frontend/src/components/landing-page.tsx` (Free vs Pro/Business
# feature bullets). Changing what Free gets is a pricing change, not a
# refactor.
FREE_EXPORT_FORMAT = "pdf"
FREE_EXPORT_THEME = "professional_neutral"


def export_entitlement_block_reason(
    tier: Tier,
    *,
    export_format: str | None = None,
    themes: tuple[str, ...] | list[str] = (),
) -> str | None:
    """Return a short human label for the locked feature if `tier` may
    NOT export with the requested format/theme, else ``None``.

    Pro and Business have the full entitlement (always ``None``). Free
    -- and anonymous, which `resolve_user_tier` already collapses to
    "free" -- is limited to ``FREE_EXPORT_FORMAT`` +
    ``FREE_EXPORT_THEME``; anything else returns the label the upgrade
    nudge should name ("DOCX export" / "Custom export themes").

    Theme/format comparison is whitespace- and case-insensitive to
    match the request models' ``_strip_theme`` normalisation. An
    empty/blank value is treated as the default (allowed), never a
    violation -- a caller omitting a theme must not be upsold.
    """
    if tier != "free":
        return None
    fmt = (export_format or "").strip().lower()
    if fmt and fmt != FREE_EXPORT_FORMAT:
        return "DOCX export"
    for theme in themes:
        normalized = (theme or "").strip().lower()
        if normalized and normalized != FREE_EXPORT_THEME:
            return "Custom export themes"
    return None


def resolve_user_tier(app_user: AppUserRecord | None) -> Tier:
    """Resolve the active subscription tier for an authenticated user.

    Consults `backend.subscriptions.get_active_subscription`, which
    reads from the Supabase ``subscriptions`` table populated by the
    Lemon Squeezy webhook handler. The read is LRU-cached for up to
    60 seconds so this function never blocks on a network round-trip
    -- it sits on every quota gate's hot path.

    Tier resolution rules:

      * No app_user (anonymous): "free".
      * No subscription row: "free".
      * subscription row with status in {"active", "cancelled",
        "past_due"} AND current_period_end > now: return the
        subscription's tier. "cancelled" still grants access during
        the paid period; "past_due" is the LS dunning window.
      * Anything else (status="expired" / "paused", current_period_end
        in the past, unknown tier value): "free".

    Lazy import of `backend.subscriptions` so circular imports during
    test collection don't crash a bare `from backend.tiers import
    TIER_CAPS` path that doesn't need subscriptions.
    """
    if app_user is None:
        return "free"
    user_id = getattr(app_user, "id", None)
    if not user_id:
        return "free"

    # Local import avoids a hard cycle in test collection: anything
    # importing `backend.tiers` (e.g. quota.py) doesn't need to drag
    # `backend.subscriptions` in if it's never actually resolving a
    # user. Same pattern HelpmateAI uses for its tier shim.
    from backend.subscriptions import get_active_subscription

    sub = get_active_subscription(str(user_id))
    if sub is None:
        return "free"

    if sub.tier not in _PAID_TIERS:
        # Defensive: the table has a CHECK constraint that limits
        # this to {"pro", "business"}, but if the constraint is ever
        # relaxed or a future migration adds a tier we haven't
        # shipped frontend support for, fall back to Free rather
        # than letting an unrecognized string flow into TIER_CAPS as
        # a KeyError at gate-check time.
        return "free"

    if sub.status not in _PAID_STATUSES_DURING_PERIOD:
        return "free"

    period_end = sub.current_period_end
    if period_end is None:
        # No period boundary on the row -- conservatively downgrade.
        # An active subscription should always have a
        # current_period_end set by the webhook; missing values
        # indicate a bug we'd rather catch on the free side than the
        # paid side.
        return "free"

    if period_end <= datetime.now(timezone.utc):
        return "free"

    # mypy/pyright: tier is narrowed to "pro" | "business" by the
    # `not in _PAID_TIERS` guard above; cast via the Literal return.
    return "pro" if sub.tier == "pro" else "business"


__all__ = [
    "TIER_CAPS",
    "UNLIMITED",
    "Tier",
    "resolve_user_tier",
    "retention_days_for_tier",
]
