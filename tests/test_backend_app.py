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
    # Ashby was added as a third source-of-record alongside
    # Greenhouse + Lever — covers the modern AI/dev-tools tier
    # (Linear, Cursor, Cohere, Mistral, ...). Health surfaces it
    # so monitoring can spot a misconfigured deploy.
    assert "ashby" in payload["providers"]
    assert "board_count" in payload["providers"]["ashby"]
    # Workday is the fourth source — covers Fortune 500 (NVIDIA,
    # Adobe, Walmart, Citi, Disney, Boeing, ...). Each tenant runs
    # its own Workday host; tokens are tenant:host:site triples.
    assert "workday" in payload["providers"]
    assert "board_count" in payload["providers"]["workday"]


def test_job_search_endpoint_returns_placeholder_backend_response():
    """End-to-end smoke for /jobs/search. Default routing (no live=true)
    goes through search_cached(); the FakeService stubs both methods so
    either dispatch path returns the same result."""
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

        # /jobs/search defaults to the cached path now — stub it too so
        # this test pins the response-shape contract regardless of which
        # branch the route picks.
        def search_cached(self, query):
            return self.search(query)

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


def test_job_search_endpoint_forwards_dropdown_filters_and_sort_to_service():
    """The new UI-driven filters (work_modes, employment_types, sort_by)
    must reach the service as a JobSearchQuery with the right shape.
    Verifies that the JobSearchRequestModel validators normalize input
    (lowercases, strips empties) and to_domain() forwards every field
    so the cache store sees what the user actually selected."""
    captured: list = []

    class FakeService:
        def search_cached(self, query):
            from src.schemas import JobSearchResult
            captured.append(query)
            return JobSearchResult(
                query=query,
                results=[],
                total_results=0,
                source_status={"backend": "ready"},
            )

    app.dependency_overrides[get_job_search_service] = lambda: FakeService()
    try:
        response = client.post(
            "/api/jobs/search",
            json={
                "query": "ml engineer",
                "work_modes": ["Remote", "HYBRID", ""],  # case + empty
                "employment_types": ["INTERNSHIP"],
                "sort_by": "Newest",  # case-insensitive
                "page_size": 20,
            },
        )
    finally:
        app.dependency_overrides.pop(get_job_search_service, None)

    assert response.status_code == 200
    # Service got a JobSearchQuery with the normalized fields.
    assert len(captured) == 1
    query = captured[0]
    assert query.work_modes == ["remote", "hybrid"]
    assert query.employment_types == ["internship"]
    assert query.sort_by == "newest"
    # Response echo includes the normalized query so the FE can re-render
    # the filter chips from server state.
    payload = response.json()
    assert payload["query"]["work_modes"] == ["remote", "hybrid"]
    assert payload["query"]["employment_types"] == ["internship"]
    assert payload["query"]["sort_by"] == "newest"


def test_job_search_endpoint_defaults_dropdown_filters_when_missing():
    """Backwards-compat: an existing client that doesn't send the new
    fields gets the legacy behaviour (empty filter lists, sort='relevance').
    Pins this so we don't accidentally break the FE during a phased
    rollout."""
    captured: list = []

    class FakeService:
        def search_cached(self, query):
            from src.schemas import JobSearchResult
            captured.append(query)
            return JobSearchResult(query=query, source_status={"backend": "ready"})

    app.dependency_overrides[get_job_search_service] = lambda: FakeService()
    try:
        response = client.post(
            "/api/jobs/search",
            json={"query": "anything"},
        )
    finally:
        app.dependency_overrides.pop(get_job_search_service, None)

    assert response.status_code == 200
    query = captured[0]
    assert query.work_modes == []
    assert query.employment_types == []
    assert query.sort_by == "relevance"


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


def test_job_search_endpoint_dispatches_cached_by_default_and_live_on_flag():
    """Pin the routing contract: no query param → search_cached, with
    `?live=true` → search. Ships the new escape-hatch behavior."""
    calls = []

    class FakeService:
        def search(self, query):
            from src.schemas import JobSearchResult
            calls.append("live")
            return JobSearchResult(query=query, source_status={"path": "live"})

        def search_cached(self, query):
            from src.schemas import JobSearchResult
            calls.append("cached")
            return JobSearchResult(query=query, source_status={"path": "cached"})

    app.dependency_overrides[get_job_search_service] = lambda: FakeService()
    try:
        # Default → cached.
        response = client.post(
            "/api/jobs/search",
            json={"query": "anything"},
        )
        assert response.status_code == 200
        assert response.json()["source_status"] == {"path": "cached"}

        # ?live=true → live fan-out.
        response = client.post(
            "/api/jobs/search?live=true",
            json={"query": "anything"},
        )
        assert response.status_code == 200
        assert response.json()["source_status"] == {"path": "live"}
    finally:
        app.dependency_overrides.pop(get_job_search_service, None)

    assert calls == ["cached", "live"]


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
