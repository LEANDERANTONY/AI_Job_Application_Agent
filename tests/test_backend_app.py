from fastapi.testclient import TestClient

from backend.app import app
from backend.routers.jobs import get_job_search_service


client = TestClient(app)


def test_backend_root_endpoint_reports_frontend_and_health_urls():
    response = client.get("/")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["frontend_url"]
    assert payload["health_url"] == "/api/health"


def test_backend_health_endpoint_reports_service_status():
    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "Backend" in payload["service"]
    assert "providers" in payload
    assert "greenhouse" in payload["providers"]
    assert "lever" in payload["providers"]


def test_job_search_endpoint_returns_placeholder_backend_response():
    class FakeService:
        def search(self, query):
            from src.schemas import JobPosting, JobSearchResult

            return JobSearchResult(
                query=query,
                results=[
                    JobPosting(
                        id="demo:1",
                        source="demo",
                        title="Machine Learning Engineer",
                        company="Demo Company",
                        location="Bengaluru",
                    )
                ],
                total_results=1,
                source_status={"backend": "ready", "demo": "ok"},
            )

    app.dependency_overrides[get_job_search_service] = lambda: FakeService()
    try:
        response = client.post(
            "/api/jobs/search",
            json={
                "query": "machine learning engineer",
                "location": "Bengaluru",
                "remote_only": True,
                "page_size": 10,
            },
        )
    finally:
        app.dependency_overrides.pop(get_job_search_service, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"]["query"] == "machine learning engineer"
    assert payload["query"]["location"] == "Bengaluru"
    assert payload["query"]["remote_only"] is True
    assert payload["source_status"]["backend"] == "ready"
    assert payload["source_status"]["demo"] == "ok"
    assert payload["total_results"] >= 0


def test_job_search_endpoint_rejects_blank_query():
    response = client.post(
        "/api/jobs/search",
        json={
            "query": "   ",
            "location": "Bengaluru",
        },
    )

    assert response.status_code == 422


def test_job_search_endpoint_rejects_invalid_page_size():
    response = client.post(
        "/api/jobs/search",
        json={
            "query": "data scientist",
            "page_size": 99,
        },
    )

    assert response.status_code == 422


def test_job_resolve_endpoint_rejects_blank_url():
    response = client.post(
        "/api/jobs/resolve",
        json={"url": "   "},
    )

    assert response.status_code == 422


def test_admin_refresh_cache_rejects_missing_bearer(monkeypatch):
    """Without a bearer token in Authorization, the admin refresh
    endpoint returns 401. Proves the gate works before any worker
    code runs."""
    monkeypatch.setattr(
        "backend.routers.jobs.REFRESH_CACHE_SECRET", "test-secret"
    )
    response = client.post("/api/admin/refresh-cache")
    assert response.status_code == 401


def test_admin_refresh_cache_rejects_wrong_bearer(monkeypatch):
    """Wrong bearer token → 401. Constant-time compare ensures
    we don't leak the secret via timing."""
    monkeypatch.setattr(
        "backend.routers.jobs.REFRESH_CACHE_SECRET", "test-secret"
    )
    response = client.post(
        "/api/admin/refresh-cache",
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert response.status_code == 401


def test_admin_refresh_cache_returns_503_when_secret_unconfigured(monkeypatch):
    """Server with no REFRESH_CACHE_SECRET fails closed (503) instead
    of accepting any request. Defends the deploy-default state."""
    monkeypatch.setattr("backend.routers.jobs.REFRESH_CACHE_SECRET", "")
    response = client.post(
        "/api/admin/refresh-cache",
        headers={"Authorization": "Bearer anything"},
    )
    assert response.status_code == 503


def test_admin_refresh_cache_accepts_correct_bearer_then_runs_worker(monkeypatch):
    """Right secret + worker stub → endpoint returns the worker's
    report. Pins that the auth → worker handoff actually works."""
    monkeypatch.setattr(
        "backend.routers.jobs.REFRESH_CACHE_SECRET", "test-secret"
    )

    def _fake_refresh():
        return {
            "started_at": "2026-05-07T18:00:00Z",
            "finished_at": "2026-05-07T18:00:05Z",
            "duration_seconds": 5.0,
            "providers": {"greenhouse": {"status": "ok"}},
            "total_active_after": 42,
        }

    monkeypatch.setattr(
        "backend.routers.jobs.refresh_cached_jobs", _fake_refresh
    )

    response = client.post(
        "/api/admin/refresh-cache",
        headers={"Authorization": "Bearer test-secret"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["total_active_after"] == 42
    assert payload["providers"]["greenhouse"]["status"] == "ok"
