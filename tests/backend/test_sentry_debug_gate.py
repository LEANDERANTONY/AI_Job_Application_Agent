"""L1 — /health/sentry-debug must not be an open, unauthenticated 500 button.

The route deliberately raises so a deploy can verify Sentry catches unhandled
exceptions end-to-end — but it had no auth, so anyone could curl it to mint
500s / Sentry noise on demand. It's now gated behind the admin bearer secret
(``_verify_refresh_secret``): a blocked call returns 401/503 *before* the body
runs (FastAPI handles the HTTPException cleanly, so no Sentry event), while an
authorized caller still hits the intentional crash.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app import app
from backend.routers import jobs as jobs_router

client = TestClient(app, raise_server_exceptions=False)

URL = "/health/sentry-debug"


def test_anonymous_call_is_blocked_not_500(monkeypatch):
    monkeypatch.setattr(jobs_router, "REFRESH_CACHE_SECRET", "smoke-secret")
    response = client.get(URL)
    # 401, NOT the 500 the unauthenticated crash used to produce.
    assert response.status_code == 401


def test_wrong_token_is_401(monkeypatch):
    monkeypatch.setattr(jobs_router, "REFRESH_CACHE_SECRET", "smoke-secret")
    response = client.get(URL, headers={"Authorization": "Bearer nope"})
    assert response.status_code == 401


def test_unconfigured_secret_fails_closed_503(monkeypatch):
    monkeypatch.setattr(jobs_router, "REFRESH_CACHE_SECRET", "")
    response = client.get(URL)
    assert response.status_code == 503


def test_valid_token_reaches_the_intentional_crash(monkeypatch):
    monkeypatch.setattr(jobs_router, "REFRESH_CACHE_SECRET", "smoke-secret")
    response = client.get(URL, headers={"Authorization": "Bearer smoke-secret"})
    # The route's whole purpose: an authorized caller still triggers the
    # unhandled ZeroDivisionError (a 500) that Sentry is meant to catch.
    assert response.status_code == 500
