"""Subscription lookup + cache for tier resolution.

`resolve_user_tier` reads from this module on every quota gate, which
means it has to:

  1. Never block on a network round-trip. The function is called from
     hot paths (every /workspace/analyze, every assistant turn,
     /workspace/quota). A 200ms Supabase read per call would shred
     P95.
  2. Pick up the new tier within a minute of a successful webhook. LS
     sends ``subscription_created`` immediately after checkout; the
     user expects to see Pro state within "the next page load or two",
     not the next refresh-five-minutes-later cycle.

The compromise is a 60-second TTL cache keyed by
``(user_id, current_minute_bucket)`` — the cache key changes every
calendar minute, so reads converge on the new value within at most
60 seconds without the webhook having to invalidate anything. The LRU
holds at most 4096 entries (≈10MB) and evicts the oldest on overflow.

The webhook handler in `backend/webhooks/lemonsqueezy.py` does NOT
need to call `invalidate_subscription_cache(user_id)` — it can, for a
sharper user-visible cutover, but the natural minute-bucket expiry is
the contract.

Backend selection mirrors `backend.quota`:
  * Supabase service-role client when SUPABASE_URL +
    SUPABASE_SERVICE_ROLE_KEY are present.
  * In-memory fallback for unit tests + local dev without Supabase.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional

from src.config import SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL


try:  # supabase is an optional dep in some test paths
    from supabase import create_client as _create_supabase_client  # type: ignore
except Exception:  # pragma: no cover - defensive import
    _create_supabase_client = None  # type: ignore


logger = logging.getLogger(__name__)


# The subscriptions table name is fixed for v1 (mirrors the SQL
# migration in docs/sql/supabase-subscriptions.sql). Exposed as a
# module-level constant so the webhook handler can write to the same
# table without hard-coding the literal twice.
SUBSCRIPTIONS_TABLE = "subscriptions"
WEBHOOK_LOG_TABLE = "subscription_webhook_log"


@dataclass(frozen=True)
class Subscription:
    """Row shape returned by `get_active_subscription`.

    Mirrors the Supabase table column-for-column. `tier` is narrowed
    to "pro" | "business" by the table's check constraint, but typed
    as plain str here so the upstream resolver can do its own Literal
    narrow without an explicit cast.
    """

    user_id: str
    processor: str
    processor_customer_id: str
    processor_subscription_id: str
    tier: str
    status: str
    current_period_end: Optional[datetime]
    cancel_at_period_end: bool
    variant_id: str


# ─── Backend abstraction ────────────────────────────────────────────────


class _InMemorySubscriptionsBackend:
    """Process-local store used in unit tests + local dev without
    Supabase. Mirrors the Supabase backend's read surface; the webhook
    handler writes through the same `upsert` method.

    Thread-safe via a single lock — concurrency in tests is handled
    correctly. Production must run with the Supabase backend.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # user_id -> Subscription
        self._store: dict[str, Subscription] = {}
        # event_id -> True; mirrors the subscription_webhook_log table
        # for idempotency in tests.
        self._processed_events: set[str] = set()

    def reset(self) -> None:
        with self._lock:
            self._store.clear()
            self._processed_events.clear()

    def read_by_user_id(self, user_id: str) -> Optional[Subscription]:
        with self._lock:
            return self._store.get(user_id)

    def upsert(self, sub: Subscription) -> None:
        with self._lock:
            self._store[sub.user_id] = sub

    def has_processed_event(self, event_id: str) -> bool:
        with self._lock:
            return event_id in self._processed_events

    def mark_event_processed(self, event_id: str, event_name: str) -> None:
        del event_name  # only the event_id is used in-memory.
        with self._lock:
            self._processed_events.add(event_id)


class _SupabaseSubscriptionsBackend:
    """Service-role-backed subscription store.

    Reads via the service role so RLS doesn't matter -- the row's
    user_id is the lookup key, not auth.uid(). Writes are by the
    webhook handler (which also uses service_role) on a different
    code path; the read API exposed here is purely for the tier
    resolver.

    Lazy client initialization so importing the module without
    SUPABASE_URL / SERVICE_ROLE_KEY doesn't crash -- the in-memory
    fallback handles that path. is_configured() picks the dispatch.
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

    def read_by_user_id(self, user_id: str) -> Optional[Subscription]:
        try:
            client = self._require_client()
            response = (
                client.table(SUBSCRIPTIONS_TABLE)
                .select(
                    "user_id,processor,processor_customer_id,"
                    "processor_subscription_id,tier,status,current_period_end,"
                    "cancel_at_period_end,variant_id"
                )
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
        except Exception:  # noqa: BLE001 - read is best-effort
            logger.exception(
                "subscription_read_failed user_id=%s", user_id
            )
            return None
        data = getattr(response, "data", None) or []
        if not data:
            return None
        row = data[0] if isinstance(data, list) else data
        if not isinstance(row, dict):
            return None
        return _row_to_subscription(row)

    def upsert(self, sub: Subscription) -> None:
        client = self._require_client()
        payload = {
            "user_id": sub.user_id,
            "processor": sub.processor,
            "processor_customer_id": sub.processor_customer_id or None,
            "processor_subscription_id": sub.processor_subscription_id,
            "tier": sub.tier,
            "status": sub.status,
            "current_period_end": (
                sub.current_period_end.isoformat()
                if sub.current_period_end is not None
                else None
            ),
            "cancel_at_period_end": sub.cancel_at_period_end,
            "variant_id": sub.variant_id or None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        client.table(SUBSCRIPTIONS_TABLE).upsert(
            payload, on_conflict="user_id"
        ).execute()

    def has_processed_event(self, event_id: str) -> bool:
        try:
            client = self._require_client()
            response = (
                client.table(WEBHOOK_LOG_TABLE)
                .select("event_id")
                .eq("event_id", event_id)
                .limit(1)
                .execute()
            )
        except Exception:  # noqa: BLE001 - read is best-effort
            logger.exception(
                "subscription_webhook_log_read_failed event_id=%s", event_id
            )
            # Fail-open on idempotency: if we can't tell whether the
            # event was processed, let it through. Webhook handlers
            # MUST themselves be idempotent (upsert by user_id) so a
            # duplicate is harmless; vs. a fail-closed branch silently
            # dropping a real event.
            return False
        data = getattr(response, "data", None) or []
        return bool(data)

    def mark_event_processed(self, event_id: str, event_name: str) -> None:
        try:
            client = self._require_client()
            client.table(WEBHOOK_LOG_TABLE).insert(
                {"event_id": event_id, "event_name": event_name}
            ).execute()
        except Exception:  # noqa: BLE001 - best-effort log write
            # If the insert races (two concurrent webhook deliveries
            # for the same event_id), the PK conflict is benign -- the
            # upsert path already ran idempotently. Log + swallow.
            logger.warning(
                "subscription_webhook_log_insert_failed event_id=%s",
                event_id,
            )


def _row_to_subscription(row: dict) -> Subscription:
    """Convert a Supabase row dict into a frozen Subscription."""
    raw_end = row.get("current_period_end")
    current_period_end: Optional[datetime]
    if raw_end:
        try:
            # Supabase returns timestamptz as ISO-8601 with a "+00:00"
            # offset; datetime.fromisoformat handles that since 3.11.
            current_period_end = datetime.fromisoformat(
                str(raw_end).replace("Z", "+00:00")
            )
        except ValueError:
            current_period_end = None
    else:
        current_period_end = None
    return Subscription(
        user_id=str(row.get("user_id") or ""),
        processor=str(row.get("processor") or ""),
        processor_customer_id=str(row.get("processor_customer_id") or ""),
        processor_subscription_id=str(row.get("processor_subscription_id") or ""),
        tier=str(row.get("tier") or ""),
        status=str(row.get("status") or ""),
        current_period_end=current_period_end,
        cancel_at_period_end=bool(row.get("cancel_at_period_end") or False),
        variant_id=str(row.get("variant_id") or ""),
    )


# Module-level singletons. Tests reach in via `reset_in_memory_backend`
# or by monkeypatching `_BACKEND` directly.
_IN_MEMORY_BACKEND = _InMemorySubscriptionsBackend()
_SUPABASE_BACKEND = _SupabaseSubscriptionsBackend()


def _select_backend():
    if _SUPABASE_BACKEND.is_configured():
        return _SUPABASE_BACKEND
    return _IN_MEMORY_BACKEND


def reset_in_memory_backend() -> None:
    """Wipe the process-local subscription store. Test-only."""
    _IN_MEMORY_BACKEND.reset()


# ─── 60-second LRU cache ────────────────────────────────────────────────


def _current_minute_bucket(now: Optional[datetime] = None) -> str:
    """Return a string key that flips once per UTC calendar minute.

    Used as a cache key component so `_cached_read` automatically
    misses (and re-reads from Supabase) within at most 60 seconds of
    any subscription state change -- without the webhook handler
    having to call into the cache directly. The cache also exposes
    `invalidate_subscription_cache` for callers who want a sharper
    cutover.
    """
    moment = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    return f"{moment.year:04d}-{moment.month:02d}-{moment.day:02d}T{moment.hour:02d}:{moment.minute:02d}"


# LRU is module-level so it survives across requests. maxsize=4096 is
# enough to hold every active user across a small fleet; if the
# product scales past that we'll need a process-shared cache (Redis
# / memcached). The TTL via minute_bucket keeps stale entries
# bounded.
@lru_cache(maxsize=4096)
def _cached_read(user_id: str, minute_bucket: str) -> Optional[Subscription]:
    """LRU-cached read of a subscription row.

    `minute_bucket` is included in the cache key but unused inside
    the function -- it exists purely to invalidate the entry on the
    next minute boundary. functools.lru_cache hashes positional args,
    so two calls with different minute_bucket strings produce
    different cache slots.
    """
    del minute_bucket  # intentionally unused -- it's the TTL knob.
    backend = _select_backend()
    return backend.read_by_user_id(user_id)


def invalidate_subscription_cache(user_id: Optional[str] = None) -> None:
    """Drop cached subscription entries.

    Called by the LS webhook handler after a successful upsert so the
    next gate check sees the new state immediately rather than
    waiting for the minute-bucket flip. Passing `None` clears the
    whole cache (used in tests and on process-wide subscription
    refreshes).

    `lru_cache` doesn't support per-key eviction directly, so we
    clear the whole cache when `user_id` is provided too. The cache
    is small and the webhook path is low-volume, so this is fine.
    """
    del user_id  # signature reserved for a future per-user clear.
    _cached_read.cache_clear()


# ─── Public API ─────────────────────────────────────────────────────────


def get_active_subscription(user_id: str) -> Optional[Subscription]:
    """Return the user's subscription row, or None when no row exists.

    The "active" in the function name refers to "the row that exists
    for this user", not the status field. The caller (typically
    `resolve_user_tier`) is responsible for interpreting the status
    + period semantics; this function just looks the row up.

    Caches the result for up to 60 seconds via an LRU keyed by
    `(user_id, current_minute_bucket)`. Webhook upserts call
    `invalidate_subscription_cache()` for a sharper cutover; even
    without that, the cache naturally converges within 60 seconds.

    Returns None when:
      * No subscription row exists for this user (Free tier).
      * The backend read failed (logged and swallowed). The caller
        falls back to Free in that case -- the alternative is to
        block paid gates on a transient Supabase outage, which the
        product specifically doesn't want.
    """
    if not user_id:
        return None
    return _cached_read(user_id, _current_minute_bucket())


def upsert_subscription(sub: Subscription) -> None:
    """Write a subscription row through the active backend.

    Used by the LS webhook handler. The route does its own HMAC
    verification + event idempotency check before calling this, so
    this function is a thin write-through to the backend. Invalidates
    the read cache after a successful write so the next tier resolution
    picks up the new state immediately.
    """
    backend = _select_backend()
    backend.upsert(sub)
    invalidate_subscription_cache()


def has_processed_event(event_id: str) -> bool:
    """Check whether a webhook event_id has already been processed.

    Used by the LS webhook handler for idempotency. LS retries on
    non-2xx responses + has at-least-once semantics, so we MUST be
    safe under duplicate delivery. Returns False on read failures
    (fail-open) -- the upsert by user_id is itself idempotent, so a
    duplicate processing pass produces the same final state.
    """
    if not event_id:
        return False
    backend = _select_backend()
    return backend.has_processed_event(event_id)


def mark_event_processed(event_id: str, event_name: str) -> None:
    """Record that a webhook event_id has been processed.

    Best-effort -- a failure here just means a redelivery would
    re-process the event. Since the upsert path is itself idempotent,
    that's fine.
    """
    if not event_id:
        return
    backend = _select_backend()
    backend.mark_event_processed(event_id, event_name)


__all__ = [
    "Subscription",
    "SUBSCRIPTIONS_TABLE",
    "WEBHOOK_LOG_TABLE",
    "get_active_subscription",
    "has_processed_event",
    "invalidate_subscription_cache",
    "mark_event_processed",
    "reset_in_memory_backend",
    "upsert_subscription",
]
