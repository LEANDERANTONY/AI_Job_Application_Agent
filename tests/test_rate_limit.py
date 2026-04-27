"""Tests for the rate limiter.

Strategy
--------
The limit constants (LIMIT_HEAVY/LIMIT_LLM/LIMIT_PARSE) are read at
module-import time, and slowapi's @limiter.limit decorator captures
the budget at decoration time. To exercise a low budget without
firing 60+ real requests, we set RATE_LIMIT_OVERRIDE in the env and
reload the affected modules so the decorators re-bind. Each test
function gets its own freshly-reloaded app via a fixture so the
in-memory limiter state is isolated.
"""
from __future__ import annotations

import base64
import importlib
import json
import os
from typing import Iterable

import pytest
from fastapi.testclient import TestClient


def _reload_app(monkeypatch: pytest.MonkeyPatch, override: str = "2/minute"):
    """Reload backend modules with RATE_LIMIT_OVERRIDE applied.

    Returns a fresh TestClient bound to a freshly-decorated app.
    Reloads in dependency order so the decorators see the new
    LIMIT_* constants.
    """
    monkeypatch.setenv("RATE_LIMIT_OVERRIDE", override)

    import backend.rate_limit
    import backend.routers.workspace
    import backend.routers.jobs
    import backend.app

    # Reload bottom-up so decorators on routes pick up new limits.
    importlib.reload(backend.rate_limit)
    importlib.reload(backend.routers.workspace)
    importlib.reload(backend.routers.jobs)
    importlib.reload(backend.app)

    return TestClient(backend.app.app)


def _make_jwt_with_sub(sub: str) -> str:
    """Build a syntactically valid JWT (signature is junk, sub is real).

    The rate limiter only decodes the payload; it never verifies the
    signature. That's the whole reason we can do this in a unit test.
    """
    header = base64.urlsafe_b64encode(b'{"alg":"HS256","typ":"JWT"}').decode().rstrip("=")
    payload = base64.urlsafe_b64encode(json.dumps({"sub": sub}).encode()).decode().rstrip("=")
    signature = "fake-signature"
    return f"{header}.{payload}.{signature}"


def _encode_text_file_payload(filename: str, text: str):
    return {
        "filename": filename,
        "mime_type": "text/plain",
        "content_base64": base64.b64encode(text.encode("utf-8")).decode("utf-8"),
    }


def _fire_uploads(
    client: TestClient,
    count: int,
    headers: dict | None = None,
    cookies: dict | None = None,
) -> Iterable[int]:
    """Fire `count` resume uploads and yield each status code."""
    request_headers = dict(headers or {})
    if cookies:
        request_headers["Cookie"] = "; ".join(
            f"{key}={value}" for key, value in cookies.items()
        )
    for i in range(count):
        response = client.post(
            "/api/workspace/resume/upload",
            headers=request_headers,
            json=_encode_text_file_payload(f"r{i}.txt", "Leander\nPython"),
        )
        yield response.status_code


# ---------------------------------------------------------------------------
# Test 1: anonymous IP-bucketed limiting
# ---------------------------------------------------------------------------
def test_anonymous_requests_share_an_ip_bucket_and_get_429_after_the_limit(
    monkeypatch: pytest.MonkeyPatch,
):
    """With override=2/minute, the 3rd anonymous upload from the same
    test client (same IP) should return 429."""
    client = _reload_app(monkeypatch, override="2/minute")

    statuses = list(_fire_uploads(client, count=3))

    # First two succeed (200), third is rate-limited (429).
    assert statuses[0] == 200, f"first request should succeed, got {statuses[0]}"
    assert statuses[1] == 200, f"second request should succeed, got {statuses[1]}"
    assert statuses[2] == 429, f"third request should be rate-limited, got {statuses[2]}"


# ---------------------------------------------------------------------------
# Test 2: authenticated requests bucket per user-id, not per IP
# ---------------------------------------------------------------------------
def test_two_authenticated_users_get_independent_buckets(monkeypatch: pytest.MonkeyPatch):
    """Two different JWT subs from the same TestClient (same IP) must
    each get their own bucket. With override=2/minute, user-A and
    user-B can each succeed twice independently."""
    client = _reload_app(monkeypatch, override="2/minute")

    headers_a = {"X-Auth-Access-Token": _make_jwt_with_sub("user-aaa")}
    headers_b = {"X-Auth-Access-Token": _make_jwt_with_sub("user-bbb")}

    # User A consumes their bucket.
    statuses_a = list(_fire_uploads(client, count=2, headers=headers_a))
    assert statuses_a == [200, 200], statuses_a

    # User B should still have a fresh bucket.
    statuses_b = list(_fire_uploads(client, count=2, headers=headers_b))
    assert statuses_b == [200, 200], statuses_b

    # Now both are full -> next call from each is 429.
    next_a = list(_fire_uploads(client, count=1, headers=headers_a))
    next_b = list(_fire_uploads(client, count=1, headers=headers_b))
    assert next_a == [429], next_a
    assert next_b == [429], next_b


def test_authenticated_cookie_uses_user_bucket(monkeypatch: pytest.MonkeyPatch):
    """Cookie-authenticated requests should use the same per-user
    bucket behavior as the legacy auth header fallback."""
    client = _reload_app(monkeypatch, override="2/minute")

    cookies_a = {"ja_access_token": _make_jwt_with_sub("cookie-user-aaa")}
    cookies_b = {"ja_access_token": _make_jwt_with_sub("cookie-user-bbb")}

    assert list(_fire_uploads(client, count=2, cookies=cookies_a)) == [200, 200]
    assert list(_fire_uploads(client, count=2, cookies=cookies_b)) == [200, 200]
    assert list(_fire_uploads(client, count=1, cookies=cookies_a)) == [429]


# ---------------------------------------------------------------------------
# Test 3: anonymous and authenticated buckets are namespaced separately
# ---------------------------------------------------------------------------
def test_anonymous_bucket_does_not_share_with_authenticated_bucket(
    monkeypatch: pytest.MonkeyPatch,
):
    """An anonymous client filling its IP bucket must not affect a
    signed-in user's bucket on the same machine."""
    client = _reload_app(monkeypatch, override="2/minute")

    # Burn through anonymous bucket.
    anon_statuses = list(_fire_uploads(client, count=3))
    assert anon_statuses == [200, 200, 429], anon_statuses

    # Authenticated user from same IP should still succeed.
    headers = {"X-Auth-Access-Token": _make_jwt_with_sub("user-fresh")}
    auth_statuses = list(_fire_uploads(client, count=2, headers=headers))
    assert auth_statuses == [200, 200], auth_statuses


# ---------------------------------------------------------------------------
# Test 4: GET /analyze-jobs/{job_id} polling endpoint is NOT rate-limited
# ---------------------------------------------------------------------------
def test_analyze_jobs_polling_endpoint_is_not_rate_limited(
    monkeypatch: pytest.MonkeyPatch,
):
    """The frontend polls this on a timer; rate-limiting it would
    break in-progress workflow tracking. With override=2/minute (the
    same low limit applied to other tiers), 5 polls in a row should
    all succeed (returning 404 because the job-id doesn't exist, but
    never 429)."""
    client = _reload_app(monkeypatch, override="2/minute")

    statuses = []
    for _ in range(5):
        response = client.get("/api/workspace/analyze-jobs/nonexistent-job-id")
        statuses.append(response.status_code)

    assert all(s == 404 for s in statuses), (
        f"polling endpoint should never be rate-limited, got statuses: {statuses}"
    )


# ---------------------------------------------------------------------------
# Test 5: 429 response shape matches the rest of the API
# ---------------------------------------------------------------------------
def test_429_response_has_clean_json_body_and_retry_after_header(
    monkeypatch: pytest.MonkeyPatch,
):
    client = _reload_app(monkeypatch, override="1/minute")

    # First call succeeds, second is over the limit.
    first = client.post(
        "/api/workspace/resume/upload",
        json=_encode_text_file_payload("r.txt", "Leander\nPython"),
    )
    assert first.status_code == 200

    second = client.post(
        "/api/workspace/resume/upload",
        json=_encode_text_file_payload("r.txt", "Leander\nPython"),
    )
    assert second.status_code == 429
    body = second.json()
    assert "detail" in body
    assert "Too many requests" in body["detail"]
    # Retry-After header (set by our handler).
    assert second.headers.get("Retry-After") == "60"


# ---------------------------------------------------------------------------
# Test 6: read-only endpoints stay unlimited (sanity check)
# ---------------------------------------------------------------------------
def test_health_endpoint_is_never_rate_limited(monkeypatch: pytest.MonkeyPatch):
    client = _reload_app(monkeypatch, override="1/minute")

    statuses = [client.get("/api/health").status_code for _ in range(5)]
    assert all(s == 200 for s in statuses), statuses


# ---------------------------------------------------------------------------
# Final: restore the production app so other tests in the same session
# don't run against a 1-call/minute override.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True, scope="module")
def _restore_app_after_module():
    """After this module runs, reload the app one more time WITHOUT
    the override so any later tests in the same pytest session see
    production limits."""
    yield
    os.environ.pop("RATE_LIMIT_OVERRIDE", None)
    import backend.rate_limit
    import backend.routers.workspace
    import backend.routers.jobs
    import backend.app

    importlib.reload(backend.rate_limit)
    importlib.reload(backend.routers.workspace)
    importlib.reload(backend.routers.jobs)
    importlib.reload(backend.app)
