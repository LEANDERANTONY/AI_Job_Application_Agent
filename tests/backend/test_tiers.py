"""Tier resolution shim + TIER_CAPS matrix.

Step 1 of the tier-enforcement series. These tests pin four invariants:

  1. `resolve_user_tier` returns ``"free"`` for every user today.
     When Stripe lands, this test gets updated alongside the resolver
     — the test is the canary that signals tier behavior has changed.

  2. TIER_CAPS contains exactly the three tiers we advertise. Adding
     or removing a tier without updating the pricing UI is a drift
     bug; the assertion catches it at PR time.

  3. Every tier exposes the FULL counter set. A missing counter would
     KeyError at gate-check time, which is annoying to discover in
     production.

  4. Each tier's values match the locked brief table. If the pricing
     page advertises 20 tailored applications and the backend lets a
     Pro user run 200, somebody's getting a refund.
"""
from __future__ import annotations

import pytest

from backend.tiers import (
    TIER_CAPS,
    UNLIMITED,
    Tier,
    resolve_user_tier,
)
from src.schemas import AppUserRecord


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


def test_every_user_resolves_to_free_today(free_user):
    assert resolve_user_tier(free_user) == "free"


def test_resolver_ignores_app_user_plan_tier_today():
    """Even if the app_users row says ``"pro"`` somehow, the shim
    returns ``"free"`` until Stripe lands. The shim is the only source
    of truth — call sites must not consult app_user.plan_tier
    directly."""
    user = AppUserRecord(id="user-pro", plan_tier="pro")
    assert resolve_user_tier(user) == "free"


def test_resolver_accepts_none_user():
    """Anonymous traffic (no auth, or auth resolution that failed
    open) must resolve to ``"free"`` without crashing — those flows
    pass `None` defensively. The gate that wraps this call still
    rejects unauthenticated /workspace/run, but the resolver is not
    where that rejection lives."""
    assert resolve_user_tier(None) == "free"


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
    assert free["tailored_applications"] == 3
    # Premium is Pro+ only. Cap of 0 means "no premium runs allowed",
    # which the /workspace/run handler reports as "upgrade to Pro" —
    # an explicit, distinct UX from "quota exhausted".
    assert free["premium_applications"] == 0
    assert free["resume_builder_sessions"] == 1
    assert free["assistant_turns"] == 20
    assert free["resume_parses"] == 3
    assert free["job_searches"] == 50
    assert free["saved_jobs"] == 5
    assert free["saved_workspaces"] == 1


def test_pro_tier_caps_match_brief():
    pro = TIER_CAPS["pro"]
    assert pro["tailored_applications"] == 20
    assert pro["premium_applications"] == 5
    assert pro["resume_builder_sessions"] == 3
    assert pro["assistant_turns"] == 150
    assert pro["resume_parses"] == 25
    # "Unlimited" on the pricing page maps to the UNLIMITED sentinel
    # so check_and_increment short-circuits without an upsert.
    assert pro["job_searches"] == UNLIMITED
    assert pro["saved_jobs"] == 1000
    assert pro["saved_workspaces"] == 5


def test_business_tier_caps_match_brief():
    business = TIER_CAPS["business"]
    assert business["tailored_applications"] == 80
    assert business["premium_applications"] == 25
    assert business["resume_builder_sessions"] == 15
    assert business["assistant_turns"] == 500
    assert business["resume_parses"] == 100
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
