"""Tier resolution + cap matrix for AI Job Agent quota gates.

Single source of truth for which subscription tier an authenticated
user is on and what monthly / lifetime / persistent caps apply at that
tier. Every quota gate (tailored applications, premium applications,
resume-builder sessions, assistant turns, resume parses, job searches,
saved jobs, saved workspaces) reads from `TIER_CAPS` keyed by the tier
returned from `resolve_user_tier`. No other module should re-derive
the tier — that's the whole point of this indirection.

Tier resolution intentionally returns ``"free"`` for every user in the
initial enforcement PRs. When Stripe (or whatever billing surface we
land on) ships, swap the body of `resolve_user_tier` to look up the
user's active subscription. Every call site already routes through
this helper, so there is exactly one place to flip when payments go
live. The shim is the canary — if its return type stays Literal but
the body grows, downstream gates don't need to change at all.

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

from typing import Literal

from src.schemas import AppUserRecord


Tier = Literal["free", "pro", "business"]


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


def resolve_user_tier(app_user: AppUserRecord | None) -> Tier:
    """Resolve the active subscription tier for an authenticated user.

    Returns ``"free"`` for every user in this PR — intentionally. When
    Stripe (or the eventual billing surface) lands, swap the body of
    this function to consult the user's actual subscription. Every
    quota gate already routes through here, so there's exactly one
    place to update when payments go live.

    The `app_user` argument is currently unused. We accept it (and
    reference its id via the local binding below) so the signature is
    stable across the payment cutover — gates pass `app_user` today
    and they'll keep passing `app_user` tomorrow.

    Accepts `None` defensively because some upstream paths (anonymous
    workflows, tests with bare contexts) hand off without a synced app
    user. Anonymous traffic is "free" by definition.
    """
    # Touch app_user.id so the intent of "we'll read this later" is
    # explicit in the diff. The leading underscore signals
    # intentionally-unused to readers and lint configs.
    _user_id = getattr(app_user, "id", None)
    return "free"


__all__ = [
    "TIER_CAPS",
    "UNLIMITED",
    "Tier",
    "resolve_user_tier",
    "retention_days_for_tier",
]
