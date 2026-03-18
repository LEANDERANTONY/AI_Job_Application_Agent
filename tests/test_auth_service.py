from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

import src.auth_service as auth_service_module
from src.auth_service import AuthService
from src.errors import AppError


class FakeAuthClient:
    def __init__(self, oauth_response=None, exchange_response=None, set_session_response=None):
        self.oauth_response = oauth_response
        self.exchange_response = exchange_response
        self.set_session_response = set_session_response
        self.set_session_calls = []
        self.sign_out_called = False

    def sign_in_with_oauth(self, payload):
        self.oauth_payload = payload
        return self.oauth_response

    def exchange_code_for_session(self, payload):
        self.exchange_payload = payload
        return self.exchange_response

    def set_session(self, access_token, refresh_token=None):
        self.set_session_calls.append((access_token, refresh_token))
        return self.set_session_response

    def sign_out(self):
        self.sign_out_called = True


class FakeSupabaseClient:
    def __init__(self, auth_client):
        self.auth = auth_client


def test_get_google_sign_in_url_uses_supabase_oauth(monkeypatch):
    auth_client = FakeAuthClient(oauth_response={"url": "https://example.com/oauth"})

    monkeypatch.setattr(
        "src.auth_service.create_client",
        lambda *args, **kwargs: FakeSupabaseClient(auth_client),
    )
    monkeypatch.setattr("src.auth_service.ClientOptions", lambda **kwargs: kwargs)
    monkeypatch.setattr("src.auth_service.get_auth_pkce_code_verifier", lambda: "pkce-verifier")

    service = AuthService(
        supabase_url="https://project.supabase.co",
        supabase_anon_key="anon-key",
        redirect_url="http://localhost:8501",
    )

    sign_in_url = service.get_google_sign_in_url()

    assert sign_in_url == "https://example.com/oauth"
    assert auth_client.oauth_payload["provider"] == "google"
    redirect_to = auth_client.oauth_payload["options"]["redirect_to"]
    parsed_redirect = urlsplit(redirect_to)
    query = parse_qs(parsed_redirect.query)
    assert "auth_flow" in query
    assert parsed_redirect.scheme == "http"
    assert parsed_redirect.netloc == "localhost:8501"


def test_get_google_sign_in_request_builds_cookie_payload(monkeypatch):
    auth_client = FakeAuthClient(oauth_response={"url": "https://example.com/oauth"})

    monkeypatch.setattr(
        "src.auth_service.create_client",
        lambda *args, **kwargs: FakeSupabaseClient(auth_client),
    )
    monkeypatch.setattr("src.auth_service.ClientOptions", lambda **kwargs: kwargs)
    monkeypatch.setattr("src.auth_service.get_auth_pkce_code_verifier", lambda: "pkce-verifier")

    service = AuthService(
        supabase_url="https://project.supabase.co",
        supabase_anon_key="anon-key",
        redirect_url="http://localhost:8501",
    )

    sign_in_request = service.get_google_sign_in_request()
    payload = auth_service_module._deserialize_pkce_cookie_payload(sign_in_request.cookie_value)

    assert sign_in_request.url == "https://example.com/oauth"
    assert sign_in_request.cookie_name == "auth_pkce_flow"
    assert sign_in_request.cookie_max_age_seconds == 600
    assert payload["auth_flow"] == sign_in_request.auth_flow
    assert payload["code_verifier"] == "pkce-verifier"


def test_exchange_code_for_session_builds_authenticated_user(monkeypatch):
    response = SimpleNamespace(
        session=SimpleNamespace(
            access_token="access-token",
            refresh_token="refresh-token",
            user=SimpleNamespace(
                id="user-123",
                email="user@example.com",
                user_metadata={
                    "full_name": "Leander Antony",
                    "avatar_url": "https://example.com/avatar.png",
                },
            ),
        )
    )
    auth_client = FakeAuthClient(exchange_response=response)

    monkeypatch.setattr(
        "src.auth_service.create_client",
        lambda *args, **kwargs: FakeSupabaseClient(auth_client),
    )
    monkeypatch.setattr("src.auth_service.ClientOptions", lambda **kwargs: kwargs)
    monkeypatch.setattr("src.auth_service.set_auth_pkce_code_verifier", lambda value: None)
    monkeypatch.setitem(
        __import__("src.auth_service", fromlist=["_PKCE_CODE_VERIFIER_CACHE"]).__dict__["_PKCE_CODE_VERIFIER_CACHE"],
        "flow-123",
        "pkce-verifier",
    )

    service = AuthService(
        supabase_url="https://project.supabase.co",
        supabase_anon_key="anon-key",
        redirect_url="http://localhost:8501",
    )

    session = service.exchange_code_for_session("auth-code", auth_flow="flow-123")

    assert auth_client.exchange_payload == {
        "auth_code": "auth-code",
        "code_verifier": "pkce-verifier",
        "redirect_to": "http://localhost:8501?auth_flow=flow-123",
    }
    assert session.access_token == "access-token"
    assert session.refresh_token == "refresh-token"
    assert session.user.user_id == "user-123"
    assert session.user.email == "user@example.com"
    assert session.user.display_name == "Leander Antony"
    assert session.user.avatar_url == "https://example.com/avatar.png"


def test_exchange_code_for_session_uses_cookie_payload_when_session_state_is_missing(monkeypatch):
    response = SimpleNamespace(
        session=SimpleNamespace(
            access_token="access-token",
            refresh_token="refresh-token",
            user=SimpleNamespace(
                id="user-123",
                email="user@example.com",
                user_metadata={"full_name": "Leander Antony"},
            ),
        )
    )
    auth_client = FakeAuthClient(exchange_response=response)

    monkeypatch.setattr(
        "src.auth_service.create_client",
        lambda *args, **kwargs: FakeSupabaseClient(auth_client),
    )
    monkeypatch.setattr("src.auth_service.ClientOptions", lambda **kwargs: kwargs)
    monkeypatch.setattr("src.auth_service.get_auth_pkce_code_verifier", lambda: None)
    monkeypatch.setattr("src.auth_service.set_auth_pkce_code_verifier", lambda value: None)
    monkeypatch.setattr(
        "src.auth_service.get_request_cookie",
        lambda key, default=None: auth_service_module._serialize_pkce_cookie_payload(
            "flow-123", "cookie-verifier"
        ),
    )

    service = AuthService(
        supabase_url="https://project.supabase.co",
        supabase_anon_key="anon-key",
        redirect_url="http://localhost:8501",
    )

    session = service.exchange_code_for_session("auth-code", auth_flow="flow-123")

    assert auth_client.exchange_payload == {
        "auth_code": "auth-code",
        "code_verifier": "cookie-verifier",
        "redirect_to": "http://localhost:8501?auth_flow=flow-123",
    }
    assert session.user.user_id == "user-123"


def test_exchange_code_for_session_uses_local_flow_store_when_memory_is_missing(monkeypatch, tmp_path):
    response = SimpleNamespace(
        session=SimpleNamespace(
            access_token="access-token",
            refresh_token="refresh-token",
            user=SimpleNamespace(
                id="user-123",
                email="user@example.com",
                user_metadata={"full_name": "Leander Antony"},
            ),
        )
    )
    auth_client = FakeAuthClient(exchange_response=response)

    monkeypatch.setattr(
        "src.auth_service.create_client",
        lambda *args, **kwargs: FakeSupabaseClient(auth_client),
    )
    monkeypatch.setattr("src.auth_service.ClientOptions", lambda **kwargs: kwargs)
    monkeypatch.setattr("src.auth_service.get_auth_pkce_code_verifier", lambda: None)
    monkeypatch.setattr("src.auth_service.get_request_cookie", lambda key, default=None: None)
    monkeypatch.setattr("src.auth_service.set_auth_pkce_code_verifier", lambda value: None)
    monkeypatch.setattr(
        auth_service_module,
        "_PKCE_FLOW_STORE_PATH",
        tmp_path / "auth.sqlite3",
    )

    auth_service_module._store_pkce_flow("flow-123", "stored-verifier")

    service = AuthService(
        supabase_url="https://project.supabase.co",
        supabase_anon_key="anon-key",
        redirect_url="http://localhost:8501",
    )

    session = service.exchange_code_for_session("auth-code", auth_flow="flow-123")

    assert auth_client.exchange_payload == {
        "auth_code": "auth-code",
        "code_verifier": "stored-verifier",
        "redirect_to": "http://localhost:8501?auth_flow=flow-123",
    }
    assert session.user.user_id == "user-123"
    assert auth_service_module._consume_pkce_flow("flow-123") is None


def test_exchange_code_for_session_requires_pkce_verifier(monkeypatch):
    auth_client = FakeAuthClient(exchange_response=None)

    monkeypatch.setattr(
        "src.auth_service.create_client",
        lambda *args, **kwargs: FakeSupabaseClient(auth_client),
    )
    monkeypatch.setattr("src.auth_service.ClientOptions", lambda **kwargs: kwargs)
    monkeypatch.setattr("src.auth_service.get_auth_pkce_code_verifier", lambda: None)

    service = AuthService(
        supabase_url="https://project.supabase.co",
        supabase_anon_key="anon-key",
        redirect_url="http://localhost:8501",
    )

    with pytest.raises(AppError, match="session expired"):
        service.exchange_code_for_session("auth-code", auth_flow="flow-123")


def test_get_google_sign_in_url_requires_configuration():
    service = AuthService(supabase_url="", supabase_anon_key="", redirect_url="")

    with pytest.raises(AppError):
        service.get_google_sign_in_url()
