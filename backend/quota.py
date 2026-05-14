"""Atomic check-and-increment helper for tier quota counters.

Step 2 of the tier-enforcement series. The single entry point is
`check_and_increment(counter_name, user_id, tier, *, lifetime=False)`,
which:

  1. Resolves the cap for (tier, counter_name) via `TIER_CAPS`.
  2. Short-circuits when the cap equals `UNLIMITED` -- never touches
     the database, returns a sentinel `QuotaResult` so the call site
     can still log the result uniformly.
  3. Calls the Supabase `increment_aijobagent_counter` RPC, which
     atomically UPSERTs and either returns the new count or raises a
     SQLSTATE 'P0001' with detail `aijobagent_quota_exceeded`. Atomic
     means two concurrent workspace runs from the same user produce
     N+1 and N+2 -- never both N+1.
  4. On the 'P0001' branch, raises `QuotaExceededError` carrying the
     structured fields the FastAPI handler needs to build the 429.

The `lifetime` kwarg flips the period_key the row is written under
("lifetime" vs current "YYYY-MM"). Steps 4-8 expose this kwarg to the
resume-builder and persistent-count counters; step 3 only uses the
default monthly form.

`refund(counter_name, user_id, tier, *, lifetime=False)` decrements a
counter by 1, flooring at zero. Use it from the workflow-failure path
so a transient orchestrator error doesn't burn a user's quota credit.
The refund call shares the same RPC (with delta=-1), so the audit
trail in `updated_at` still reflects the change.

Backend selection:
  * The Supabase service-role client is required for the RPC because
    the RPC takes user_id as a parameter rather than reading
    auth.uid(). Granting EXECUTE to authenticated would let any
    signed-in user burn anybody else's quota.
  * When Supabase isn't configured (local dev, CI without secrets),
    we degrade to an in-memory store keyed by (user_id, period,
    counter) so unit tests and offline workflows still go through the
    same code path. The in-memory store is process-local and not safe
    under concurrent workers -- production must run with Supabase.
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from backend.tiers import TIER_CAPS, UNLIMITED, Tier
from src.config import (
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_URL,
)
from src.errors import QuotaExceededError


# Upgrade-page URL surfaced in 429 payloads and the /workspace/quota
# response so the frontend's upgrade-nudge CTA points somewhere real.
# Reads from AIJOBAGENT_UPGRADE_URL at import time so prod / staging /
# dev can each point at the right pricing page. The default mirrors
# the production landing site -- update if the marketing URL moves.
UPGRADE_URL = os.getenv(
    "AIJOBAGENT_UPGRADE_URL",
    "https://ai-job-agent.example.com/pricing",
).strip()


try:  # supabase is an optional dep in some test paths
    from supabase import create_client as _create_supabase_client  # type: ignore
except Exception:  # pragma: no cover - defensive import
    _create_supabase_client = None  # type: ignore


logger = logging.getLogger(__name__)


# Period-key literals. The Supabase composite PK is keyed by period_key
# as a free-form text column -- the application supplies whichever form
# is right for the counter. Keep these centralized so a typo in one
# call site can't desync the partition.
LIFETIME_PERIOD_KEY = "lifetime"


@dataclass(frozen=True)
class QuotaResult:
    """Snapshot returned on a successful check_and_increment call.

    `remaining` is computed against the post-increment count: a user
    with a Free cap of 3 and `count == 3` has `remaining == 0`, which
    the next call will reject. For `UNLIMITED` counters `cap` and
    `remaining` are both `UNLIMITED` so the caller can short-circuit
    any UI nudge logic with `result.cap == UNLIMITED`.
    """

    count: int
    cap: int
    remaining: int


def current_period_key(now: Optional[datetime] = None) -> str:
    """Return the YYYY-MM key for the calendar month in UTC.

    The Supabase row partitions naturally by this key -- no scheduled
    "reset" job, the next month's first increment lands in a new row
    with `count = 1`. `now` exists for tests; defaults to real UTC
    now.
    """
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return f"{moment.year:04d}-{moment.month:02d}"


def _period_key_for(*, lifetime: bool, now: Optional[datetime] = None) -> str:
    return LIFETIME_PERIOD_KEY if lifetime else current_period_key(now)


def _cap_for(tier: Tier, counter_name: str) -> int:
    """Look up a per-tier cap or raise KeyError on a typo.

    A missing counter is a bug in the call site (or the TIER_CAPS
    matrix). We deliberately let KeyError propagate rather than
    defaulting to UNLIMITED -- a silent "you're unlimited!" failure
    mode is the worst possible behavior for a billing gate.
    """
    return TIER_CAPS[tier][counter_name]


def _build_quota_exceeded_error(
    *,
    counter_name: str,
    current: int,
    cap: int,
    tier: Tier,
    period_key: str,
) -> QuotaExceededError:
    if counter_name == "premium_applications" and cap == 0:
        message = (
            "Premium applications are a Pro+ feature. Upgrade to run "
            "premium tailoring for this job."
        )
    else:
        message = (
            "You have reached the limit for this action on your current "
            "plan. Upgrade to continue or wait for the period to reset."
        )
    return QuotaExceededError(
        message,
        counter=counter_name,
        current=current,
        cap=cap,
        reset_period=period_key,
        tier=tier,
    )


# ─── Backend abstraction ────────────────────────────────────────────────


class _InMemoryQuotaBackend:
    """Process-local fallback used when Supabase isn't configured.

    Mirrors the SQL function's semantics: atomic increment, cap check
    on positive delta, UNLIMITED short-circuit (the caller already
    handled this case but the backend defends too), refund flooring at
    zero. Thread-safe via a single lock -- concurrency in tests is
    handled correctly; production must run with the Supabase backend.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._store: dict[tuple[str, str, str], int] = {}

    def reset(self) -> None:
        with self._lock:
            self._store.clear()

    def increment(
        self,
        *,
        user_id: str,
        period_key: str,
        counter_name: str,
        cap: int,
        delta: int,
    ) -> int:
        key = (user_id, period_key, counter_name)
        with self._lock:
            current = self._store.get(key, 0)
            if delta == 0:
                return current
            if cap >= 0 and delta > 0 and current + delta > cap:
                # SQLSTATE P0001 in the SQL function; translate to the
                # same Python signal so the caller's except branch
                # handles both backends uniformly.
                raise _QuotaExceededAtBackend(
                    counter_name=counter_name,
                    current=current,
                    cap=cap,
                )
            new = max(current + delta, 0)
            self._store[key] = new
            return new

    def read(
        self,
        *,
        user_id: str,
        period_key: str,
        counter_name: str,
    ) -> int:
        """Pure read of the current counter value. Returns 0 when no
        row exists -- the period hasn't been touched yet. No locking
        needed for a single dict lookup; the value is a momentary
        snapshot, not transactional with respect to concurrent
        increments (which is fine for /workspace/quota's
        informational read)."""
        return int(self._store.get((user_id, period_key, counter_name), 0))


class _QuotaExceededAtBackend(Exception):
    """Internal signal raised by either backend when the SQL/in-memory
    increment would breach the cap. Translated to `QuotaExceededError`
    in the public entry points -- the public error carries `reset_period`
    and `tier`, which the backend layer shouldn't need to know about.
    """

    def __init__(self, *, counter_name: str, current: int, cap: int) -> None:
        self.counter_name = counter_name
        self.current = current
        self.cap = cap


class _SupabaseQuotaBackend:
    """Service-role-backed quota store calling the atomic RPC.

    Uses lazy client initialization so importing this module without
    SUPABASE_URL / SERVICE_ROLE_KEY does not crash -- the in-memory
    fallback handles that path. is_configured() decides which backend
    `check_and_increment` actually dispatches to.
    """

    def __init__(
        self,
        *,
        supabase_url: str = SUPABASE_URL,
        service_role_key: str = SUPABASE_SERVICE_ROLE_KEY,
    ) -> None:
        self._url = supabase_url
        self._key = service_role_key
        self._client = None

    def is_configured(self) -> bool:
        return bool(self._url and self._key and _create_supabase_client is not None)

    def _require_client(self):
        if self._client is None:
            self._client = _create_supabase_client(self._url, self._key)
        return self._client

    def increment(
        self,
        *,
        user_id: str,
        period_key: str,
        counter_name: str,
        cap: int,
        delta: int,
    ) -> int:
        client = self._require_client()
        try:
            result = client.rpc(
                "increment_aijobagent_counter",
                {
                    "p_user_id": user_id,
                    "p_period_key": period_key,
                    "p_counter_name": counter_name,
                    "p_cap": cap,
                    "p_delta": delta,
                },
            ).execute()
        except Exception as exc:  # noqa: BLE001 - boundary translation
            # supabase-py wraps PostgREST errors in APIError; the
            # message contains the SQL DETAIL we wrote in the function.
            message = str(exc)
            if "aijobagent_quota_exceeded" in message:
                # The RPC ran the SELECT-for-update before raising, so
                # the message detail carries the current count we need
                # to surface in the 429 payload. Best-effort parse;
                # fall back to a generic "at-or-above-cap" assumption.
                current = _parse_current_from_rpc_error(message, fallback=cap)
                raise _QuotaExceededAtBackend(
                    counter_name=counter_name,
                    current=current,
                    cap=cap,
                ) from exc
            raise

        data = getattr(result, "data", None)
        if isinstance(data, list):
            return int(data[0]) if data else 0
        if data is None:
            return 0
        return int(data)

    def read(
        self,
        *,
        user_id: str,
        period_key: str,
        counter_name: str,
    ) -> int:
        """Best-effort read of the current counter value from the
        Supabase row, used by /workspace/quota. Returns 0 when no row
        exists or when the Supabase round-trip fails -- the read is
        purely informational (drives the UI's used/limit indicator),
        so swallowing transient errors is the right behavior; the
        next increment still goes through the atomic RPC."""
        try:
            client = self._require_client()
            response = (
                client.table("aijobagent_quota_counters")
                .select("count")
                .eq("user_id", user_id)
                .eq("period_key", period_key)
                .eq("counter_name", counter_name)
                .limit(1)
                .execute()
            )
        except Exception:  # noqa: BLE001 - read is best-effort
            logger.exception(
                "quota_read_failed counter=%s user_id=%s period_key=%s",
                counter_name,
                user_id,
                period_key,
            )
            return 0
        data = getattr(response, "data", None) or []
        if not data:
            return 0
        first = data[0] if isinstance(data, list) else data
        if not isinstance(first, dict):
            return 0
        try:
            return int(first.get("count", 0) or 0)
        except (TypeError, ValueError):
            return 0


def _parse_current_from_rpc_error(message: str, *, fallback: int) -> int:
    """Pull `current=<int>` out of the SQL DETAIL string.

    The SQL function raises with detail
    `counter=<name> cap=<int> current=<int>`. The supabase-py wrapper
    surfaces this as part of the APIError message. We do a small,
    forgiving parse here so the 429 payload still carries an accurate
    `current` even when supabase-py upgrades its error shape.
    """
    marker = "current="
    idx = message.find(marker)
    if idx < 0:
        return fallback
    tail = message[idx + len(marker) :]
    digits = ""
    for ch in tail:
        if ch.isdigit():
            digits += ch
            continue
        break
    if not digits:
        return fallback
    return int(digits)


# Module-level singletons. Tests reach in via `reset_in_memory_backend`
# or by monkeypatching `_BACKEND` directly. Production resolves to the
# Supabase backend automatically once the env vars are set.
_IN_MEMORY_BACKEND = _InMemoryQuotaBackend()
_SUPABASE_BACKEND = _SupabaseQuotaBackend()


def _select_backend():
    if _SUPABASE_BACKEND.is_configured():
        return _SUPABASE_BACKEND
    return _IN_MEMORY_BACKEND


def reset_in_memory_backend() -> None:
    """Wipe the process-local fallback store. Test-only -- production
    runs through Supabase and has no equivalent.
    """
    _IN_MEMORY_BACKEND.reset()


# ─── Public API ─────────────────────────────────────────────────────────


def check_and_increment(
    counter_name: str,
    user_id: str,
    tier: Tier,
    *,
    lifetime: bool = False,
    now: Optional[datetime] = None,
) -> QuotaResult:
    """Atomically increment the counter or raise QuotaExceededError.

    `counter_name` must be a key in TIER_CAPS[tier]; an unknown counter
    is a programming bug and surfaces as KeyError. `lifetime=True`
    writes to the "lifetime" period_key (used for Free-tier
    resume_builder_sessions in step 4); the default uses the current
    YYYY-MM partition.

    Returns:
        QuotaResult(count, cap, remaining) on success. For UNLIMITED
        counters returns `QuotaResult(count=0, cap=UNLIMITED, remaining=UNLIMITED)`
        without touching the database -- the count is not tracked.

    Raises:
        QuotaExceededError if the increment would breach the tier cap.
        Underlying network / Supabase errors propagate as the original
        exception so the caller can decide how to fail open or closed.
    """
    cap = _cap_for(tier, counter_name)
    period_key = _period_key_for(lifetime=lifetime, now=now)

    if cap == UNLIMITED:
        # Don't write a row -- there's no useful number to track for an
        # unlimited counter, and not writing keeps the table compact.
        return QuotaResult(count=0, cap=UNLIMITED, remaining=UNLIMITED)

    backend = _select_backend()
    try:
        new_count = backend.increment(
            user_id=user_id,
            period_key=period_key,
            counter_name=counter_name,
            cap=cap,
            delta=1,
        )
    except _QuotaExceededAtBackend as exc:
        raise _build_quota_exceeded_error(
            counter_name=exc.counter_name,
            current=exc.current,
            cap=exc.cap,
            tier=tier,
            period_key=period_key,
        ) from None

    return QuotaResult(
        count=new_count,
        cap=cap,
        remaining=max(cap - new_count, 0),
    )


def read_counter(
    counter_name: str,
    user_id: str,
    tier: Tier,
    *,
    lifetime: bool = False,
    now: Optional[datetime] = None,
) -> int:
    """Read the current counter value WITHOUT incrementing it.

    Used by /workspace/quota (step 7b) to populate the per-user quota
    snapshot the frontend renders. Returns 0 when:
      * the counter row hasn't been written this period yet, OR
      * the tier cap is UNLIMITED (the helper never writes a row for
        unlimited counters -- there's no useful number to track).

    No exception path: read failures from the Supabase backend log and
    return 0 so a transient cache miss doesn't break the /workspace/quota
    UI. The next `check_and_increment` call still goes through the
    atomic RPC, so a wrong-by-one informational read can't lead to a
    cap breach.
    """
    cap = _cap_for(tier, counter_name)
    if cap == UNLIMITED:
        # No row is ever written for unlimited counters (see
        # check_and_increment); the helper short-circuits to 0 to
        # keep the UI's used/limit copy stable rather than throwing
        # on a "no such row" round-trip.
        return 0

    period_key = _period_key_for(lifetime=lifetime, now=now)
    backend = _select_backend()
    return backend.read(
        user_id=user_id,
        period_key=period_key,
        counter_name=counter_name,
    )


def refund(
    counter_name: str,
    user_id: str,
    tier: Tier,
    *,
    lifetime: bool = False,
    now: Optional[datetime] = None,
) -> Optional[int]:
    """Decrement the counter by 1, flooring at zero.

    Use this from the workflow-failure path so a transient orchestrator
    failure doesn't burn a user's quota credit. Refunds are best-effort:
    if the decrement fails (Supabase outage, etc.) we log and swallow
    -- the user's account already absorbed the increment, and bubbling
    the failure here would mask the original orchestrator exception
    that the caller is trying to re-raise.

    Returns the new count on success, or None when no refund was
    necessary (UNLIMITED counter -- nothing was incremented to begin
    with).
    """
    cap = _cap_for(tier, counter_name)
    if cap == UNLIMITED:
        return None

    period_key = _period_key_for(lifetime=lifetime, now=now)
    backend = _select_backend()
    try:
        return backend.increment(
            user_id=user_id,
            period_key=period_key,
            counter_name=counter_name,
            cap=cap,
            delta=-1,
        )
    except _QuotaExceededAtBackend:
        # Refund (negative delta) cannot trigger the cap check in the
        # SQL function. If we get here it's a different error path --
        # log and swallow so the caller can re-raise the original
        # workflow exception.
        logger.warning(
            "quota_refund_cap_branch_unexpectedly_hit",
            extra={"counter": counter_name, "user_id": user_id},
        )
        return None
    except Exception:  # noqa: BLE001 - refund is best-effort
        logger.exception(
            "quota_refund_failed counter=%s user_id=%s",
            counter_name,
            user_id,
        )
        return None


__all__ = [
    "LIFETIME_PERIOD_KEY",
    "QuotaResult",
    "UPGRADE_URL",
    "check_and_increment",
    "current_period_key",
    "read_counter",
    "refund",
    "reset_in_memory_backend",
]
