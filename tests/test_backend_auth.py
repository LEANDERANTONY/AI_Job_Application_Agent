from fastapi.testclient import TestClient

from backend.app import app


client = TestClient(app)


def test_auth_google_start_endpoint_returns_redirect_details(monkeypatch):
    monkeypatch.setattr(
        "backend.routers.auth.start_google_sign_in",
        lambda redirect_url: {
            "url": "https://example.com/oauth",
            "auth_flow": "flow-123",
            "redirect_url": redirect_url,
        },
    )

    response = client.post(
        "/api/auth/google/start",
        json={"redirect_url": "https://frontend.example/workspace"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["url"] == "https://example.com/oauth"
    assert payload["auth_flow"] == "flow-123"
    assert payload["redirect_url"] == "https://frontend.example/workspace"


def test_auth_google_exchange_endpoint_returns_scrubbed_session_and_cookies(monkeypatch):
    monkeypatch.setattr(
        "backend.routers.auth.exchange_google_code",
        lambda auth_code, auth_flow, redirect_url: {
            "authenticated": True,
            "session": {
                "access_token": "access-token",
                "refresh_token": "refresh-token",
            },
            "user": {
                "user_id": "user-123",
                "email": "user@example.com",
                "display_name": "Leander Antony",
                "avatar_url": "",
            },
            "app_user": {
                "id": "user-123",
                "email": "user@example.com",
                "display_name": "Leander Antony",
                "avatar_url": "",
                "created_at": "",
                "last_seen_at": "",
                "plan_tier": "free",
                "account_status": "active",
            },
            "daily_quota": None,
            "features": {
                "saved_workspace_enabled": True,
                "saved_jobs_enabled": True,
                "usage_tracking_enabled": True,
                "assisted_workflow_requires_login": True,
            },
        },
    )

    response = client.post(
        "/api/auth/google/exchange",
        json={
            "auth_code": "code-123",
            "auth_flow": "flow-123",
            "redirect_url": "https://frontend.example/workspace",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["authenticated"] is True
    assert payload["session"] == {"authenticated": True}
    assert payload["app_user"]["id"] == "user-123"
    assert response.cookies["ja_access_token"] == "access-token"
    assert response.cookies["ja_refresh_token"] == "refresh-token"
    set_cookie_headers = response.headers.get_list("set-cookie")
    assert any("ja_access_token=access-token" in value for value in set_cookie_headers)
    assert any("HttpOnly" in value for value in set_cookie_headers)


def test_auth_session_restore_endpoint_forwards_header_tokens(monkeypatch):
    captured = {}

    def fake_restore_authenticated_session(*, access_token, refresh_token):
        captured["access_token"] = access_token
        captured["refresh_token"] = refresh_token
        return {
            "authenticated": True,
            "session": {
                "access_token": access_token,
                "refresh_token": refresh_token,
            },
            "user": {
                "user_id": "user-123",
                "email": "user@example.com",
                "display_name": "Leander Antony",
                "avatar_url": "",
            },
            "app_user": {
                "id": "user-123",
                "email": "user@example.com",
                "display_name": "Leander Antony",
                "avatar_url": "",
                "created_at": "",
                "last_seen_at": "",
                "plan_tier": "free",
                "account_status": "active",
            },
            "daily_quota": None,
            "features": {
                "saved_workspace_enabled": True,
                "saved_jobs_enabled": False,
                "usage_tracking_enabled": True,
                "assisted_workflow_requires_login": True,
            },
        }

    monkeypatch.setattr(
        "backend.routers.auth.restore_authenticated_session",
        fake_restore_authenticated_session,
    )

    response = client.post(
        "/api/auth/session/restore",
        headers={
            "X-Auth-Access-Token": "access-token",
            "X-Auth-Refresh-Token": "refresh-token",
        },
    )

    assert response.status_code == 200
    assert captured["access_token"] == "access-token"
    assert captured["refresh_token"] == "refresh-token"


def test_workspace_handoff_start_requires_auth_and_builds_redirect(monkeypatch):
    captured = {}

    def fake_start_workspace_handoff(*, access_token, refresh_token, target_url):
        captured["access_token"] = access_token
        captured["refresh_token"] = refresh_token
        captured["target_url"] = target_url
        return {
            "status": "ready",
            "redirect_url": f"{target_url}?handoff=token-123",
        }

    monkeypatch.setattr(
        "backend.routers.auth.start_workspace_handoff",
        fake_start_workspace_handoff,
    )

    response = client.post(
        "/api/auth/workspace-handoff/start",
        json={"target_url": "https://app.job-application-copilot.xyz"},
        headers={
            "X-Auth-Access-Token": "access-token",
            "X-Auth-Refresh-Token": "refresh-token",
        },
    )

    assert response.status_code == 200
    assert captured["access_token"] == "access-token"
    assert captured["refresh_token"] == "refresh-token"
    assert (
        captured["target_url"] == "https://app.job-application-copilot.xyz"
    )
    assert (
        response.json()["redirect_url"]
        == "https://app.job-application-copilot.xyz?handoff=token-123"
    )


def test_workspace_handoff_exchange_sets_cookies_and_scrubs_tokens(monkeypatch):
    monkeypatch.setattr(
        "backend.routers.auth.exchange_workspace_handoff",
        lambda handoff_token: {
            "authenticated": True,
            "session": {
                "access_token": "access-token",
                "refresh_token": "refresh-token",
            },
            "user": {
                "user_id": "user-123",
                "email": "user@example.com",
                "display_name": "Leander Antony",
                "avatar_url": "",
            },
            "app_user": {
                "id": "user-123",
                "email": "user@example.com",
                "display_name": "Leander Antony",
                "avatar_url": "",
                "created_at": "",
                "last_seen_at": "",
                "plan_tier": "free",
                "account_status": "active",
            },
            "daily_quota": None,
            "features": {
                "saved_workspace_enabled": True,
                "saved_jobs_enabled": True,
                "usage_tracking_enabled": True,
                "assisted_workflow_requires_login": True,
            },
        },
    )

    response = client.post(
        "/api/auth/workspace-handoff/exchange",
        json={"handoff_token": "token-123"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["authenticated"] is True
    assert payload["session"] == {"authenticated": True}
    assert response.cookies["ja_access_token"] == "access-token"
    assert response.cookies["ja_refresh_token"] == "refresh-token"


# ---------------------------------------------------------------------------
# Auth-cookie security attributes (review L8)
#
# The endpoint tests above only assert HttpOnly, so a config/refactor that
# dropped Secure / SameSite (or set samesite='none' without secure — which
# browsers reject) would fail no test. These pin the full security envelope by
# exercising the cookie helper directly with PROD-shaped settings monkeypatched
# in, since the dev defaults leave Secure off.
# ---------------------------------------------------------------------------


def _prod_cookie_settings():
    from types import SimpleNamespace

    return SimpleNamespace(
        auth_cookie_secure=True,
        auth_cookie_samesite="lax",
        auth_cookie_domain="app.example.com",
    )


def _set_cookie_headers(response):
    return [
        value.decode()
        for (key, value) in response.raw_headers
        if key == b"set-cookie"
    ]


def test_set_auth_cookies_carries_secure_samesite_and_scope(monkeypatch):
    from fastapi import Response

    from backend.services import auth_cookies

    monkeypatch.setattr(
        auth_cookies, "get_backend_settings", _prod_cookie_settings
    )
    response = Response()
    auth_cookies.set_auth_cookies(response, "access-token", "refresh-token")

    cookies = _set_cookie_headers(response)
    assert len(cookies) == 2
    for cookie in cookies:
        lowered = cookie.lower()
        assert "httponly" in lowered
        assert "secure" in lowered
        assert "samesite=lax" in lowered
        assert "domain=app.example.com" in lowered
        assert "path=/" in lowered


def test_clear_auth_cookies_matches_path_and_domain(monkeypatch):
    from fastapi import Response

    from backend.services import auth_cookies

    monkeypatch.setattr(
        auth_cookies, "get_backend_settings", _prod_cookie_settings
    )
    response = Response()
    auth_cookies.clear_auth_cookies(response)

    cookies = _set_cookie_headers(response)
    assert len(cookies) == 2
    for cookie in cookies:
        lowered = cookie.lower()
        # Same path/domain the cookie was set with — otherwise the browser
        # keeps the original and the user stays "signed in" indefinitely.
        assert "domain=app.example.com" in lowered
        assert "path=/" in lowered
        # An actual deletion: expired (Max-Age=0 and/or a past Expires).
        assert "max-age=0" in lowered or "expires=" in lowered
