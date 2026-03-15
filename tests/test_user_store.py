from types import SimpleNamespace

import pytest

from src.auth_service import AuthService, AuthSession, AuthUser
from src.errors import AppError
from src.user_store import AppUserStore


class FakeQuery:
    def __init__(self, response):
        self.response = response
        self.upsert_payload = None
        self.on_conflict = None

    def upsert(self, payload, on_conflict=None):
        self.upsert_payload = payload
        self.on_conflict = on_conflict
        return self

    def execute(self):
        return self.response


class FakeTableClient:
    def __init__(self, response):
        self.response = response
        self.last_query = None
        self.table_name = None

    def table(self, table_name):
        self.table_name = table_name
        self.last_query = FakeQuery(self.response)
        return self.last_query


def test_restore_session_accepts_direct_session_object(monkeypatch):
    direct_session = SimpleNamespace(
        access_token="access-token",
        refresh_token="refresh-token",
        user=SimpleNamespace(
            id="user-123",
            email="user@example.com",
            user_metadata={"full_name": "Leander Antony"},
        ),
    )
    service = AuthService(
        supabase_url="https://project.supabase.co",
        supabase_anon_key="anon-key",
        redirect_url="http://localhost:8501",
    )
    monkeypatch.setattr(service, "create_authenticated_client", lambda *args, **kwargs: SimpleNamespace(auth=SimpleNamespace(get_session=lambda: direct_session)))

    session = service.restore_session("access-token", "refresh-token")

    assert session.user.user_id == "user-123"
    assert session.user.display_name == "Leander Antony"


def test_app_user_store_syncs_user_record(monkeypatch):
    auth_service = AuthService(
        supabase_url="https://project.supabase.co",
        supabase_anon_key="anon-key",
        redirect_url="http://localhost:8501",
    )
    table_client = FakeTableClient(
        response=SimpleNamespace(
            data=[
                {
                    "id": "user-123",
                    "email": "user@example.com",
                    "display_name": "Leander Antony",
                    "avatar_url": "https://example.com/avatar.png",
                    "created_at": "2026-03-14T00:00:00+00:00",
                    "last_seen_at": "2026-03-14T00:01:00+00:00",
                    "plan_tier": "free",
                    "account_status": "active",
                }
            ]
        )
    )
    monkeypatch.setattr(
        auth_service,
        "create_authenticated_client",
        lambda access_token, refresh_token: table_client,
    )
    store = AppUserStore(auth_service)
    auth_session = AuthSession(
        access_token="access-token",
        refresh_token="refresh-token",
        user=AuthUser(
            user_id="user-123",
            email="user@example.com",
            display_name="Leander Antony",
            avatar_url="https://example.com/avatar.png",
        ),
    )

    record = store.sync_user_record(auth_session)

    assert table_client.table_name == "app_users"
    assert table_client.last_query.on_conflict == "id"
    assert table_client.last_query.upsert_payload["id"] == "user-123"
    assert record.plan_tier == "free"
    assert record.account_status == "active"


def test_app_user_store_surfaces_sync_failures(monkeypatch):
    auth_service = AuthService(
        supabase_url="https://project.supabase.co",
        supabase_anon_key="anon-key",
        redirect_url="http://localhost:8501",
    )

    class FailingTableClient:
        def table(self, table_name):
            raise RuntimeError("relation public.app_users does not exist")

    monkeypatch.setattr(
        auth_service,
        "create_authenticated_client",
        lambda access_token, refresh_token: FailingTableClient(),
    )
    store = AppUserStore(auth_service)
    auth_session = AuthSession(
        access_token="access-token",
        refresh_token="refresh-token",
        user=AuthUser(user_id="user-123", email="user@example.com"),
    )

    with pytest.raises(AppError) as error:
        store.sync_user_record(auth_session)

    assert "could not sync your account record" in error.value.user_message.lower()


def test_app_user_store_assigns_internal_plan_to_allowlisted_email(monkeypatch):
    auth_service = AuthService(
        supabase_url="https://project.supabase.co",
        supabase_anon_key="anon-key",
        redirect_url="http://localhost:8501",
    )
    table_client = FakeTableClient(
        response=SimpleNamespace(
            data=[
                {
                    "id": "user-123",
                    "email": "antony.leander@gmail.com",
                    "display_name": "Leander Antony",
                    "avatar_url": "https://example.com/avatar.png",
                    "created_at": "2026-03-14T00:00:00+00:00",
                    "last_seen_at": "2026-03-14T00:01:00+00:00",
                    "plan_tier": "internal",
                    "account_status": "active",
                }
            ]
        )
    )
    monkeypatch.setattr(
        auth_service,
        "create_authenticated_client",
        lambda access_token, refresh_token: table_client,
    )
    monkeypatch.setattr(
        "src.user_store.get_default_plan_tier_for_email",
        lambda email, fallback=None: "internal" if str(email).lower() == "antony.leander@gmail.com" else (fallback or "free"),
    )
    store = AppUserStore(auth_service)
    auth_session = AuthSession(
        access_token="access-token",
        refresh_token="refresh-token",
        user=AuthUser(
            user_id="user-123",
            email="antony.leander@gmail.com",
            display_name="Leander Antony",
            avatar_url="https://example.com/avatar.png",
        ),
    )

    record = store.sync_user_record(auth_session)

    assert table_client.last_query.upsert_payload["plan_tier"] == "internal"
    assert record.plan_tier == "internal"