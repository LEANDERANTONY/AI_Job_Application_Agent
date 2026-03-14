from types import SimpleNamespace

import pytest

from src.auth_service import AuthService
from src.errors import AppError
from src.history_store import HistoryStore


class FakeHistoryQuery:
    def __init__(self, response):
        self.response = response
        self.insert_payload = None
        self.select_fields = None
        self.eq_filter = None
        self.order_by = None
        self.limit_value = None

    def insert(self, payload):
        self.insert_payload = payload
        return self

    def select(self, fields):
        self.select_fields = fields
        return self

    def eq(self, field, value):
        self.eq_filter = (field, value)
        return self

    def order(self, field, desc=False):
        self.order_by = (field, desc)
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def execute(self):
        return self.response


class FakeHistoryClient:
    def __init__(self, responses):
        self.responses = {key: list(value) for key, value in responses.items()}
        self.queries = []

    def table(self, table_name):
        response = self.responses[table_name].pop(0)
        query = FakeHistoryQuery(response)
        query.table_name = table_name
        self.queries.append(query)
        return query


def test_history_store_creates_workflow_run(monkeypatch):
    auth_service = AuthService(
        supabase_url="https://project.supabase.co",
        supabase_anon_key="anon-key",
        redirect_url="http://localhost:8501",
    )
    client = FakeHistoryClient(
        {
            "workflow_runs": [
                SimpleNamespace(
                    data=[
                        {
                            "id": "run-1",
                            "user_id": "user-123",
                            "job_title": "Data Analyst",
                            "fit_score": 82,
                            "review_approved": True,
                            "model_policy": "gpt-5.4",
                            "workflow_signature": "sig-1",
                            "workflow_snapshot_json": "{\"candidate_profile\": {}}",
                            "report_payload_json": "{\"title\": \"Saved Report\", \"filename_stem\": \"saved-report\", \"summary\": \"summary\", \"markdown\": \"# Report\", \"plain_text\": \"Report\"}",
                            "tailored_resume_payload_json": "{\"title\": \"Saved Resume\", \"filename_stem\": \"saved-resume\", \"summary\": \"summary\", \"markdown\": \"# Resume\", \"plain_text\": \"Resume\", \"theme\": \"classic_ats\"}",
                            "created_at": "2026-03-14T00:00:00+00:00",
                        }
                    ]
                )
            ],
            "artifacts": [],
        }
    )
    monkeypatch.setattr(auth_service, "create_authenticated_client", lambda *args, **kwargs: client)
    store = HistoryStore(auth_service)

    record = store.create_workflow_run(
        "access-token",
        "refresh-token",
        {
            "user_id": "user-123",
            "job_title": "Data Analyst",
            "fit_score": 82,
            "review_approved": True,
            "model_policy": "gpt-5.4",
        },
    )

    assert record.id == "run-1"
    assert client.queries[0].table_name == "workflow_runs"
    assert client.queries[0].insert_payload["user_id"] == "user-123"
    assert client.queries[0].insert_payload["workflow_signature"] == ""


def test_history_store_lists_recent_workflow_runs(monkeypatch):
    auth_service = AuthService(
        supabase_url="https://project.supabase.co",
        supabase_anon_key="anon-key",
        redirect_url="http://localhost:8501",
    )
    client = FakeHistoryClient(
        {
            "workflow_runs": [
                SimpleNamespace(
                    data=[
                        {
                            "id": "run-2",
                            "user_id": "user-123",
                            "job_title": "ML Engineer",
                            "fit_score": 76,
                            "review_approved": False,
                            "model_policy": "gpt-5-mini-2025-08-07",
                            "workflow_signature": "sig-2",
                            "workflow_snapshot_json": "{\"candidate_profile\": {}}",
                            "report_payload_json": "{\"title\": \"Saved Report\", \"filename_stem\": \"saved-report\", \"summary\": \"summary\", \"markdown\": \"# Report\", \"plain_text\": \"Report\"}",
                            "tailored_resume_payload_json": "{\"title\": \"Saved Resume\", \"filename_stem\": \"saved-resume\", \"summary\": \"summary\", \"markdown\": \"# Resume\", \"plain_text\": \"Resume\", \"theme\": \"modern_professional\"}",
                            "created_at": "2026-03-14T01:00:00+00:00",
                        }
                    ]
                )
            ],
            "artifacts": [],
        }
    )
    monkeypatch.setattr(auth_service, "create_authenticated_client", lambda *args, **kwargs: client)
    store = HistoryStore(auth_service)

    rows = store.list_recent_workflow_runs("access-token", "refresh-token", "user-123")

    assert len(rows) == 1
    assert rows[0].job_title == "ML Engineer"
    assert rows[0].workflow_signature == "sig-2"
    assert rows[0].report_payload_json.startswith("{")
    assert client.queries[0].order_by == ("created_at", True)


def test_history_store_creates_artifact_record(monkeypatch):
    auth_service = AuthService(
        supabase_url="https://project.supabase.co",
        supabase_anon_key="anon-key",
        redirect_url="http://localhost:8501",
    )
    client = FakeHistoryClient(
        {
            "workflow_runs": [],
            "artifacts": [
                SimpleNamespace(
                    data=[
                        {
                            "id": "artifact-1",
                            "workflow_run_id": "run-1",
                            "artifact_type": "application_report_pdf",
                            "filename_stem": "candidate-data-analyst",
                            "storage_path": "candidate-data-analyst.pdf",
                            "created_at": "2026-03-14T02:00:00+00:00",
                        }
                    ]
                )
            ],
        }
    )
    monkeypatch.setattr(auth_service, "create_authenticated_client", lambda *args, **kwargs: client)
    store = HistoryStore(auth_service)

    artifact = store.create_artifact_record(
        "access-token",
        "refresh-token",
        {
            "workflow_run_id": "run-1",
            "artifact_type": "application_report_pdf",
            "filename_stem": "candidate-data-analyst",
            "storage_path": "candidate-data-analyst.pdf",
        },
    )

    assert artifact.id == "artifact-1"
    assert client.queries[0].table_name == "artifacts"


def test_history_store_surfaces_read_failures(monkeypatch):
    auth_service = AuthService(
        supabase_url="https://project.supabase.co",
        supabase_anon_key="anon-key",
        redirect_url="http://localhost:8501",
    )

    class FailingClient:
        def table(self, table_name):
            raise RuntimeError("permission denied")

    monkeypatch.setattr(auth_service, "create_authenticated_client", lambda *args, **kwargs: FailingClient())
    store = HistoryStore(auth_service)

    with pytest.raises(AppError):
        store.list_recent_workflow_runs("access-token", "refresh-token", "user-123")