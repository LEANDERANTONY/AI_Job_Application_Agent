"""Subscription lookup + LRU cache + webhook idempotency log.

Tests the contract `backend.tiers.resolve_user_tier` depends on:

  * `get_active_subscription(user_id)` returns the upserted row, or
    None when no row exists.
  * The 60-second LRU cache holds the row across calls within the
    same minute, AND `invalidate_subscription_cache()` drops cached
    entries so a webhook upsert is immediately visible.
  * The in-memory backend mirrors the Supabase backend's API surface
    -- in particular `has_processed_event` / `mark_event_processed`
    for webhook idempotency.

The Supabase backend has its own DDL-side fixture
(docs/sql/supabase-subscriptions.sql); we don't spin up a real
Postgres for unit tests.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend import subscriptions
from backend.subscriptions import (
    Subscription,
    _current_minute_bucket,
    get_active_subscription,
    has_processed_event,
    invalidate_subscription_cache,
    mark_event_processed,
    reset_in_memory_backend,
    upsert_subscription,
)


@pytest.fixture(autouse=True)
def _fresh_subscriptions_store(monkeypatch):
    """Pin the in-memory backend + start from an empty store. Mirrors
    the autouse fixture in test_quota.py."""
    monkeypatch.setattr(
        subscriptions, "_SUPABASE_BACKEND", _NeverConfiguredBackend()
    )
    invalidate_subscription_cache()
    reset_in_memory_backend()
    yield
    invalidate_subscription_cache()
    reset_in_memory_backend()


class _NeverConfiguredBackend:
    def is_configured(self) -> bool:
        return False


def _make_subscription(
    *,
    user_id: str = "user-1",
    tier: str = "pro",
    status: str = "active",
) -> Subscription:
    return Subscription(
        user_id=user_id,
        processor="lemonsqueezy",
        processor_customer_id="cust-1",
        processor_subscription_id=f"sub-{user_id}",
        tier=tier,
        status=status,
        current_period_end=datetime.now(timezone.utc) + timedelta(days=30),
        cancel_at_period_end=False,
        variant_id="variant-pro",
    )


# ─── basic CRUD ─────────────────────────────────────────────────────────


def test_get_active_subscription_returns_none_when_missing():
    assert get_active_subscription("user-1") is None


def test_upsert_and_read_round_trip():
    upsert_subscription(_make_subscription())
    sub = get_active_subscription("user-1")
    assert sub is not None
    assert sub.user_id == "user-1"
    assert sub.tier == "pro"
    assert sub.status == "active"


def test_upsert_replaces_existing_row():
    upsert_subscription(_make_subscription(tier="pro"))
    upsert_subscription(_make_subscription(tier="business"))
    sub = get_active_subscription("user-1")
    assert sub is not None
    assert sub.tier == "business"


def test_get_active_subscription_returns_none_for_empty_user_id():
    """Defensive: an empty user_id must short-circuit without
    calling the backend. Catches the regression where an anonymous
    context handle hits the cache."""
    upsert_subscription(_make_subscription(user_id=""))
    assert get_active_subscription("") is None


# ─── LRU cache invalidation ─────────────────────────────────────────────


def test_cache_hit_returns_cached_subscription():
    """Two reads inside the same minute hit the cache. The first
    read populates it; the second reads from the LRU without
    touching the backend."""
    upsert_subscription(_make_subscription(tier="pro"))
    first = get_active_subscription("user-1")
    # Mutate the underlying store WITHOUT going through
    # upsert_subscription (which invalidates the cache). The cache
    # entry should still reflect the original row.
    subscriptions._IN_MEMORY_BACKEND._store["user-1"] = _make_subscription(
        tier="business"
    )
    second = get_active_subscription("user-1")
    assert first is not None and second is not None
    assert second.tier == first.tier == "pro"


def test_upsert_invalidates_cache():
    """The webhook handler calls upsert_subscription, which must
    drop cached entries so the next gate check sees the new state
    immediately rather than waiting for the minute boundary."""
    upsert_subscription(_make_subscription(tier="pro"))
    assert get_active_subscription("user-1").tier == "pro"
    upsert_subscription(_make_subscription(tier="business"))
    assert get_active_subscription("user-1").tier == "business"


def test_explicit_invalidation_clears_cache():
    """`invalidate_subscription_cache()` clears entries even when
    the underlying store is mutated out-of-band. Used in tests and
    on process-wide subscription refreshes."""
    upsert_subscription(_make_subscription(tier="pro"))
    assert get_active_subscription("user-1").tier == "pro"
    subscriptions._IN_MEMORY_BACKEND._store["user-1"] = _make_subscription(
        tier="business"
    )
    invalidate_subscription_cache()
    assert get_active_subscription("user-1").tier == "business"


def test_minute_bucket_is_yyyy_mm_dd_thh_mm():
    """The cache key format is locked because `_cached_read` hashes
    it. A format change without coordination would silently rebucket
    every active user (a moderate stampede on Supabase) -- catch the
    drift here."""
    moment = datetime(2026, 5, 14, 23, 30, tzinfo=timezone.utc)
    assert _current_minute_bucket(moment) == "2026-05-14T23:30"


def test_minute_bucket_changes_on_minute_boundary():
    """Two timestamps one second apart but spanning a minute
    boundary produce different bucket strings -- this is the
    mechanism behind the natural 60-second TTL."""
    before = datetime(2026, 5, 14, 23, 29, 59, tzinfo=timezone.utc)
    after = datetime(2026, 5, 14, 23, 30, 0, tzinfo=timezone.utc)
    assert _current_minute_bucket(before) != _current_minute_bucket(after)


# ─── webhook idempotency log ────────────────────────────────────────────


def test_has_processed_event_returns_false_for_unknown_event():
    assert has_processed_event("evt-1") is False


def test_mark_event_processed_then_has_processed_event():
    mark_event_processed("evt-1", "subscription_created")
    assert has_processed_event("evt-1") is True


def test_has_processed_event_returns_false_for_empty_id():
    """Defensive: an empty event_id must short-circuit to False
    rather than reporting "yes, the empty string was processed".
    The webhook router doesn't call mark_event_processed in that
    case, but the read API has to be safe under arbitrary inputs."""
    mark_event_processed("", "subscription_created")
    assert has_processed_event("") is False
