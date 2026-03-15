from datetime import datetime, timezone
from types import SimpleNamespace

from src.auth_service import AuthService
from src.saved_workspace_store import SavedWorkspaceStore


class FakeSavedWorkspaceQuery:
    def __init__(self, response):
        self.response = response
        self.upsert_payload = None
        self.upsert_conflict = None
        self.select_fields = None
        self.eq_filter = None
        self.lte_filter = None
        self.limit_value = None
        self.deleted = False

    def upsert(self, payload, on_conflict=None):
        self.upsert_payload = payload
        self.upsert_conflict = on_conflict
        return self

    def select(self, fields):
        self.select_fields = fields
        return self

    def eq(self, field, value):
        self.eq_filter = (field, value)
        return self

    def lte(self, field, value):
        self.lte_filter = (field, value)
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def delete(self):
        self.deleted = True
        return self

    def execute(self):
        return self.response


class FakeSavedWorkspaceClient:
    def __init__(self, responses):
        self.responses = {key: list(value) for key, value in responses.items()}
        self.queries = []

    def table(self, table_name):
        response = self.responses[table_name].pop(0)
        query = FakeSavedWorkspaceQuery(response)
        query.table_name = table_name
        self.queries.append(query)
        return query


def test_saved_workspace_store_upserts_single_row(monkeypatch):
    auth_service = AuthService(
        supabase_url="https://project.supabase.co",
        supabase_anon_key="anon-key",
        redirect_url="http://localhost:8501",
    )
    client = FakeSavedWorkspaceClient(
        {
            "saved_workspaces": [
                SimpleNamespace(data=[]),
                SimpleNamespace(
                    data=[
                        {
                            "user_id": "user-123",
                            "job_title": "Data Analyst",
                            "workflow_signature": "sig-1",
                            "workflow_snapshot_json": "{\"version\": 1}",
                            "report_payload_json": "{\"version\": 1}",
                            "tailored_resume_payload_json": "{\"version\": 1}",
                            "expires_at": "2026-03-16T00:00:00+00:00",
                            "updated_at": "2026-03-15T00:00:00+00:00",
                        }
                    ]
                )
            ]
        }
    )
    monkeypatch.setattr(auth_service, "create_authenticated_client", lambda *args, **kwargs: client)
    store = SavedWorkspaceStore(auth_service)

    record = store.save_workspace(
        "access-token",
        "refresh-token",
        {
            "user_id": "user-123",
            "job_title": "Data Analyst",
            "workflow_signature": "sig-1",
            "workflow_snapshot_json": "snapshot",
            "report_payload_json": "report",
            "tailored_resume_payload_json": "resume",
        },
    )

    assert record.user_id == "user-123"
    assert client.queries[0].table_name == "saved_workspaces"
    assert client.queries[0].deleted is True
    assert client.queries[0].eq_filter == ("user_id", "user-123")
    assert client.queries[0].lte_filter[0] == "expires_at"
    assert client.queries[1].upsert_conflict == "user_id"
    assert client.queries[1].upsert_payload["user_id"] == "user-123"
    assert client.queries[1].upsert_payload["expires_at"]


def test_saved_workspace_store_deletes_expired_rows_on_load(monkeypatch):
    auth_service = AuthService(
        supabase_url="https://project.supabase.co",
        supabase_anon_key="anon-key",
        redirect_url="http://localhost:8501",
    )
    client = FakeSavedWorkspaceClient(
        {
            "saved_workspaces": [
                SimpleNamespace(data=[]),
                SimpleNamespace(
                    data=[
                        {
                            "user_id": "user-123",
                            "job_title": "Expired Snapshot",
                            "workflow_signature": "sig-1",
                            "workflow_snapshot_json": "snapshot",
                            "report_payload_json": "report",
                            "tailored_resume_payload_json": "resume",
                            "expires_at": "2026-03-15T00:00:00+00:00",
                            "updated_at": "2026-03-14T00:00:00+00:00",
                        }
                    ]
                ),
                SimpleNamespace(data=[]),
            ]
        }
    )
    monkeypatch.setattr(auth_service, "create_authenticated_client", lambda *args, **kwargs: client)
    store = SavedWorkspaceStore(auth_service)

    record, status = store.load_workspace(
        "access-token",
        "refresh-token",
        "user-123",
        now=datetime(2026, 3, 15, 1, 0, tzinfo=timezone.utc),
    )

    assert record is None
    assert status == "expired"
    assert client.queries[0].deleted is True
    assert client.queries[0].eq_filter == ("user_id", "user-123")
    assert client.queries[0].lte_filter[0] == "expires_at"
    assert client.queries[2].deleted is True