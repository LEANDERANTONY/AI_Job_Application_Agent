from types import SimpleNamespace

import pytest

from src.auth_service import AuthService
from src.errors import AppError
from src.usage_store import UsageStore


class FakeInsertQuery:
    def __init__(self, response):
        self.response = response
        self.insert_payload = None

    def insert(self, payload):
        self.insert_payload = payload
        return self

    def execute(self):
        return self.response


class FakeUsageTableClient:
    def __init__(self, response):
        self.response = response
        self.table_name = None
        self.query = None

    def table(self, table_name):
        self.table_name = table_name
        self.query = FakeInsertQuery(self.response)
        return self.query


def test_usage_store_records_usage_event(monkeypatch):
    auth_service = AuthService(
        supabase_url="https://project.supabase.co",
        supabase_anon_key="anon-key",
        redirect_url="http://localhost:8501",
    )
    table_client = FakeUsageTableClient(
        SimpleNamespace(
            data=[
                {
                    "user_id": "user-123",
                    "task_name": "review",
                    "model_name": "gpt-5.4",
                    "request_count": 1,
                    "prompt_tokens": 10,
                    "completion_tokens": 6,
                    "total_tokens": 16,
                    "response_id": "resp_1",
                    "status": "completed",
                    "created_at": "2026-03-14T00:00:00+00:00",
                }
            ]
        )
    )
    monkeypatch.setattr(
        auth_service,
        "create_authenticated_client",
        lambda access_token, refresh_token: table_client,
    )
    store = UsageStore(auth_service)

    record = store.record_usage_event(
        "access-token",
        "refresh-token",
        {
            "user_id": "user-123",
            "task_name": "review",
            "model_name": "gpt-5.4",
            "request_count": 1,
            "prompt_tokens": 10,
            "completion_tokens": 6,
            "total_tokens": 16,
            "response_id": "resp_1",
            "status": "completed",
        },
    )

    assert table_client.table_name == "usage_events"
    assert table_client.query.insert_payload["user_id"] == "user-123"
    assert record.total_tokens == 16
    assert record.response_id == "resp_1"


def test_usage_store_requires_user_id(monkeypatch):
    auth_service = AuthService(
        supabase_url="https://project.supabase.co",
        supabase_anon_key="anon-key",
        redirect_url="http://localhost:8501",
    )
    monkeypatch.setattr(
        auth_service,
        "create_authenticated_client",
        lambda access_token, refresh_token: FakeUsageTableClient(SimpleNamespace(data=[])),
    )
    store = UsageStore(auth_service)

    with pytest.raises(AppError):
        store.record_usage_event(
            "access-token",
            "refresh-token",
            {"task_name": "review"},
        )


def test_usage_store_aggregates_daily_usage_totals(monkeypatch):
    auth_service = AuthService(
        supabase_url="https://project.supabase.co",
        supabase_anon_key="anon-key",
        redirect_url="http://localhost:8501",
    )

    class FakeDailyQuery(FakeInsertQuery):
        def select(self, fields):
            self.fields = fields
            return self

        def eq(self, field, value):
            self.user_filter = (field, value)
            return self

        def gte(self, field, value):
            self.gte_filter = (field, value)
            return self

        def lt(self, field, value):
            self.lt_filter = (field, value)
            return self

    class FakeDailyClient(FakeUsageTableClient):
        def table(self, table_name):
            self.table_name = table_name
            self.query = FakeDailyQuery(
                SimpleNamespace(
                    data=[
                        {
                            "request_count": 1,
                            "prompt_tokens": 12,
                            "completion_tokens": 5,
                            "total_tokens": 17,
                        },
                        {
                            "request_count": 2,
                            "prompt_tokens": 9,
                            "completion_tokens": 4,
                            "total_tokens": 13,
                        },
                    ]
                )
            )
            return self.query

    table_client = FakeDailyClient(SimpleNamespace(data=[]))
    monkeypatch.setattr(
        auth_service,
        "create_authenticated_client",
        lambda access_token, refresh_token: table_client,
    )
    store = UsageStore(auth_service)

    totals = store.get_daily_usage_totals("access-token", "refresh-token", "user-123")

    assert table_client.table_name == "usage_events"
    assert totals["request_count"] == 3
    assert totals["prompt_tokens"] == 21
    assert totals["completion_tokens"] == 9
    assert totals["total_tokens"] == 30