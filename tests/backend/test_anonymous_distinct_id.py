"""M21 — anonymous backend events keep their own PostHog distinct id.

Before this fix every unauthenticated caller emitted ``distinct_id=""`` →
the constant ``"anonymous"``, so all anonymous visitors collapsed onto one
PostHog person — matching neither the browser's random id nor the later
Supabase id, leaving anonymous→signup conversion (the headline launch metric)
uncomputable.

The fix: the browser sends its ``posthog.get_distinct_id()`` in the
``X-PostHog-Distinct-Id`` header; the backend prefers the authenticated
Supabase id, then that header, then ``"anonymous"`` only as a last resort. On
login the client calls ``posthog.identify(userId)``, which aliases the
anonymous id to the Supabase id — so the whole path stitches into one person.

These tests pin both the resolver precedence and the end-to-end header flow
through the ``job_searched`` funnel-top event.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.observability import (
    POSTHOG_DISTINCT_ID_HEADER,
    resolve_distinct_id,
)
from backend.routers import jobs as jobs_router
from backend.services.job_search_service import get_job_search_service

client = TestClient(app, raise_server_exceptions=False)


# ─── resolve_distinct_id precedence ─────────────────────────────────────────


def test_authenticated_user_id_wins_over_browser_id():
    # A signed-in caller is always keyed by the Supabase id, never the
    # client-controlled header.
    assert resolve_distinct_id("user-123", "browser-abc") == "user-123"


def test_browser_id_used_when_no_user_id():
    assert resolve_distinct_id("", "browser-abc") == "browser-abc"
    assert resolve_distinct_id(None, "browser-abc") == "browser-abc"


def test_falls_back_to_anonymous_when_neither_present():
    assert resolve_distinct_id("", "") == "anonymous"
    assert resolve_distinct_id(None, None) == "anonymous"


def test_whitespace_only_values_are_treated_as_empty():
    assert resolve_distinct_id("   ", "  browser-abc  ") == "browser-abc"
    assert resolve_distinct_id("   ", "   ") == "anonymous"


def test_browser_id_is_length_clamped():
    huge = "x" * 5000
    resolved = resolve_distinct_id("", huge)
    assert resolved == "x" * 200


# ─── end-to-end header flow through job_searched ─────────────────────────────


@pytest.fixture
def stub_job_search():
    """Stub the JobSearchService so the route never touches Supabase."""
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

    app.dependency_overrides[get_job_search_service] = lambda: _StubService()
    yield
    app.dependency_overrides.pop(get_job_search_service, None)


@pytest.fixture
def capture_distinct_id(monkeypatch):
    """Intercept the route's capture_event and record the distinct id used."""
    captured: dict = {}

    def _fake_capture(distinct_id, event, properties=None):
        captured["distinct_id"] = distinct_id
        captured["event"] = event

    monkeypatch.setattr(jobs_router, "capture_event", _fake_capture)
    return captured


def test_anonymous_search_attributes_to_browser_distinct_id(
    stub_job_search, capture_distinct_id
):
    body = {"query": "ml engineer", "location": "", "page_size": 20}
    response = client.post(
        "/api/jobs/search",
        json=body,
        headers={POSTHOG_DISTINCT_ID_HEADER: "browser-abc-123"},
    )
    assert response.status_code == 200, response.text
    assert capture_distinct_id["event"] == "job_searched"
    # The headline assertion: NOT collapsed onto the shared "anonymous" id.
    assert capture_distinct_id["distinct_id"] == "browser-abc-123"


def test_anonymous_search_without_header_falls_back_to_anonymous(
    stub_job_search, capture_distinct_id
):
    body = {"query": "ml engineer", "location": "", "page_size": 20}
    response = client.post("/api/jobs/search", json=body)
    assert response.status_code == 200, response.text
    assert capture_distinct_id["distinct_id"] == "anonymous"
