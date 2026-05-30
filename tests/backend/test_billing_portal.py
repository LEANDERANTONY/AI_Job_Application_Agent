"""Coverage for POST /billing/portal — the "Manage subscription" button (M18).

The webhook half of billing was exhaustively tested; the customer-portal route
(every paying user's path to manage/cancel) had zero tests across its 503 / 401
/ 404 / 502 / 200 branches, plus the untested payload-shape defenses in
_fetch_customer_portal_url. A regression here (wrong status, a crash on the LS
payload shape, a 404<->401 flip) blocks paying users — a billing-trust risk.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend import subscriptions
from backend.app import app
from backend.routers import billing

client = TestClient(app)

PORTAL_URL = "/api/billing/portal"
AUTH_HEADERS = {
    "X-Auth-Access-Token": "a",
    "X-Auth-Refresh-Token": "r",
}


@pytest.fixture
def _signed_in(monkeypatch):
    """Resolve a signed-in context with a user id for the portal route."""
    monkeypatch.setattr(
        billing,
        "resolve_authenticated_context",
        lambda *, access_token, refresh_token: SimpleNamespace(
            app_user=SimpleNamespace(id="user-1"),
        ),
    )


def test_portal_returns_503_when_lemon_squeezy_unconfigured(monkeypatch):
    monkeypatch.setattr(billing, "_ls_api_key", lambda: "")
    response = client.post(PORTAL_URL, headers=AUTH_HEADERS)
    assert response.status_code == 503


def test_portal_returns_401_when_signed_out(monkeypatch):
    monkeypatch.setattr(billing, "_ls_api_key", lambda: "ls_key")
    # No auth headers -> optional tokens resolve to (None, None) -> 401.
    response = client.post(PORTAL_URL)
    assert response.status_code == 401


def test_portal_returns_404_when_no_active_subscription(monkeypatch, _signed_in):
    monkeypatch.setattr(billing, "_ls_api_key", lambda: "ls_key")
    monkeypatch.setattr(subscriptions, "get_active_subscription", lambda _uid: None)
    response = client.post(PORTAL_URL, headers=AUTH_HEADERS)
    assert response.status_code == 404


def test_portal_returns_404_when_subscription_has_no_customer_id(
    monkeypatch, _signed_in
):
    monkeypatch.setattr(billing, "_ls_api_key", lambda: "ls_key")
    monkeypatch.setattr(
        subscriptions,
        "get_active_subscription",
        lambda _uid: SimpleNamespace(processor_customer_id=""),
    )
    response = client.post(PORTAL_URL, headers=AUTH_HEADERS)
    assert response.status_code == 404


def test_portal_returns_502_when_ls_returns_no_url(monkeypatch, _signed_in):
    monkeypatch.setattr(billing, "_ls_api_key", lambda: "ls_key")
    monkeypatch.setattr(
        subscriptions,
        "get_active_subscription",
        lambda _uid: SimpleNamespace(processor_customer_id="cust_1"),
    )
    monkeypatch.setattr(
        billing, "_fetch_customer_portal_url", lambda *, api_key, customer_id: ""
    )
    response = client.post(PORTAL_URL, headers=AUTH_HEADERS)
    assert response.status_code == 502


def test_portal_returns_200_with_url_on_success(monkeypatch, _signed_in):
    monkeypatch.setattr(billing, "_ls_api_key", lambda: "ls_key")
    monkeypatch.setattr(
        subscriptions,
        "get_active_subscription",
        lambda _uid: SimpleNamespace(processor_customer_id="cust_1"),
    )
    monkeypatch.setattr(
        billing,
        "_fetch_customer_portal_url",
        lambda *, api_key, customer_id: "https://billing.example.com/portal",
    )
    response = client.post(PORTAL_URL, headers=AUTH_HEADERS)
    assert response.status_code == 200
    assert response.json()["url"] == "https://billing.example.com/portal"


# --- _fetch_customer_portal_url payload-shape parsing ---------------------


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_fetch_portal_url_extracts_customer_portal(monkeypatch):
    import httpx

    monkeypatch.setattr(
        httpx,
        "get",
        lambda *a, **k: _FakeResponse(
            200, {"data": {"attributes": {"urls": {"customer_portal": "https://p"}}}}
        ),
    )
    assert (
        billing._fetch_customer_portal_url(api_key="k", customer_id="c") == "https://p"
    )


def test_fetch_portal_url_returns_empty_on_non_200(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse(500, {}))
    assert billing._fetch_customer_portal_url(api_key="k", customer_id="c") == ""


def test_fetch_portal_url_returns_empty_on_non_dict_or_missing_urls(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse(200, ["not", "dict"]))
    assert billing._fetch_customer_portal_url(api_key="k", customer_id="c") == ""

    monkeypatch.setattr(
        httpx, "get", lambda *a, **k: _FakeResponse(200, {"data": {"attributes": {}}})
    )
    assert billing._fetch_customer_portal_url(api_key="k", customer_id="c") == ""
