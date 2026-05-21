"""Tier resolution shim + TIER_CAPS matrix.

These tests pin five invariants:

  1. `resolve_user_tier` resolves to "free" for users with no
     subscription row, and to the subscription's tier for users
     whose row is active + within the paid period. Each LS
     subscription status maps deterministically to a tier; the
     mapping is the contract between the webhook handler and the
     gate.

  2. TIER_CAPS contains exactly the three tiers we advertise. Adding
     or removing a tier without updating the pricing UI is a drift
     bug; the assertion catches it at PR time.

  3. Every tier exposes the FULL counter set. A missing counter would
     KeyError at gate-check time, which is annoying to discover in
     production.

  4. Each tier's values match the locked brief table. If the pricing
     page advertises 20 tailored applications and the backend lets a
     Pro user run 200, somebody's getting a refund.

  5. The resolver never trusts `app_user.plan_tier` -- the
     subscription row is the only source of truth. A stale plan_tier
     on the app_users row must not let a Free user run Pro gates.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from backend import subscriptions
from backend.subscriptions import (
    Subscription,
    invalidate_subscription_cache,
    reset_in_memory_backend,
    upsert_subscription,
)
from backend.tiers import (
    TIER_CAPS,
    UNLIMITED,
    Tier,
    resolve_user_tier,
)
from src.schemas import AppUserRecord


@pytest.fixture(autouse=True)
def _fresh_subscriptions_store(monkeypatch):
    """Force every test to use the in-memory subscriptions backend and
    start from an empty store. Mirrors the autouse fixture in
    test_quota.py so individual tests don't have to opt in.
    """
    monkeypatch.setattr(
        subscriptions, "_SUPABASE_BACKEND", _NeverConfiguredBackend()
    )
    invalidate_subscription_cache()
    reset_in_memory_backend()
    yield
    invalidate_subscription_cache()
    reset_in_memory_backend()


class _NeverConfiguredBackend:
    """Stub used to force `_select_backend` to pick the in-memory
    path. Mirrors `_NeverConfiguredBackend` in test_quota.py."""

    def is_configured(self) -> bool:
        return False


def _future(days: int = 30) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)


def _past(days: int = 1) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


_PERIOD_END_UNSET = object()


def _make_subscription(
    *,
    user_id: str = "user-1",
    tier: str = "pro",
    status: str = "active",
    period_end: datetime | None | object = _PERIOD_END_UNSET,
    cancel_at_period_end: bool = False,
) -> Subscription:
    # Use a sentinel for the default so callers can pass `None`
    # explicitly to mean "no period_end" (defensively-NULL row)
    # without the helper substituting a future date. None and the
    # sentinel are distinct.
    if period_end is _PERIOD_END_UNSET:
        resolved_period_end: datetime | None = _future()
    else:
        resolved_period_end = period_end  # type: ignore[assignment]
    return Subscription(
        user_id=user_id,
        processor="lemonsqueezy",
        processor_customer_id="cust-1",
        processor_subscription_id=f"sub-{user_id}",
        tier=tier,
        status=status,
        current_period_end=resolved_period_end,
        cancel_at_period_end=cancel_at_period_end,
        variant_id="variant-pro",
    )


# ─── resolve_user_tier ──────────────────────────────────────────────────


@pytest.fixture
def free_user() -> AppUserRecord:
    """Default app-user shape — what `_build_fallback_app_user_record`
    produces for an anonymous Google sign-in. plan_tier defaults to
    ``"free"`` on AppUserRecord so we exercise the realistic baseline.
    """
    return AppUserRecord(
        id="00000000-0000-4000-8000-000000000001",
        email="someone@example.com",
    )


def test_resolves_to_free_when_no_subscription_row(free_user):
    """A user with no subscription row is on Free -- the default
    state after sign-up. The resolver never auto-creates a row; it
    just reads."""
    assert resolve_user_tier(free_user) == "free"


def test_resolver_ignores_app_user_plan_tier(free_user):
    """Even if the app_users row says ``"pro"``, the resolver only
    consults the subscriptions table. plan_tier on AppUserRecord is
    legacy state that we keep around for backwards compatibility
    with the older quota service, but it's not the source of truth
    for the post-LS world.

    Catches the regression where a future PR threads
    ``app_user.plan_tier`` back into the gate -- the test fails
    because the subscriptions store is empty here.
    """
    user = AppUserRecord(id="user-pro", plan_tier="pro")
    assert resolve_user_tier(user) == "free"


def test_resolver_accepts_none_user():
    """Anonymous traffic (no auth, or auth resolution that failed
    open) must resolve to ``"free"`` without crashing — those flows
    pass `None` defensively."""
    assert resolve_user_tier(None) == "free"


def test_resolver_accepts_user_with_empty_id():
    """An AppUserRecord with id="" must resolve to Free without
    issuing a Supabase lookup. Defensive: shouldn't happen in
    practice but the helper carries through unauth'd contexts in
    some test scaffolds."""
    user = AppUserRecord(id="", email="someone@example.com")
    assert resolve_user_tier(user) == "free"


# ─── subscription status -> tier mapping ────────────────────────────────


def test_active_pro_subscription_resolves_to_pro(free_user):
    """A row with status="active" and a future period_end grants
    the row's tier to the user. The happy path for every paid user
    most of the time."""
    upsert_subscription(_make_subscription(user_id=free_user.id, tier="pro"))
    assert resolve_user_tier(free_user) == "pro"


def test_active_business_subscription_resolves_to_business(free_user):
    upsert_subscription(
        _make_subscription(user_id=free_user.id, tier="business")
    )
    assert resolve_user_tier(free_user) == "business"


def test_cancelled_subscription_within_period_keeps_tier(free_user):
    """LS "cancelled" status = user clicked cancel but the paid
    period hasn't ended yet. Keep tier access; downgrade kicks in
    only after current_period_end."""
    upsert_subscription(
        _make_subscription(
            user_id=free_user.id,
            tier="pro",
            status="cancelled",
            cancel_at_period_end=True,
        )
    )
    assert resolve_user_tier(free_user) == "pro"


def test_past_due_subscription_keeps_tier(free_user):
    """LS retries failed payments for ~14 days. During that window
    status="past_due"; we still grant tier access so a transient card
    decline doesn't immediately downgrade a paying user. Final
    downgrade happens when LS sends subscription_expired (mapped to
    status="expired")."""
    upsert_subscription(
        _make_subscription(
            user_id=free_user.id,
            tier="pro",
            status="past_due",
        )
    )
    assert resolve_user_tier(free_user) == "pro"


def test_expired_subscription_resolves_to_free(free_user):
    """status="expired" is the terminal downgrade. LS sends
    subscription_expired after the dunning retries are exhausted."""
    upsert_subscription(
        _make_subscription(
            user_id=free_user.id,
            tier="pro",
            status="expired",
        )
    )
    assert resolve_user_tier(free_user) == "free"


def test_paused_subscription_resolves_to_free(free_user):
    """Pausing a subscription downgrades the user to Free until
    they unpause -- LS's subscription_unpaused webhook flips status
    back to "active"."""
    upsert_subscription(
        _make_subscription(
            user_id=free_user.id,
            tier="pro",
            status="paused",
        )
    )
    assert resolve_user_tier(free_user) == "free"


def test_active_status_with_past_period_resolves_to_free(free_user):
    """Even with status="active", a period_end in the past means
    the user shouldn't have tier access. Defensive against a stale
    webhook -- LS should have sent subscription_expired by then,
    but if it didn't, the resolver still does the right thing."""
    upsert_subscription(
        _make_subscription(
            user_id=free_user.id,
            tier="pro",
            status="active",
            period_end=_past(),
        )
    )
    assert resolve_user_tier(free_user) == "free"


def test_cancelled_status_with_past_period_resolves_to_free(free_user):
    """Once the paid period ends on a cancelled subscription, the
    user falls back to Free. The /cancelled grace window has
    expired."""
    upsert_subscription(
        _make_subscription(
            user_id=free_user.id,
            tier="pro",
            status="cancelled",
            period_end=_past(),
            cancel_at_period_end=True,
        )
    )
    assert resolve_user_tier(free_user) == "free"


def test_unknown_tier_value_resolves_to_free(free_user):
    """A tier value outside {"pro", "business"} (typo or future
    tier we haven't shipped) falls back to Free rather than
    KeyError-ing in TIER_CAPS. Defensive against schema drift."""
    upsert_subscription(
        _make_subscription(
            user_id=free_user.id,
            tier="enterprise",  # not in _PAID_TIERS
            status="active",
        )
    )
    assert resolve_user_tier(free_user) == "free"


def test_subscription_without_period_end_resolves_to_free(free_user):
    """An "active" row with NULL current_period_end is treated as
    Free defensively -- the webhook is meant to always populate
    that column on subscription_created. Missing values indicate a
    bug we'd rather catch on the free side."""
    upsert_subscription(
        _make_subscription(
            user_id=free_user.id,
            tier="pro",
            status="active",
            period_end=None,
        )
    )
    assert resolve_user_tier(free_user) == "free"


# ─── TIER_CAPS shape ────────────────────────────────────────────────────


def test_all_advertised_tiers_present():
    assert set(TIER_CAPS.keys()) == {"free", "pro", "business"}


def test_every_tier_exposes_full_counter_set():
    """Every tier must have every counter — a missing key would
    KeyError at gate-check time. Steps 4-8 plug into this matrix
    directly, so the shape has to be tight before they land."""
    expected_counters = {
        "tailored_applications",
        "premium_applications",
        "resume_builder_sessions",
        "assistant_turns",
        "resume_parses",
        # Unified weekly LLM token meter (report.md "Unified LLM token
        # meter"). Metered via enforce_llm_budget / record_llm_token_
        # usage, but it still carries a per-tier cap in this matrix.
        "llm_tokens",
        "job_searches",
        "saved_jobs",
        "saved_workspaces",
    }
    for tier_name, caps in TIER_CAPS.items():
        assert set(caps.keys()) == expected_counters, (
            f"tier {tier_name!r} is missing counters: "
            f"{expected_counters - set(caps.keys())!r}"
        )


# ─── per-tier values match the brief's locked table ─────────────────────


def test_free_tier_caps_match_brief():
    free = TIER_CAPS["free"]
    # The four per-feature LLM gates are SUPERSEDED by the llm_tokens
    # meter (T4 of the token-meter migration) — loosened to UNLIMITED
    # so the weekly token meter is the single LLM gate.
    assert free["tailored_applications"] == UNLIMITED
    assert free["resume_builder_sessions"] == UNLIMITED
    assert free["assistant_turns"] == UNLIMITED
    assert free["resume_parses"] == UNLIMITED
    # premium_applications STAYS — Pro+ only, cap 0 means "no premium
    # runs allowed", reported as "upgrade to Pro". It is the
    # premium-model entitlement, not a usage count.
    assert free["premium_applications"] == 0
    # Unified weekly LLM token meter — the primary LLM gate.
    assert free["llm_tokens"] == 90_000
    assert free["job_searches"] == 50
    assert free["saved_jobs"] == 5
    assert free["saved_workspaces"] == 1


def test_pro_tier_caps_match_brief():
    pro = TIER_CAPS["pro"]
    # Superseded LLM gates — UNLIMITED post-migration (see free-tier
    # test). premium_applications stays as the premium-model gate.
    assert pro["tailored_applications"] == UNLIMITED
    assert pro["resume_builder_sessions"] == UNLIMITED
    assert pro["assistant_turns"] == UNLIMITED
    assert pro["resume_parses"] == UNLIMITED
    assert pro["premium_applications"] == 5
    assert pro["llm_tokens"] == 1_000_000
    # "Unlimited" on the pricing page maps to the UNLIMITED sentinel
    # so check_and_increment short-circuits without an upsert.
    assert pro["job_searches"] == UNLIMITED
    assert pro["saved_jobs"] == 1000
    assert pro["saved_workspaces"] == 5


def test_business_tier_caps_match_brief():
    business = TIER_CAPS["business"]
    # Superseded LLM gates — UNLIMITED post-migration (see free-tier
    # test). premium_applications stays as the premium-model gate.
    assert business["tailored_applications"] == UNLIMITED
    assert business["resume_builder_sessions"] == UNLIMITED
    assert business["assistant_turns"] == UNLIMITED
    assert business["resume_parses"] == UNLIMITED
    assert business["premium_applications"] == 25
    assert business["llm_tokens"] == 4_000_000
    assert business["job_searches"] == UNLIMITED
    assert business["saved_jobs"] == UNLIMITED
    assert business["saved_workspaces"] == UNLIMITED


# ─── invariants across tiers ────────────────────────────────────────────


def test_higher_tier_never_has_smaller_cap():
    """A paid tier must never have a SMALLER cap than free for the
    same counter. Catches the easy copy-paste bug where someone
    shuffles the dict and gets the wrong numbers in the wrong tier.

    UNLIMITED (-1) is treated as "greater than any finite cap" for
    this check — that's the product intent even though the sentinel
    value happens to be negative."""
    tiers: list[Tier] = ["free", "pro", "business"]
    counter_names = list(TIER_CAPS["free"].keys())

    def _rank(cap: int) -> float:
        return float("inf") if cap == UNLIMITED else float(cap)

    for counter in counter_names:
        values = [_rank(TIER_CAPS[t][counter]) for t in tiers]
        assert values == sorted(values), (
            f"counter {counter!r} not monotonically non-decreasing "
            f"across {tiers!r}: {values!r}"
        )


def test_unlimited_is_negative_sentinel():
    """check_and_increment short-circuits with a ``cap < 0`` test, so
    the sentinel must be negative. Locking the value (-1) here makes
    it a breaking-change test if someone tries to switch to e.g.
    ``None`` or ``0`` — both of which would silently change behavior."""
    assert UNLIMITED == -1
    assert UNLIMITED < 0
