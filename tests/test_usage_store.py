from datetime import datetime, timezone
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


class FakeRpcQuery:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.function_name = None
        self.params = None

    def execute(self):
        if self.error is not None:
            raise self.error
        return self.response


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
        def __init__(self, response):
            super().__init__(response)
            self.rpc_query = None

        def rpc(self, function_name, params):
            self.rpc_query = FakeRpcQuery(error=RuntimeError("rpc unavailable"))
            self.rpc_query.function_name = function_name
            self.rpc_query.params = params
            return self.rpc_query

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
    assert table_client.rpc_query.function_name == "get_daily_usage_totals"
    assert totals["request_count"] == 3
    assert totals["prompt_tokens"] == 21
    assert totals["completion_tokens"] == 9
    assert totals["total_tokens"] == 30


def test_usage_store_prefers_rpc_daily_usage_aggregation(monkeypatch):
    auth_service = AuthService(
        supabase_url="https://project.supabase.co",
        supabase_anon_key="anon-key",
        redirect_url="http://localhost:8501",
    )

    class FakeRpcClient:
        def __init__(self):
            self.table_called = False
            self.rpc_query = None

        def rpc(self, function_name, params):
            self.rpc_query = FakeRpcQuery(
                response=SimpleNamespace(
                    data={
                        "request_count": 4,
                        "prompt_tokens": 40,
                        "completion_tokens": 10,
                        "total_tokens": 50,
                        "window_start": "2026-03-16T00:00:00+00:00",
                        "window_end": "2026-03-17T00:00:00+00:00",
                    }
                )
            )
            self.rpc_query.function_name = function_name
            self.rpc_query.params = params
            return self.rpc_query

        def table(self, table_name):
            self.table_called = True
            raise AssertionError("table fallback should not run when rpc succeeds")

    client = FakeRpcClient()
    monkeypatch.setattr(
        auth_service,
        "create_authenticated_client",
        lambda access_token, refresh_token: client,
    )
    monkeypatch.setattr(
        UsageStore,
        "_daily_window_bounds",
        staticmethod(
            lambda now=None: (
                datetime(2026, 3, 16, tzinfo=timezone.utc),
                datetime(2026, 3, 17, tzinfo=timezone.utc),
            )
        ),
    )
    store = UsageStore(auth_service)

    totals = store.get_daily_usage_totals("access-token", "refresh-token", "user-123")

    assert client.rpc_query.function_name == "get_daily_usage_totals"
    assert client.rpc_query.params["target_user_id"] == "user-123"
    assert client.rpc_query.params["target_window_start"] == "2026-03-16T00:00:00+00:00"
    assert client.rpc_query.params["target_window_end"] == "2026-03-17T00:00:00+00:00"
    assert totals["request_count"] == 4
    assert totals["prompt_tokens"] == 40
    assert totals["completion_tokens"] == 10
    assert totals["total_tokens"] == 50
    assert totals["window_start"] == "2026-03-16T00:00:00+00:00"
    assert totals["window_end"] == "2026-03-17T00:00:00+00:00"