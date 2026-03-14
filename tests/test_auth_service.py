from types import SimpleNamespace

import pytest

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

    service = AuthService(
        supabase_url="https://project.supabase.co",
        supabase_anon_key="anon-key",
        redirect_url="http://localhost:8501",
    )

    sign_in_url = service.get_google_sign_in_url()

    assert sign_in_url == "https://example.com/oauth"
    assert auth_client.oauth_payload["provider"] == "google"
    assert auth_client.oauth_payload["options"]["redirect_to"] == "http://localhost:8501"


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

    service = AuthService(
        supabase_url="https://project.supabase.co",
        supabase_anon_key="anon-key",
        redirect_url="http://localhost:8501",
    )

    session = service.exchange_code_for_session("auth-code")

    assert auth_client.exchange_payload == {"auth_code": "auth-code"}
    assert session.access_token == "access-token"
    assert session.refresh_token == "refresh-token"
    assert session.user.user_id == "user-123"
    assert session.user.email == "user@example.com"
    assert session.user.display_name == "Leander Antony"
    assert session.user.avatar_url == "https://example.com/avatar.png"


def test_get_google_sign_in_url_requires_configuration():
    service = AuthService(supabase_url="", supabase_anon_key="", redirect_url="")

    with pytest.raises(AppError):
        service.get_google_sign_in_url()