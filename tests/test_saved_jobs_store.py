from types import SimpleNamespace

from src.auth_service import AuthService
from src.saved_jobs_store import SavedJobsStore


class FakeSavedJobsQuery:
    def __init__(self, response):
        self.response = response
        self.upsert_payload = None
        self.upsert_conflict = None
        self.select_fields = None
        self.eq_filters = []
        self.ordering = None
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
        self.eq_filters.append((field, value))
        return self

    def order(self, field, desc=False):
        self.ordering = (field, desc)
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    def delete(self):
        self.deleted = True
        return self

    def execute(self):
        return self.response


class FakeSavedJobsClient:
    def __init__(self, responses):
        self.responses = {key: list(value) for key, value in responses.items()}
        self.queries = []

    def table(self, table_name):
        response = self.responses[table_name].pop(0)
        query = FakeSavedJobsQuery(response)
        query.table_name = table_name
        self.queries.append(query)
        return query


def test_saved_jobs_store_upserts_job(monkeypatch):
    auth_service = AuthService(
        supabase_url="https://project.supabase.co",
        supabase_anon_key="anon-key",
        redirect_url="http://localhost:8501",
    )
    client = FakeSavedJobsClient(
        {
            "saved_jobs": [
                SimpleNamespace(
                    data=[
                        {
                            "user_id": "user-123",
                            "job_id": "greenhouse:narvar:1",
                            "source": "greenhouse",
                            "title": "Sr. AI Engineer",
                            "company": "Narvar",
                            "metadata": {"departments": ["Engineering"]},
                        }
                    ]
                )
            ]
        }
    )
    monkeypatch.setattr(auth_service, "create_authenticated_client", lambda *args, **kwargs: client)
    store = SavedJobsStore(auth_service)

    record = store.save_job(
        "access-token",
        "refresh-token",
        {
            "user_id": "user-123",
            "job_id": "greenhouse:narvar:1",
            "source": "greenhouse",
            "title": "Sr. AI Engineer",
            "company": "Narvar",
            "metadata": {"departments": ["Engineering"]},
        },
    )

    assert record.job_id == "greenhouse:narvar:1"
    assert client.queries[0].table_name == "saved_jobs"
    assert client.queries[0].upsert_conflict == "user_id,job_id"
    assert client.queries[0].upsert_payload["user_id"] == "user-123"


def test_saved_jobs_store_lists_recent_jobs(monkeypatch):
    auth_service = AuthService(
        supabase_url="https://project.supabase.co",
        supabase_anon_key="anon-key",
        redirect_url="http://localhost:8501",
    )
    client = FakeSavedJobsClient(
        {
            "saved_jobs": [
                SimpleNamespace(
                    data=[
                        {
                            "user_id": "user-123",
                            "job_id": "lever:mistral:1",
                            "source": "lever",
                            "title": "AI Engineer",
                            "company": "Mistral",
                            "saved_at": "2026-04-02T10:00:00+00:00",
                        }
                    ]
                )
            ]
        }
    )
    monkeypatch.setattr(auth_service, "create_authenticated_client", lambda *args, **kwargs: client)
    store = SavedJobsStore(auth_service)

    records = store.list_jobs("access-token", "refresh-token", "user-123")

    assert len(records) == 1
    assert records[0].title == "AI Engineer"
    assert client.queries[0].eq_filters == [("user_id", "user-123")]
    assert client.queries[0].ordering == ("saved_at", True)


def test_saved_jobs_store_deletes_job(monkeypatch):
    auth_service = AuthService(
        supabase_url="https://project.supabase.co",
        supabase_anon_key="anon-key",
        redirect_url="http://localhost:8501",
    )
    client = FakeSavedJobsClient({"saved_jobs": [SimpleNamespace(data=[])]})
    monkeypatch.setattr(auth_service, "create_authenticated_client", lambda *args, **kwargs: client)
    store = SavedJobsStore(auth_service)

    store.delete_job("access-token", "refresh-token", "user-123", "greenhouse:narvar:1")

    assert client.queries[0].deleted is True
    assert client.queries[0].eq_filters == [("user_id", "user-123"), ("job_id", "greenhouse:narvar:1")]
