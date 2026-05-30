"""Object-level authorization for the analysis-job routes (SECURITY-1).

    GET  /api/workspace/analyze-jobs/{job_id}
    POST /api/workspace/analyze-jobs/{job_id}/cancel

The ``job_id`` is a uuid4 carried in the URL — it leaks via reverse-proxy
access logs, the ``Referer`` header, browser history, and Sentry/PostHog
breadcrumbs, so it is NOT an authorization token. Before the fix both
routes were unauthenticated and looked the job up by id alone, letting
any caller read a stranger's tailored résumé + cover letter or cancel
their in-flight run (an unauthenticated BOLA).

These tests pin the fix end-to-end against the REAL routes and the REAL
in-memory job registry:
  * signed-out  -> 401 (login required)
  * owner       -> 200 / cancel succeeds
  * non-owner   -> 404, indistinguishable from an unknown id (existence
    is never confirmed) and the owner's run is never flagged
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.services import workspace_run_jobs as wrj
from backend.services.workspace_run_jobs import WorkspaceRunJob


client = TestClient(app)

OWNER_TOKENS = {
    "X-Auth-Access-Token": "owner-access",
    "X-Auth-Refresh-Token": "owner-refresh",
}
ATTACKER_TOKENS = {
    "X-Auth-Access-Token": "attacker-access",
    "X-Auth-Refresh-Token": "attacker-refresh",
}


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Give each test a clean process-global ``_JOBS`` and restore it
    afterward so this module never leaks job state into the rest of the
    suite (mirrors tests/test_workspace_run_jobs_cancel.py)."""
    with wrj._LOCK:
        saved = dict(wrj._JOBS)
        wrj._JOBS.clear()
    try:
        yield
    finally:
        with wrj._LOCK:
            wrj._JOBS.clear()
            wrj._JOBS.update(saved)


@pytest.fixture
def _identity_by_token(monkeypatch):
    """Resolve the caller's user_id from the access token so a test can
    act as the owner or as a different signed-in user. Matches the real
    ``resolve_authenticated_context`` contract (keyword-only tokens; an
    unknown/expired token resolves to no identity, which the route turns
    into a 401)."""

    def _resolve(*, access_token, refresh_token):
        mapping = {"owner-access": "owner-1", "attacker-access": "attacker-2"}
        user_id = mapping.get(access_token)
        if user_id is None:
            return None
        return SimpleNamespace(app_user=SimpleNamespace(id=user_id))

    monkeypatch.setattr(
        "backend.routers.workspace.resolve_authenticated_context", _resolve
    )


def _put_job(job_id: str, owner_user_id: str, status: str = "completed") -> None:
    with wrj._LOCK:
        wrj._JOBS[job_id] = WorkspaceRunJob(
            job_id=job_id,
            status=status,
            owner_user_id=owner_user_id,
            # The PII-dense payload the BOLA leaked — assert it never
            # appears in a non-owner response body.
            result={"artifacts": {"tailored_resume": {"markdown": "SECRET-RESUME"}}},
        )


def test_status_route_requires_login():
    _put_job("job-1", owner_user_id="owner-1")
    response = client.get("/api/workspace/analyze-jobs/job-1")
    assert response.status_code == 401


def test_cancel_route_requires_login():
    _put_job("job-1", owner_user_id="owner-1", status="running")
    response = client.post("/api/workspace/analyze-jobs/job-1/cancel")
    assert response.status_code == 401


def test_status_route_returns_job_to_owner(_identity_by_token):
    _put_job("job-1", owner_user_id="owner-1")
    response = client.get("/api/workspace/analyze-jobs/job-1", headers=OWNER_TOKENS)
    assert response.status_code == 200
    body = response.json()
    assert body["job_id"] == "job-1"
    assert body["status"] == "completed"


def test_status_route_hides_job_from_non_owner(_identity_by_token):
    _put_job("job-1", owner_user_id="owner-1")
    response = client.get("/api/workspace/analyze-jobs/job-1", headers=ATTACKER_TOKENS)
    # Same actionable 404 a missing id returns — never confirm the job
    # exists, never leak the owner's tailored résumé.
    assert response.status_code == 404
    assert "SECRET-RESUME" not in response.text


def test_cancel_route_blocks_non_owner(_identity_by_token):
    _put_job("job-1", owner_user_id="owner-1", status="running")
    response = client.post(
        "/api/workspace/analyze-jobs/job-1/cancel", headers=ATTACKER_TOKENS
    )
    assert response.status_code == 404
    # The owner's in-flight run was NOT flagged for cancellation.
    with wrj._LOCK:
        assert wrj._JOBS["job-1"].cancel_requested is False


def test_cancel_route_allows_owner(_identity_by_token):
    _put_job("job-1", owner_user_id="owner-1", status="running")
    response = client.post(
        "/api/workspace/analyze-jobs/job-1/cancel", headers=OWNER_TOKENS
    )
    assert response.status_code == 200
    with wrj._LOCK:
        assert wrj._JOBS["job-1"].cancel_requested is True
