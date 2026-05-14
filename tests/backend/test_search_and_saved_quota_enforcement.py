"""Quota enforcement for /jobs/search, save_saved_job, and
save_workspace_snapshot.

Step 6 of the tier-enforcement series. Three counters, three insertion
points:

  * `job_searches`: monthly counter (Free 50 / Pro UNLIMITED /
    Business UNLIMITED). Standard period-keyed gate via
    `quota.check_and_increment`. UNLIMITED tiers short-circuit and
    never write a row.

  * `saved_jobs`: PERSISTENT row-count cap (Free 5 / Pro 1000 /
    Business UNLIMITED). NOT a period-keyed counter. The gate reads
    the existing row count via `SavedJobsStore.list_jobs(...)` and
    compares to the tier cap; re-saving the same job_id is allowed
    (the store's upsert key is (user_id, job_id), so it's an
    UPDATE).

  * `saved_workspaces`: PERSISTENT row-count cap (Free 1 / Pro 5 /
    Business UNLIMITED). Same row-count pattern as saved_jobs.
    Eviction policy: REJECT at cap (the user deletes explicitly
    before re-saving). No auto-eviction of oldest.

Refund policy divergences (documented in code comments too):
  * job_searches has NO refund-on-failure. Search is cheap (FTS
    read, ~30ms), and an erroring search still consumed a "search
    intent" from the user's perspective.
  * saved_jobs / saved_workspaces have no refund logic because they
    aren't increment-based -- we count rows; nothing to refund.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend import quota
from backend.app import app
from backend.quota import current_period_key, reset_in_memory_backend
from backend.routers import jobs as jobs_router
from backend.services import saved_jobs_service, workspace_persistence_service
from backend.services.auth_session_service import AuthenticatedContext
from backend.tiers import TIER_CAPS
from src.auth_service import AuthSession, AuthUser
from src.errors import QuotaExceededError
from src.schemas import AppUserRecord


client = TestClient(app, raise_server_exceptions=False)


# ─── fixtures ───────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _fresh_quota_backend(monkeypatch):
    """Force in-memory quota backend. Mirrors other quota test modules."""

    class _NeverConfigured:
        def is_configured(self) -> bool:
            return False

    monkeypatch.setattr(quota, "_SUPABASE_BACKEND", _NeverConfigured())
    reset_in_memory_backend()
    yield
    reset_in_memory_backend()


@pytest.fixture(autouse=True)
def _disable_rate_limiter(monkeypatch):
    """Disable slowapi for these tests. The job_searches gate needs to
    fire 50+ times in a single test; the default LIMIT_LLM budget
    (30/minute) trips first. The tier-quota machinery is what these
    tests actually exercise -- the rate-limit middleware is tested
    separately in tests/test_rate_limit.py.
    """
    from backend.rate_limit import limiter

    original_enabled = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = original_enabled


def _build_auth_context(*, user_id: str = "user-test", email: str = "u@example.com"):
    auth_session = AuthSession(
        access_token="access",
        refresh_token="refresh",
        user=AuthUser(user_id=user_id, email=email),
    )
    app_user = AppUserRecord(id=user_id, email=email)
    return AuthenticatedContext(
        auth_service=None,  # type: ignore[arg-type] - unused
        auth_session=auth_session,
        app_user=app_user,
        daily_quota=None,
    )


@pytest.fixture
def stub_job_search(monkeypatch):
    """Replace the JobSearchService dependency with a stub so the
    quota test never depends on the cached_jobs Supabase table."""
    from src.schemas import JobSearchResult

    class _StubService:
        def search_cached(self, query):
            return JobSearchResult(
                query=query,
                results=[],
                total_results=0,
                source_status={"cache": "ok", "backend": "ready"},
            )

        def search(self, query):
            return self.search_cached(query)

        def resolve_url(self, url):
            from src.schemas import JobResolutionResult

            return JobResolutionResult(source="unknown", status="unsupported", error_message="")

    # FastAPI Depends-based stubs go through dependency_overrides.
    from backend.services.job_search_service import get_job_search_service

    app.dependency_overrides[get_job_search_service] = lambda: _StubService()
    yield
    app.dependency_overrides.pop(get_job_search_service, None)


# ─── job_searches enforcement ───────────────────────────────────────────


def test_51st_job_search_on_free_returns_429(stub_job_search, monkeypatch):
    """Free's job_searches cap is 50. The 51st search via HTTP returns
    a 429 with the canonical payload."""
    auth_context = _build_auth_context(user_id="user-free-search-1")
    monkeypatch.setattr(
        jobs_router,
        "resolve_authenticated_context",
        lambda **_kwargs: auth_context,
    )

    headers = {
        "X-Auth-Access-Token": "access",
        "X-Auth-Refresh-Token": "refresh",
    }
    body = {"query": "ml engineer", "location": "", "page_size": 20}
    for _ in range(TIER_CAPS["free"]["job_searches"]):
        response = client.post("/api/jobs/search", json=body, headers=headers)
        assert response.status_code == 200, response.text

    response = client.post("/api/jobs/search", json=body, headers=headers)
    assert response.status_code == 429
    payload = response.json()
    assert payload["code"] == "tier_limit_exceeded"
    assert payload["counter"] == "job_searches"
    assert payload["cap"] == TIER_CAPS["free"]["job_searches"] == 50
    assert payload["current"] == 50
    assert payload["tier"] == "free"


def test_pro_job_search_unlimited(stub_job_search, monkeypatch):
    """Pro's job_searches is UNLIMITED. The gate short-circuits and the
    user can fire many more than Free's 50 cap without ever hitting a
    429. We verify by running 60 searches at the route-handler level
    and asserting every one returns 200."""
    monkeypatch.setattr(jobs_router, "resolve_user_tier", lambda _u: "pro")
    auth_context = _build_auth_context(user_id="user-pro-search-1")
    monkeypatch.setattr(
        jobs_router,
        "resolve_authenticated_context",
        lambda **_kwargs: auth_context,
    )

    headers = {
        "X-Auth-Access-Token": "access",
        "X-Auth-Refresh-Token": "refresh",
    }
    body = {"query": "ml engineer", "location": "", "page_size": 20}
    for _ in range(60):  # well above Free's 50 cap
        response = client.post("/api/jobs/search", json=body, headers=headers)
        assert response.status_code == 200, response.text


def test_business_job_search_unlimited(stub_job_search, monkeypatch):
    """Business mirrors Pro for job_searches -- UNLIMITED."""
    monkeypatch.setattr(jobs_router, "resolve_user_tier", lambda _u: "business")
    auth_context = _build_auth_context(user_id="user-biz-search-1")
    monkeypatch.setattr(
        jobs_router,
        "resolve_authenticated_context",
        lambda **_kwargs: auth_context,
    )

    headers = {
        "X-Auth-Access-Token": "access",
        "X-Auth-Refresh-Token": "refresh",
    }
    body = {"query": "data lead", "location": "", "page_size": 20}
    for _ in range(60):
        response = client.post("/api/jobs/search", json=body, headers=headers)
        assert response.status_code == 200


def test_anonymous_job_search_skips_gate(stub_job_search):
    """No auth headers -> no user_id -> gate skipped. Anonymous
    callers are still rate-limited by slowapi but not metered
    against the per-tier monthly cap."""
    body = {"query": "ml engineer", "location": "", "page_size": 20}
    # Anonymous + many calls in a row works as long as the slowapi
    # rate limit isn't tripped. We only need to confirm the FIRST
    # anonymous call lands -- the gate must be a no-op here.
    response = client.post("/api/jobs/search", json=body)
    assert response.status_code == 200


# ─── saved_jobs enforcement ─────────────────────────────────────────────


class _FakeSavedJobsStore:
    """In-memory stand-in for SavedJobsStore. Records the list of
    saved (user_id, job_id) pairs so the gate's row-count read sees
    a realistic count.
    """

    def __init__(self):
        # (user_id, job_id) -> record dict
        self._rows: dict[tuple[str, str], dict] = {}

    def is_configured(self) -> bool:
        return True

    def list_jobs(self, _access_token, _refresh_token, user_id, limit: int = 20):
        rows = [record for (uid, _jid), record in self._rows.items() if uid == user_id]
        # Sort newest-first to match the production order_by saved_at desc.
        rows.sort(key=lambda r: r.get("saved_at", ""), reverse=True)
        from src.schemas import SavedJobRecord

        return [SavedJobRecord(**row) for row in rows[:limit]]

    def save_job(self, _access_token, _refresh_token, payload):
        key = (str(payload["user_id"]), str(payload["job_id"]))
        from datetime import datetime, timezone

        timestamp = datetime.now(timezone.utc).isoformat()
        record = {
            "user_id": key[0],
            "job_id": key[1],
            "source": str(payload.get("source", "") or ""),
            "title": str(payload.get("title", "") or ""),
            "company": str(payload.get("company", "") or ""),
            "location": str(payload.get("location", "") or ""),
            "employment_type": str(payload.get("employment_type", "") or ""),
            "url": str(payload.get("url", "") or ""),
            "summary": str(payload.get("summary", "") or ""),
            "description_text": str(payload.get("description_text", "") or ""),
            "posted_at": str(payload.get("posted_at", "") or ""),
            "scraped_at": str(payload.get("scraped_at", "") or ""),
            "metadata": payload.get("metadata") or {},
            "saved_at": str(payload.get("saved_at") or timestamp),
            "updated_at": str(payload.get("updated_at") or timestamp),
        }
        self._rows[key] = record
        from src.schemas import SavedJobRecord

        return SavedJobRecord(**record)

    def delete_job(self, _access_token, _refresh_token, user_id, job_id):
        self._rows.pop((str(user_id), str(job_id)), None)


def _save_saved_job(*, auth_context, store, job_id: str):
    """Drive saved_jobs_service.save_saved_job with the supplied stubs."""

    def _resolver(*, access_token=None, refresh_token=None):
        return auth_context

    with patch.object(saved_jobs_service, "resolve_authenticated_context", _resolver):
        with patch.object(
            saved_jobs_service,
            "SavedJobsStore",
            lambda _auth_service=None: store,
        ):
            return saved_jobs_service.save_saved_job(
                access_token="access",
                refresh_token="refresh",
                job_posting={
                    "id": job_id,
                    "title": "Test Role",
                    "source": "test",
                },
            )


def test_6th_saved_job_on_free_returns_429():
    """Free's saved_jobs cap is 5. Five distinct saves succeed; the
    6th rejects with cap=5 and current=5."""
    auth_context = _build_auth_context(user_id="user-free-saved-1")
    store = _FakeSavedJobsStore()

    for index in range(TIER_CAPS["free"]["saved_jobs"]):
        result = _save_saved_job(
            auth_context=auth_context,
            store=store,
            job_id=f"job-{index}",
        )
        assert result["status"] == "saved"

    with pytest.raises(QuotaExceededError) as exc_info:
        _save_saved_job(
            auth_context=auth_context,
            store=store,
            job_id="job-6",
        )
    err = exc_info.value
    assert err.counter == "saved_jobs"
    assert err.cap == TIER_CAPS["free"]["saved_jobs"] == 5
    assert err.current == 5
    assert err.tier == "free"


def test_1001st_saved_job_on_pro_returns_429(monkeypatch):
    """Pro's saved_jobs cap is 1000. Verify the gate rejects at 1001.
    We pre-seed 1000 distinct rows into the stub store so the test
    runs in milliseconds.
    """
    monkeypatch.setattr(saved_jobs_service, "resolve_user_tier", lambda _u: "pro")
    auth_context = _build_auth_context(user_id="user-pro-saved-1")

    store = _FakeSavedJobsStore()
    # Pre-seed cap rows directly so the test doesn't hammer save_job
    # 1000 times.
    from datetime import datetime, timezone

    timestamp = datetime.now(timezone.utc).isoformat()
    for index in range(TIER_CAPS["pro"]["saved_jobs"]):
        store._rows[("user-pro-saved-1", f"job-{index}")] = {
            "user_id": "user-pro-saved-1",
            "job_id": f"job-{index}",
            "source": "test",
            "title": "T",
            "company": "C",
            "location": "L",
            "employment_type": "",
            "url": "",
            "summary": "",
            "description_text": "",
            "posted_at": "",
            "scraped_at": "",
            "metadata": {},
            "saved_at": timestamp,
            "updated_at": timestamp,
        }

    with pytest.raises(QuotaExceededError) as exc_info:
        _save_saved_job(
            auth_context=auth_context,
            store=store,
            job_id="job-new",
        )
    err = exc_info.value
    assert err.counter == "saved_jobs"
    assert err.cap == TIER_CAPS["pro"]["saved_jobs"] == 1000
    assert err.tier == "pro"


def test_business_saved_jobs_unlimited(monkeypatch):
    """Business's saved_jobs cap is UNLIMITED. The gate is skipped --
    even a user with a huge existing-row count can keep saving.
    """
    monkeypatch.setattr(saved_jobs_service, "resolve_user_tier", lambda _u: "business")
    auth_context = _build_auth_context(user_id="user-biz-saved-1")
    store = _FakeSavedJobsStore()

    # Save more than Pro's cap to prove the gate didn't fire.
    for index in range(1100):
        result = _save_saved_job(
            auth_context=auth_context,
            store=store,
            job_id=f"job-{index}",
        )
        assert result["status"] == "saved"


def test_saved_job_re_save_at_cap_allowed():
    """Re-saving the SAME job at the cap is allowed -- the store's
    upsert is an UPDATE, not a new row. Without this carve-out a Free
    user at 5 saved jobs could never edit one of them.
    """
    auth_context = _build_auth_context(user_id="user-free-saved-resave-1")
    store = _FakeSavedJobsStore()
    cap = TIER_CAPS["free"]["saved_jobs"]
    for index in range(cap):
        _save_saved_job(
            auth_context=auth_context,
            store=store,
            job_id=f"job-{index}",
        )
    # Re-saving job-0 (already saved) must still succeed.
    result = _save_saved_job(
        auth_context=auth_context,
        store=store,
        job_id="job-0",
    )
    assert result["status"] == "saved"


def test_saved_job_delete_then_save_works():
    """Deleting a saved job frees a slot so the user can save another
    distinct job after hitting the cap.
    """
    auth_context = _build_auth_context(user_id="user-free-saved-delete-1")
    store = _FakeSavedJobsStore()
    cap = TIER_CAPS["free"]["saved_jobs"]
    for index in range(cap):
        _save_saved_job(
            auth_context=auth_context,
            store=store,
            job_id=f"job-{index}",
        )
    # 6th distinct save: rejected.
    with pytest.raises(QuotaExceededError):
        _save_saved_job(
            auth_context=auth_context,
            store=store,
            job_id="job-new",
        )
    # Delete one, then the next net-new save should succeed.
    store.delete_job("access", "refresh", "user-free-saved-delete-1", "job-0")
    result = _save_saved_job(
        auth_context=auth_context,
        store=store,
        job_id="job-new",
    )
    assert result["status"] == "saved"


# ─── saved_workspaces enforcement ───────────────────────────────────────


class _FakeSavedWorkspaceStore:
    """In-memory stand-in for SavedWorkspaceStore. Models the multi-row
    schema the gate is written against: a list of records keyed by
    user_id + slot id so we can simulate "user already has 1 workspace
    saved, try to save another."

    For tests that want the single-row production schema, just save
    once. For tests that want the future multi-row schema, set
    ``self._rows[user_id]`` directly.
    """

    def __init__(self):
        # user_id -> count of saved workspaces (production schema: 0 or 1)
        self._counts: dict[str, int] = {}

    def is_configured(self) -> bool:
        return True

    def load_workspace(self, _access_token, _refresh_token, user_id, _now=None):
        from src.schemas import SavedWorkspaceRecord

        count = self._counts.get(user_id, 0)
        if count == 0:
            return None, "missing"
        record = SavedWorkspaceRecord(
            user_id=user_id,
            job_title="Stub",
            workflow_signature="sig",
            workflow_snapshot_json="{}",
            cover_letter_payload_json="{}",
            tailored_resume_payload_json="{}",
            expires_at="2099-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
        )
        return record, "available"

    def save_workspace(self, _access_token, _refresh_token, payload):
        user_id = str(payload["user_id"])
        # Production semantic: upsert on user_id, so the count is
        # capped at 1.
        self._counts[user_id] = max(self._counts.get(user_id, 0), 1)
        from src.schemas import SavedWorkspaceRecord

        return SavedWorkspaceRecord(
            user_id=user_id,
            job_title=str(payload.get("job_title", "") or ""),
            workflow_signature=str(payload.get("workflow_signature", "") or ""),
            workflow_snapshot_json="{}",
            cover_letter_payload_json="{}",
            tailored_resume_payload_json="{}",
            expires_at="2099-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
        )

    def delete_workspace(self, _access_token, _refresh_token, user_id):
        self._counts.pop(user_id, None)


def _save_workspace_snapshot(*, auth_context, store):
    """Drive save_workspace_snapshot with stubbed dependencies."""
    snapshot = {
        "candidate_profile": {},
        "job_description": {"title": "Test"},
        "fit_analysis": {},
        "tailored_draft": {},
        "artifacts": {
            "tailored_resume": {},
            "cover_letter": {},
        },
    }

    def _resolver(*, access_token=None, refresh_token=None):
        return auth_context

    with patch.object(workspace_persistence_service, "resolve_authenticated_context", _resolver):
        with patch.object(
            workspace_persistence_service,
            "SavedWorkspaceStore",
            lambda _auth_service=None: store,
        ):
            return workspace_persistence_service.save_workspace_snapshot(
                access_token="access",
                refresh_token="refresh",
                workspace_snapshot=snapshot,
            )


def test_free_re_save_upserts_existing_workspace():
    """Free's saved_workspaces cap is 1, but re-saving an existing
    workspace is an UPDATE to the same slot rather than a new slot —
    so the gate must NOT 429. This is what the frontend autosave
    relies on: every snapshot refresh after the first save calls
    /workspace/save without pre-delete; blocking those would break
    the autosave UX for every Free user past their first save.

    The cap (1) governs the maximum number of *distinct slots* a Free
    user can occupy, not the number of write operations against their
    existing slot. Today's one-row-per-user schema can't actually
    produce a >1 distinct-slot state for a single user, so the
    "(cap+1)-th distinct save" assertion lands with the multi-row
    schema migration (see test_distinct_2nd_workspace_blocks_when_multi_slot_lands).

    Regression for Codex P1 flagged on PR #2 (May 2026).
    """
    auth_context = _build_auth_context(user_id="user-free-workspace-1")
    store = _FakeSavedWorkspaceStore()

    # First save: 0 existing -> allowed.
    first = _save_workspace_snapshot(auth_context=auth_context, store=store)
    assert first["status"] == "saved"

    # Second save: same user_id, store upserts -> still an update to
    # the user's existing slot, NOT a new slot. Must succeed.
    second = _save_workspace_snapshot(auth_context=auth_context, store=store)
    assert second["status"] == "saved"


def test_pro_saved_workspace_with_existing_row_is_allowed(monkeypatch):
    """Pro's saved_workspaces cap is 5, but the current store upserts
    on user_id (one row per user). Until the schema migrates to
    multi-row saved workspaces, Pro / Business users can only ever
    have 1 row, so the gate's row-count check (0 or 1) is always
    below the Pro cap. Verify that a re-save on Pro doesn't 429 --
    the gate must NOT promote the single-row schema's overwrite into
    a rejection just because we have a tier slot to check.

    The full "6th distinct save on Pro -> 429" test will land
    alongside the multi-row schema migration in a follow-up PR;
    today the production code path can't reach that state.
    """
    monkeypatch.setattr(workspace_persistence_service, "resolve_user_tier", lambda _u: "pro")
    auth_context = _build_auth_context(user_id="user-pro-workspace-1")
    store = _FakeSavedWorkspaceStore()

    # First save lands.
    _save_workspace_snapshot(auth_context=auth_context, store=store)
    # Second save: 1 existing row, Pro cap=5 -> 1 < 5 -> allowed.
    result = _save_workspace_snapshot(auth_context=auth_context, store=store)
    assert result["status"] == "saved"


def test_saved_workspace_delete_then_save_works():
    """Deleting the saved workspace and re-saving the next snapshot
    both succeed. With the post-Codex-fix gate, re-saving never
    requires a pre-delete (upserts are always allowed against an
    existing slot), so the explicit DELETE is purely UX-driven --
    e.g. when the user wants to clear their workspace from the
    saved-jobs sidebar. This test pins that DELETE + save round-trips
    cleanly even after the gate is in place.
    """
    auth_context = _build_auth_context(user_id="user-free-workspace-delete-1")
    store = _FakeSavedWorkspaceStore()
    # First save: 0 existing -> allowed.
    first = _save_workspace_snapshot(auth_context=auth_context, store=store)
    assert first["status"] == "saved"
    # Explicit delete (user-driven clean slate).
    store.delete_workspace("access", "refresh", "user-free-workspace-delete-1")
    # Save again from 0 existing -> allowed.
    second = _save_workspace_snapshot(auth_context=auth_context, store=store)
    assert second["status"] == "saved"
