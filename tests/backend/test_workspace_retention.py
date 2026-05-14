"""Tier-aware saved_workspaces retention sweeper (Step 8).

The sweeper deletes saved_workspaces rows whose age exceeds the
owner's tier retention window:

    free       7 days
    pro        30 days
    business   unbounded (never deleted)

These tests pin six invariants:

  1. `retention_days_for_tier` returns the brief's locked durations.
  2. Free workspaces older than 7d are deleted.
  3. Free workspaces newer than 7d are kept.
  4. Pro workspaces older than 30d are deleted.
  5. Business workspaces of any age are kept.
  6. Tier-downgrade scenario: a workspace owned by a user previously
     on Business but who's now Free gets re-evaluated under Free's
     7-day cutoff on the next sweep. The sweeper re-resolves the
     tier on every pass; nothing is cached across runs.

The sweeper does its real work against Supabase. The tests use a
fake client that records calls, so we exercise the logic without
needing a live database.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.maintenance import (
    SweepSummary,
    sweep_expired_workspaces,
)
from backend.tiers import retention_days_for_tier


NOW = datetime(2026, 5, 14, 12, 0, 0, tzinfo=timezone.utc)


# ─── retention_days_for_tier ────────────────────────────────────────


def test_retention_days_for_tier_matches_locked_table():
    """Lock the per-tier retention numbers against the brief. Drift
    here is a marketing/product mismatch -- the pricing page and the
    sweeper have to agree on what "Free retention" means or the
    backend silently deletes data the user thought they had."""
    assert retention_days_for_tier("free") == 7
    assert retention_days_for_tier("pro") == 30
    assert retention_days_for_tier("business") is None


# ─── sweeper behavior with a fake Supabase client ───────────────────


class _FakeSupabaseTable:
    """Minimal supabase-py-compatible table builder used by the
    sweeper tests. Records every `delete().eq(...).execute()` chain
    so each test can assert which user_ids actually got swept.

    Reading is faked at the call site -- each test instantiates
    `_FakeSupabaseClient` with the workspace rows it wants the
    sweeper to see.
    """

    def __init__(self, *, name: str, rows: list[dict], user_records: list[dict]):
        self.name = name
        self._rows = rows
        self._user_records = user_records
        self._select_cols: str = ""
        self._eq_filters: list[tuple[str, str]] = []
        self._limit: int | None = None
        self._delete_eq: tuple[str, str] | None = None
        self.deleted_user_ids: list[str] = []

    # ── read path ─────────────────────────────────────────────────
    def select(self, cols: str):
        self._select_cols = cols
        self._eq_filters = []
        self._limit = None
        return self

    def eq(self, field: str, value: str):
        if self._delete_eq is not None:
            # We're inside a delete() chain.
            self._delete_eq = (field, str(value))
        else:
            self._eq_filters.append((field, str(value)))
        return self

    def limit(self, count: int):
        self._limit = count
        return self

    # ── delete path ───────────────────────────────────────────────
    def delete(self):
        self._delete_eq = ("", "")
        return self

    def execute(self):
        if self._delete_eq and self._delete_eq[0] == "user_id":
            self.deleted_user_ids.append(self._delete_eq[1])
            self._delete_eq = None
            return _FakeResponse([])
        # Read path.
        if self.name == "app_users":
            for filter_field, filter_value in self._eq_filters:
                if filter_field == "id":
                    for record in self._user_records:
                        if str(record.get("id", "")) == filter_value:
                            return _FakeResponse([record])
                    return _FakeResponse([])
            return _FakeResponse([])
        # Workspaces read.
        return _FakeResponse(list(self._rows))


class _FakeResponse:
    def __init__(self, data: list[dict]):
        self.data = data


class _FakeSupabaseClient:
    """Two-table fake with shared state across the sweep's calls.

    We expose `deleted_user_ids` so each test can assert exactly
    which workspace rows got swept.
    """

    def __init__(
        self,
        *,
        workspaces_table: str,
        workspace_rows: list[dict],
        user_records: list[dict],
    ):
        self._workspaces_table = workspaces_table
        self._workspaces = _FakeSupabaseTable(
            name=workspaces_table,
            rows=workspace_rows,
            user_records=user_records,
        )
        self._app_users = _FakeSupabaseTable(
            name="app_users",
            rows=[],
            user_records=user_records,
        )

    def table(self, name: str):
        if name == self._workspaces_table:
            return self._workspaces
        return self._app_users

    @property
    def deleted_user_ids(self) -> list[str]:
        return self._workspaces.deleted_user_ids


def _ws_row(user_id: str, age_days: float) -> dict:
    """Build a workspace row updated `age_days` ago."""
    return {
        "user_id": user_id,
        "updated_at": (NOW - timedelta(days=age_days)).isoformat(),
    }


def _user_row(user_id: str, plan_tier: str = "free") -> dict:
    return {
        "id": user_id,
        "email": f"{user_id}@example.com",
        "plan_tier": plan_tier,
        "account_status": "active",
    }


def _run_sweep(
    *,
    workspace_rows: list[dict],
    user_records: list[dict],
) -> tuple[SweepSummary, _FakeSupabaseClient]:
    client = _FakeSupabaseClient(
        workspaces_table="saved_workspaces",
        workspace_rows=workspace_rows,
        user_records=user_records,
    )
    summary = sweep_expired_workspaces(
        now=NOW,
        table_name="saved_workspaces",
        client=client,
    )
    return summary, client


def test_free_workspace_older_than_7d_is_deleted():
    """Free retention is 7 days; an 8-day-old workspace is past
    the cutoff and the sweep deletes it."""
    summary, client = _run_sweep(
        workspace_rows=[_ws_row("user-free-old", age_days=8)],
        user_records=[_user_row("user-free-old", "free")],
    )
    assert summary.expired_workspaces_deleted == 1
    assert client.deleted_user_ids == ["user-free-old"]


def test_free_workspace_newer_than_7d_is_kept():
    """A 3-day-old Free workspace is well inside the window; the
    sweep must NOT delete it."""
    summary, client = _run_sweep(
        workspace_rows=[_ws_row("user-free-new", age_days=3)],
        user_records=[_user_row("user-free-new", "free")],
    )
    assert summary.expired_workspaces_deleted == 0
    assert client.deleted_user_ids == []
    assert summary.rows_inspected == 1


def test_pro_workspace_older_than_30d_is_deleted(monkeypatch):
    """Pro retention is 30 days. The shim resolves everyone to Free
    today, so we patch the resolver directly to exercise the Pro
    branch -- this is the test that locks the Pro behavior in for
    when Stripe lands."""
    monkeypatch.setattr(
        "backend.maintenance.resolve_user_tier",
        lambda _user: "pro",
    )
    summary, client = _run_sweep(
        workspace_rows=[_ws_row("user-pro-old", age_days=31)],
        user_records=[_user_row("user-pro-old", "pro")],
    )
    assert summary.expired_workspaces_deleted == 1
    assert client.deleted_user_ids == ["user-pro-old"]


def test_pro_workspace_newer_than_30d_is_kept(monkeypatch):
    """A 20-day-old Pro workspace is inside the 30d window -- kept."""
    monkeypatch.setattr(
        "backend.maintenance.resolve_user_tier",
        lambda _user: "pro",
    )
    summary, client = _run_sweep(
        workspace_rows=[_ws_row("user-pro-new", age_days=20)],
        user_records=[_user_row("user-pro-new", "pro")],
    )
    assert summary.expired_workspaces_deleted == 0
    assert client.deleted_user_ids == []


def test_business_workspace_of_any_age_is_kept(monkeypatch):
    """Business retention is unbounded -- a 999-day-old workspace
    must survive the sweep. The summary's
    business_workspaces_skipped counter increments so operators can
    sanity-check the exemption from the cron log."""
    monkeypatch.setattr(
        "backend.maintenance.resolve_user_tier",
        lambda _user: "business",
    )
    summary, client = _run_sweep(
        workspace_rows=[
            _ws_row("user-biz-1", age_days=999),
            _ws_row("user-biz-2", age_days=10000),
        ],
        user_records=[
            _user_row("user-biz-1", "business"),
            _user_row("user-biz-2", "business"),
        ],
    )
    assert summary.expired_workspaces_deleted == 0
    assert client.deleted_user_ids == []
    assert summary.business_workspaces_skipped == 2


def test_tier_downgrade_reapplies_free_retention(monkeypatch):
    """If a user was Business and got downgraded to Free, the
    next sweep re-resolves their tier and applies Free's 7-day
    retention. The sweeper has no cache across runs -- tier is
    resolved per row, per pass.

    This is the test that locks in the no-cache invariant: a
    business→free downgrade can't be silently masked by stale
    state. The sweep is the authoritative cleanup, so it has to
    react to tier changes the moment the auth row reflects them.
    """
    # First sweep: user is on Business, workspace is 100 days old,
    # nothing is deleted.
    monkeypatch.setattr(
        "backend.maintenance.resolve_user_tier",
        lambda _user: "business",
    )
    summary_pre, client_pre = _run_sweep(
        workspace_rows=[_ws_row("user-downgrade", age_days=100)],
        user_records=[_user_row("user-downgrade", "business")],
    )
    assert summary_pre.expired_workspaces_deleted == 0
    assert client_pre.deleted_user_ids == []
    assert summary_pre.business_workspaces_skipped == 1

    # Now simulate the tier flip: same workspace, same age (100d),
    # but the resolver now returns "free". The 7-day cutoff fires
    # and the row gets deleted.
    monkeypatch.setattr(
        "backend.maintenance.resolve_user_tier",
        lambda _user: "free",
    )
    summary_post, client_post = _run_sweep(
        workspace_rows=[_ws_row("user-downgrade", age_days=100)],
        user_records=[_user_row("user-downgrade", "free")],
    )
    assert summary_post.expired_workspaces_deleted == 1
    assert client_post.deleted_user_ids == ["user-downgrade"]


# ─── boundary / hygiene ─────────────────────────────────────────────


def test_sweep_with_no_service_role_client_logs_and_returns_zero(caplog):
    """If the env vars aren't set, the sweeper can't get a service-
    role client. The brief calls this out: "Document the suggested
    cron line in your final report rather than adding it (the user
    can wire it post-merge)" -- which means the cron will boot in
    environments where the secrets aren't there yet. It must not
    crash on import / first run; it should log and return a zero
    summary."""
    # The default branch -- no client argument, no env vars in the
    # test process -- triggers the "no service role" path.
    summary = sweep_expired_workspaces(client=None)
    assert summary.expired_workspaces_deleted == 0
    assert summary.rows_inspected == 0


def test_mixed_free_workspace_set_only_deletes_the_old_ones():
    """End-to-end smoke: two Free workspaces, one new, one old --
    the sweep deletes exactly the old one and the summary's
    rows_inspected reflects both."""
    summary, client = _run_sweep(
        workspace_rows=[
            _ws_row("user-recent", age_days=2),
            _ws_row("user-stale", age_days=14),
        ],
        user_records=[
            _user_row("user-recent", "free"),
            _user_row("user-stale", "free"),
        ],
    )
    assert summary.rows_inspected == 2
    assert summary.expired_workspaces_deleted == 1
    assert client.deleted_user_ids == ["user-stale"]
