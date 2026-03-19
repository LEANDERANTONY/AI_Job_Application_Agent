from fastapi.testclient import TestClient

from backend.app import app


client = TestClient(app)


def test_backend_health_endpoint_reports_service_status():
    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert "Backend" in payload["service"]


def test_job_search_endpoint_returns_placeholder_backend_response():
    response = client.post(
        "/api/jobs/search",
        json={
            "query": "machine learning engineer",
            "location": "Bengaluru",
            "remote_only": True,
            "page_size": 10,
        },
    )

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
