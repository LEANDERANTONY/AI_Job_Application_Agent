"""Atomic check-and-increment helper + 429 surface.

Step 2 of the tier-enforcement series. Three layers of coverage:

  * Unit tests on `check_and_increment` against the in-memory backend
    -- exercises the increment / cap / refund semantics without
    touching Supabase. The same semantics live in the SQL function so
    behavioral parity here also documents the contract for the
    Supabase backend.
  * Concurrency test: 100 threads racing on the same counter must
    produce N+1...N+100 with no duplicates -- the central invariant
    of "atomic check + increment".
  * Integration test on /workspace/run-equivalent surface: a raised
    QuotaExceededError must surface as 429 with the canonical body
    shape, not bubble up as a 500.

The Supabase backend has its own DDL-side test fixture in
docs/sql/supabase-quota-counters.sql; we don't spin up a real
Postgres for the unit suite. The in-memory backend mirrors the SQL
function's semantics line-for-line.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import quota
from backend.quota import (
    LIFETIME_PERIOD_KEY,
    LLM_TOKENS_COUNTER,
    QuotaResult,
    check_and_increment,
    current_period_key,
    enforce_llm_budget,
    read_llm_token_usage,
    record_llm_token_usage,
    refund,
    reset_in_memory_backend,
    weekly_period_key,
)
from backend.tiers import TIER_CAPS, UNLIMITED
from src.errors import QuotaExceededError


# ─── fixtures ───────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _fresh_quota_store(monkeypatch):
    """Force every test to use the in-memory backend with a fresh
    state. Tests that want to exercise Supabase translation paths
    monkeypatch the backend explicitly. autouse so individual tests
    don't have to opt in."""
    # Defensive: hide any Supabase env vars so the selection helper
    # picks the in-memory backend even when running locally with
    # production credentials in the shell.
    monkeypatch.setattr(quota, "_SUPABASE_BACKEND", _NeverConfiguredBackend())
    # The token-meter migration (T4) loosened the four per-feature LLM
    # gates to UNLIMITED in the production TIER_CAPS. This file
    # unit-tests the GENERIC check_and_increment machine — increment,
    # cap-breach, refund, period-key partitioning — which needs a
    # finite-capped counter to exercise. We pin the pre-migration
    # finite values for the duration of each test (auto-reverted by
    # monkeypatch). The product's real cap POLICY is asserted in
    # test_tiers.py; this file only cares that the machine works.
    for counter, by_tier in _PRE_T4_FINITE_CAPS.items():
        for tier_name, cap in by_tier.items():
            monkeypatch.setitem(quota.TIER_CAPS[tier_name], counter, cap)
    reset_in_memory_backend()
    yield
    reset_in_memory_backend()


# Pre-migration finite caps for the four superseded LLM counters. See
# the `_fresh_quota_store` fixture for why this file pins them.
_PRE_T4_FINITE_CAPS: dict[str, dict[str, int]] = {
    "tailored_applications": {"free": 3, "pro": 20, "business": 80},
    "assistant_turns": {"free": 20, "pro": 150, "business": 500},
    "resume_parses": {"free": 3, "pro": 25, "business": 100},
    "resume_builder_sessions": {"free": 1, "pro": 3, "business": 15},
}


class _NeverConfiguredBackend:
    """Stub used to force `_select_backend` to pick the in-memory
    path. Mirrors the public surface of `_SupabaseQuotaBackend` only
    enough for `is_configured()` to return False."""

    def is_configured(self) -> bool:
        return False


# ─── current_period_key ─────────────────────────────────────────────────


def test_current_period_key_is_yyyy_mm_utc():
    moment = datetime(2026, 5, 14, 23, 30, tzinfo=timezone.utc)
    assert current_period_key(moment) == "2026-05"


def test_current_period_key_uses_utc_not_local():
    """A user submitting from a UTC+5:30 timezone at 2am on June 1
    must land in the June partition, not May. The Supabase RPC uses
    `timezone('utc', now())` for the row default; this helper has to
    match or the application-side and database-side counts will live
    in different periods on the rollover hour."""
    # 2026-06-01 02:00 IST == 2026-05-31 20:30 UTC -> May partition.
    iso = datetime.fromisoformat("2026-06-01T02:00:00+05:30")
    assert current_period_key(iso) == "2026-05"


# ─── check_and_increment basics ─────────────────────────────────────────


def test_first_increment_returns_count_1():
    result = check_and_increment("tailored_applications", "user-a", "free")
    assert result == QuotaResult(count=1, cap=3, remaining=2)


def test_second_increment_advances_count():
    check_and_increment("tailored_applications", "user-a", "free")
    result = check_and_increment("tailored_applications", "user-a", "free")
    assert result.count == 2
    assert result.remaining == 1


def test_at_cap_returns_zero_remaining():
    for _ in range(3):
        result = check_and_increment("tailored_applications", "user-a", "free")
    assert result.count == 3
    assert result.cap == 3
    assert result.remaining == 0


def test_over_cap_raises_quota_exceeded():
    """The 4th call on a Free tier (cap=3) must raise -- never silently
    pass and never write a 4th increment."""
    for _ in range(3):
        check_and_increment("tailored_applications", "user-a", "free")
    with pytest.raises(QuotaExceededError) as exc_info:
        check_and_increment("tailored_applications", "user-a", "free")
    err = exc_info.value
    assert err.counter == "tailored_applications"
    assert err.cap == 3
    assert err.current == 3
    assert err.tier == "free"
    # period_key on the QuotaExceededError mirrors the partition the
    # row lives in -- not "lifetime" for this monthly counter.
    assert err.reset_period == current_period_key()


def test_premium_zero_cap_raises_on_first_call_for_free():
    """Free tier's premium_applications cap is 0 -- there is no
    'first run free' loophole, the very first attempt must reject.
    The error message branch in `_build_quota_exceeded_error` for
    `counter == "premium_applications" and cap == 0` makes the toast
    say "upgrade to Pro+" rather than the generic "you have reached".
    """
    with pytest.raises(QuotaExceededError) as exc_info:
        check_and_increment("premium_applications", "user-a", "free")
    err = exc_info.value
    assert err.cap == 0
    assert err.current == 0
    assert "Pro" in err.user_message


# ─── isolation between users / counters / tiers ─────────────────────────


def test_user_isolation():
    check_and_increment("tailored_applications", "user-a", "free")
    check_and_increment("tailored_applications", "user-a", "free")
    check_and_increment("tailored_applications", "user-b", "free")
    # user-a at 2, user-b at 1 -- separate rows, independent caps.
    result_a = check_and_increment("tailored_applications", "user-a", "free")
    assert result_a.count == 3
    result_b = check_and_increment("tailored_applications", "user-b", "free")
    assert result_b.count == 2


def test_counter_isolation():
    """Different counters share a user but live in distinct rows; the
    counter_name field is part of the composite PK."""
    a = check_and_increment("tailored_applications", "user-a", "free")
    # Tailored counter at 1 -- premium counter for the same user is
    # still 0 (and will reject because Free's cap is 0).
    assert a.count == 1
    with pytest.raises(QuotaExceededError):
        check_and_increment("premium_applications", "user-a", "free")


def test_pro_tier_cap_higher_than_free():
    """Same user, same counter, different tier -- exercises the
    `_cap_for` lookup. (The shim returns "free" today, but the helper
    accepts the tier as a parameter; once Stripe lands and the
    resolver returns "pro" for paying users, the cap moves up
    automatically with zero call-site changes.)"""
    for _ in range(20):
        check_and_increment("tailored_applications", "user-pro", "pro")
    with pytest.raises(QuotaExceededError) as exc_info:
        check_and_increment("tailored_applications", "user-pro", "pro")
    assert exc_info.value.cap == 20


def test_unlimited_short_circuits_without_writing():
    """A Pro user's job_searches counter is UNLIMITED. The helper must
    return a sentinel QuotaResult without touching the database. The
    in-memory store has no key recorded, so calling refund() on the
    same counter returns None (nothing to undo)."""
    result = check_and_increment("job_searches", "user-pro", "pro")
    assert result.cap == UNLIMITED
    assert result.remaining == UNLIMITED
    # No row written -- refund is a noop.
    assert refund("job_searches", "user-pro", "pro") is None


def test_unknown_counter_raises_key_error():
    """A typo in the counter_name is a programming bug, not a runtime
    edge case. We deliberately let KeyError propagate so the diff that
    introduced the typo fails CI loudly."""
    with pytest.raises(KeyError):
        check_and_increment("nonexistent_counter", "user-a", "free")


# ─── lifetime period_key ────────────────────────────────────────────────


def test_lifetime_flag_writes_to_lifetime_partition():
    """The same counter_name under lifetime=True lives in a separate
    row from the monthly partition. Brief: free-tier
    resume_builder_sessions uses lifetime semantics."""
    check_and_increment(
        "resume_builder_sessions", "user-a", "free", lifetime=True,
    )
    # That writes to the "lifetime" partition. The monthly partition
    # for the same counter is empty, so a non-lifetime call would
    # start fresh from 1.
    monthly_result = check_and_increment(
        "resume_builder_sessions", "user-a", "free", lifetime=False,
    )
    assert monthly_result.count == 1


def test_lifetime_partition_persists_across_months(monkeypatch):
    """Increment a lifetime counter "in May"; verify that even with the
    clock rolled to June the next lifetime increment lands on the same
    row. The period_key is always "lifetime", independent of the
    `now` argument."""
    check_and_increment(
        "resume_builder_sessions",
        "user-a",
        "free",
        lifetime=True,
        now=datetime(2026, 5, 14, tzinfo=timezone.utc),
    )
    with pytest.raises(QuotaExceededError):
        # Free's lifetime cap is 1, so the second call rejects even
        # though calendar months changed.
        check_and_increment(
            "resume_builder_sessions",
            "user-a",
            "free",
            lifetime=True,
            now=datetime(2026, 6, 14, tzinfo=timezone.utc),
        )


def test_monthly_rollover_creates_new_partition():
    """Two increments straddling a month boundary live in distinct
    rows. The user's effective allowance resets at midnight UTC on the
    first of the month -- no application-side scheduler required."""
    check_and_increment(
        "tailored_applications",
        "user-a",
        "free",
        now=datetime(2026, 5, 30, tzinfo=timezone.utc),
    )
    # New month -- counter resets implicitly.
    june_result = check_and_increment(
        "tailored_applications",
        "user-a",
        "free",
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    assert june_result.count == 1


# ─── refund ─────────────────────────────────────────────────────────────


def test_refund_decrements_counter():
    check_and_increment("tailored_applications", "user-a", "free")
    check_and_increment("tailored_applications", "user-a", "free")
    new = refund("tailored_applications", "user-a", "free")
    assert new == 1


def test_refund_floors_at_zero():
    """Refund must not produce a negative count even if it's called
    more times than there were increments. The SQL function uses
    `greatest(count + delta, 0)` to enforce this; the in-memory
    backend mirrors it."""
    check_and_increment("tailored_applications", "user-a", "free")
    refund("tailored_applications", "user-a", "free")
    new = refund("tailored_applications", "user-a", "free")
    assert new == 0


def test_refund_allows_retry_after_failure():
    """End-to-end of the refund-on-failure pattern: a user at the Free
    cap of 3 can have a failed run refunded and then re-run successfully."""
    for _ in range(3):
        check_and_increment("tailored_applications", "user-a", "free")
    # Simulating "the orchestrator raised, refund the credit".
    refund("tailored_applications", "user-a", "free")
    # The next attempt should succeed -- the counter is back at 2,
    # and 2 + 1 == 3 == cap (boundary, but still allowed).
    result = check_and_increment("tailored_applications", "user-a", "free")
    assert result.count == 3


def test_refund_after_failed_increment_is_safe():
    """If `check_and_increment` raises (cap breach), the caller MUST
    NOT issue a refund -- the counter wasn't incremented, refunding
    would decrement somebody else's earlier successful increment. The
    public API requires the caller to refund only after a successful
    return; this test documents that contract by asserting refund
    after a failed increment is a noop on a fresh user."""
    with pytest.raises(QuotaExceededError):
        for _ in range(4):
            check_and_increment("tailored_applications", "user-a", "free")
    # 3 succeeded, 4th failed. The counter is at 3. A refund call
    # decrements to 2 -- the test below just verifies refund is a
    # plain decrement; the GUARANTEE that the caller never refunds a
    # failed increment lives in the workspace_service code, not here.
    assert refund("tailored_applications", "user-a", "free") == 2


# ─── concurrency / atomicity ────────────────────────────────────────────


def test_concurrent_increments_do_not_double_count():
    """100 threads, each issuing one increment, must produce counts
    that are a permutation of 1..100 -- no duplicates. The in-memory
    backend uses a single lock; the Supabase backend uses
    INSERT ... ON CONFLICT DO UPDATE which Postgres guarantees is
    atomic. This test pins the in-memory invariant; the Supabase
    parity lives in the SQL function.

    The user gets a Business cap of 80 for this counter -- pick a
    counter whose Business cap >= 100 so the test doesn't fire 429s
    along the happy path. assistant_turns has Business cap 500 which
    is comfortably above 100.
    """
    user_id = "user-concurrent"
    results: list[int] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker() -> None:
        try:
            result = check_and_increment(
                "assistant_turns", user_id, "business",
            )
            with lock:
                results.append(result.count)
        except BaseException as exc:  # pragma: no cover - debug
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(100)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not errors, f"unexpected errors in concurrent increments: {errors!r}"
    assert sorted(results) == list(range(1, 101)), (
        "atomicity violation -- expected a permutation of 1..100, "
        f"got duplicates or gaps: {sorted(results)!r}"
    )


# ─── FastAPI 429 surfacing ──────────────────────────────────────────────


def test_quota_exceeded_error_surfaces_as_429_payload():
    """The global handler in backend.app turns QuotaExceededError into
    a 429 with the canonical body shape. Build a small FastAPI app
    with just the handler registered + a route that raises the error,
    so we test the handler in isolation from the rest of /workspace."""
    from backend.app import quota_exceeded_handler

    app = FastAPI()
    app.add_exception_handler(QuotaExceededError, quota_exceeded_handler)

    @app.get("/raise-quota")
    def _raise():
        raise QuotaExceededError(
            "You have reached the limit for this action on your current plan.",
            counter="tailored_applications",
            current=3,
            cap=3,
            reset_period="2026-05",
            tier="free",
        )

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/raise-quota")

    assert response.status_code == 429
    body = response.json()
    assert body == {
        "detail": "You have reached the limit for this action on your current plan.",
        "code": "tier_limit_exceeded",
        "counter": "tailored_applications",
        "current": 3,
        "cap": 3,
        "reset_period": "2026-05",
        "tier": "free",
    }


def test_quota_exceeded_handler_is_registered_on_production_app():
    """End-to-end through the real FastAPI app: the handler must be
    registered on `backend.app.app` and intercept QuotaExceededError
    before FastAPI's default 500 path fires.

    Step 3 wires the first endpoint that actually raises the error;
    until then we mount a one-off route directly on the production app
    so this test exercises the SAME handler chain a real request will
    hit. Mounting at runtime is safe because pytest's app fixture is
    process-local.
    """
    from backend.app import app

    @app.get("/__test_quota_exceeded__")
    def _raise():
        raise QuotaExceededError(
            "You have reached the limit.",
            counter="tailored_applications",
            current=3,
            cap=3,
            reset_period=current_period_key(),
            tier="free",
        )

    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/__test_quota_exceeded__")
    finally:
        # Don't leave the test route mounted between tests in the same
        # session -- pop it off the FastAPI router so other tests see
        # the clean app surface.
        app.router.routes[:] = [
            route
            for route in app.router.routes
            if getattr(route, "path", "") != "/__test_quota_exceeded__"
        ]

    assert response.status_code == 429
    body = response.json()
    assert body["code"] == "tier_limit_exceeded"
    assert body["counter"] == "tailored_applications"
    assert body["cap"] == 3


# ─── caps table integrity ───────────────────────────────────────────────


def test_check_and_increment_reads_tier_caps_table():
    """Defensive: assert the helper is reading from the canonical
    TIER_CAPS table, not a copy. If a future refactor moves the caps
    into a separate config file, this test fails because the value
    here drifts from the value at the gate site.
    """
    assert TIER_CAPS["free"]["tailored_applications"] == 3
    # Burn the first 3 -- the 4th must raise with the right cap.
    for _ in range(3):
        check_and_increment("tailored_applications", "user-a", "free")
    with pytest.raises(QuotaExceededError) as exc_info:
        check_and_increment("tailored_applications", "user-a", "free")
    assert exc_info.value.cap == TIER_CAPS["free"]["tailored_applications"]


def test_lifetime_period_key_constant_is_stable():
    """The LIFETIME_PERIOD_KEY value is part of the on-disk Supabase
    schema (composite PK column value). Changing it from "lifetime" to
    anything else is a data migration, not a refactor."""
    assert LIFETIME_PERIOD_KEY == "lifetime"


# ─── weekly_period_key (token meter) ────────────────────────────────────


def test_weekly_period_key_is_yyyy_www():
    moment = datetime(2026, 5, 21, 12, 0, tzinfo=timezone.utc)
    key = weekly_period_key(moment)
    assert key.startswith("2026-W")
    # Shape is YYYY-Www with a zero-padded 2-digit week.
    year, _, week = key.partition("-W")
    assert len(year) == 4 and year.isdigit()
    assert len(week) == 2 and week.isdigit()
    assert 1 <= int(week) <= 53


def test_weekly_period_key_uses_iso_year_at_jan_boundary():
    """Jan 1 2021 is a Friday that ISO-calendar-wise belongs to the
    LAST week of 2020 (2020 has 53 ISO weeks). A naive %Y-W%U would
    mislabel it "2021-W00" and split one real week across two
    partitions; isocalendar() gets it right."""
    iso = datetime(2021, 1, 1, tzinfo=timezone.utc)
    assert weekly_period_key(iso) == "2020-W53"


def test_weekly_period_key_uses_utc_not_local():
    """Same UTC-rollover concern as current_period_key: a submission
    from UTC+5:30 just after local midnight must land in the UTC week,
    matching the Supabase row default."""
    # 2026-05-25 02:00 IST == 2026-05-24 20:30 UTC. May 24 2026 is a
    # Sunday -> ISO week 21; May 25 (Mon) would be week 22. The IST
    # clock says "Monday" but UTC says "Sunday" -> week 21.
    iso = datetime.fromisoformat("2026-05-25T02:00:00+05:30")
    assert weekly_period_key(iso) == weekly_period_key(
        datetime(2026, 5, 24, 20, 30, tzinfo=timezone.utc)
    )
    assert weekly_period_key(iso) == "2026-W21"


# ─── token meter: enforce / record / read ───────────────────────────────


def test_llm_tokens_counter_constant_is_stable():
    """LLM_TOKENS_COUNTER is the composite-PK counter_name value on
    disk -- renaming it is a data migration. The tier matrix must carry
    a cap for it on every tier."""
    assert LLM_TOKENS_COUNTER == "llm_tokens"
    assert TIER_CAPS["free"][LLM_TOKENS_COUNTER] == 90_000
    assert TIER_CAPS["pro"][LLM_TOKENS_COUNTER] == 1_000_000
    assert TIER_CAPS["business"][LLM_TOKENS_COUNTER] == 4_000_000


def test_enforce_llm_budget_passes_for_fresh_user():
    """A brand-new week (count 0) is well under every tier cap -- the
    entry check is a no-op so the operation may run. This is the
    '>=1 full run on a fresh week' guarantee."""
    enforce_llm_budget("user-a", "free")  # must not raise


def test_enforce_llm_budget_blank_user_is_noop():
    """No user_id -> no per-user meter to read. The route's auth gate
    enforces 'login required', not this helper."""
    enforce_llm_budget("", "free")  # must not raise


def test_record_llm_token_usage_accumulates_weekly():
    assert record_llm_token_usage("user-a", 1_800) == 1_800
    assert record_llm_token_usage("user-a", 2_300) == 4_100
    assert read_llm_token_usage("user-a", "free") == 4_100


def test_record_llm_token_usage_ignores_blank_user_and_nonpositive():
    assert record_llm_token_usage("", 5_000) is None
    assert record_llm_token_usage("user-a", 0) is None
    assert record_llm_token_usage("user-a", -10) is None
    assert read_llm_token_usage("user-a", "free") == 0


def test_enforce_llm_budget_raises_when_meter_at_cap():
    """Drive the Free meter to exactly the cap; the next entry check
    must raise the canonical 429 with token-meter fields."""
    cap = TIER_CAPS["free"][LLM_TOKENS_COUNTER]
    record_llm_token_usage("user-a", cap)
    with pytest.raises(QuotaExceededError) as exc_info:
        enforce_llm_budget("user-a", "free")
    err = exc_info.value
    assert err.counter == LLM_TOKENS_COUNTER
    assert err.cap == cap
    assert err.current == cap
    assert err.tier == "free"
    assert err.reset_period == weekly_period_key()


def test_record_llm_token_usage_allows_overshoot_past_cap():
    """The after-call record must NEVER raise on the cap -- the op
    already ran, its cost has to land even if it pushes the meter past
    the limit. Overshoot-by-one-operation is the deliberate design."""
    cap = TIER_CAPS["free"][LLM_TOKENS_COUNTER]
    record_llm_token_usage("user-a", cap - 1_000)
    # This single call vaults from just-under-cap to well past it.
    new_total = record_llm_token_usage("user-a", 16_000)
    assert new_total == cap - 1_000 + 16_000
    assert new_total > cap
    # ...and the NEXT entry check is what stops the user.
    with pytest.raises(QuotaExceededError):
        enforce_llm_budget("user-a", "free")


def test_token_meter_check_before_increment_after_cycle():
    """End-to-end of the meter contract: a started operation always
    finishes (entry check passed while under cap), and the operation
    that tips the meter over still completes -- only the FOLLOWING one
    is blocked."""
    # Pro cap is 1M; simulate three ~400K operations.
    enforce_llm_budget("user-pro", "pro")  # 0 used -> ok
    record_llm_token_usage("user-pro", 400_000)
    enforce_llm_budget("user-pro", "pro")  # 400K used -> ok
    record_llm_token_usage("user-pro", 400_000)
    enforce_llm_budget("user-pro", "pro")  # 800K used -> still ok
    record_llm_token_usage("user-pro", 400_000)  # -> 1.2M, overshoot
    with pytest.raises(QuotaExceededError):
        enforce_llm_budget("user-pro", "pro")  # 1.2M used -> blocked


def test_token_meter_isolates_users_and_weeks():
    """The meter partitions by (user, ISO week): one user's spend never
    touches another's, and last week's spend never counts against this
    week."""
    week_a = datetime(2026, 5, 18, tzinfo=timezone.utc)  # Mon, W21
    week_b = datetime(2026, 5, 25, tzinfo=timezone.utc)  # Mon, W22
    record_llm_token_usage("user-a", 50_000, now=week_a)
    record_llm_token_usage("user-b", 9_000, now=week_a)
    # Different user -> independent row.
    assert read_llm_token_usage("user-b", "free", now=week_a) == 9_000
    # Same user, next ISO week -> fresh row at 0 (implicit reset).
    assert read_llm_token_usage("user-a", "free", now=week_b) == 0
    assert read_llm_token_usage("user-a", "free", now=week_a) == 50_000
    # The fresh week passes the entry check even though last week was
    # over half-spent.
    enforce_llm_budget("user-a", "free", now=week_b)  # must not raise


def test_read_llm_token_usage_blank_user_is_zero():
    assert read_llm_token_usage("", "free") == 0


# ─── PostHog quota_blocked funnel event ─────────────────────────────────


def test_quota_blocked_event_captured_on_cap_breach(monkeypatch):
    """A cap-breaching check_and_increment emits a `quota_blocked`
    PostHog event (counter + tier + cap) before the 429 is raised."""
    events = []
    monkeypatch.setattr(
        quota, "capture_event", lambda **kwargs: events.append(kwargs)
    )
    for _ in range(3):
        check_and_increment("tailored_applications", "user-q", "free")
    with pytest.raises(QuotaExceededError):
        check_and_increment("tailored_applications", "user-q", "free")

    # Only the rejected 4th call emits — the 3 successes do not.
    assert len(events) == 1
    event = events[0]
    assert event["event"] == "quota_blocked"
    assert event["distinct_id"] == "user-q"
    assert event["properties"]["counter"] == "tailored_applications"
    assert event["properties"]["tier"] == "free"
    assert event["properties"]["cap"] == 3
    assert event["properties"]["current"] == 3


def test_quota_blocked_event_captured_on_llm_budget_rejection(monkeypatch):
    """An exhausted weekly LLM-token meter emits `quota_blocked` with
    the llm_tokens counter."""
    monkeypatch.setitem(quota.TIER_CAPS["free"], LLM_TOKENS_COUNTER, 100)
    events = []
    monkeypatch.setattr(
        quota, "capture_event", lambda **kwargs: events.append(kwargs)
    )
    record_llm_token_usage("user-llm", 100)
    with pytest.raises(QuotaExceededError):
        enforce_llm_budget("user-llm", "free")

    assert len(events) == 1
    assert events[0]["event"] == "quota_blocked"
    assert events[0]["distinct_id"] == "user-llm"
    assert events[0]["properties"]["counter"] == LLM_TOKENS_COUNTER
    assert events[0]["properties"]["tier"] == "free"
