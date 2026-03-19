from src.job_sources.greenhouse import GreenhouseJobSourceAdapter
from src.schemas import JobSearchQuery


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(
            {
                "url": url,
                "params": params,
                "timeout": timeout,
            }
        )
        return _FakeResponse(self.payload)


def test_greenhouse_adapter_returns_normalized_results():
    fake_session = _FakeSession(
        {
            "jobs": [
                {
                    "id": 123,
                    "internal_job_id": 456,
                    "title": "Machine Learning Engineer",
                    "updated_at": "2026-03-19T09:00:00Z",
                    "requisition_id": "REQ-1",
                    "location": {"name": "Bengaluru, India"},
                    "absolute_url": "https://boards.greenhouse.io/example/jobs/123",
                    "language": "en",
                    "metadata": {"company_name": "Example AI"},
                    "content": "<p>Build ML systems with Python and SQL.</p>",
                    "departments": [{"name": "Engineering"}],
                    "offices": [{"name": "Bengaluru"}],
                }
            ]
        }
    )
    adapter = GreenhouseJobSourceAdapter(
        board_tokens=["example"],
        http_session=fake_session,
    )

    response = adapter.search(
        JobSearchQuery(query="machine learning engineer", location="Bengaluru", page_size=10)
    )

    assert response.status == "ok"
    assert len(response.results) == 1
    assert response.results[0].source == "greenhouse"
    assert response.results[0].company == "Example AI"
    assert response.results[0].metadata["board_token"] == "example"
    assert response.source_details["example"] == "matched"
    assert fake_session.calls[0]["params"] == {"content": "true"}


def test_greenhouse_adapter_reports_not_configured_without_board_tokens():
    adapter = GreenhouseJobSourceAdapter(board_tokens=[])

    response = adapter.search(JobSearchQuery(query="data scientist"))

    assert response.status == "not_configured"
    assert response.results == []
    assert response.source_details["greenhouse"] == "not_configured"


def test_greenhouse_adapter_can_resolve_job_url():
    adapter = GreenhouseJobSourceAdapter(board_tokens=[])

    assert adapter.can_resolve_url("https://boards.greenhouse.io/narvar/jobs/123456")
    assert not adapter.can_resolve_url("https://example.com/jobs/123456")


def test_greenhouse_adapter_resolves_job_url_to_posting():
    fake_session = _FakeSession(
        {
            "id": 123,
            "internal_job_id": 456,
            "title": "Machine Learning Engineer",
            "updated_at": "2026-03-19T09:00:00Z",
            "requisition_id": "REQ-1",
            "location": {"name": "Bengaluru, India"},
            "absolute_url": "https://boards.greenhouse.io/narvar/jobs/123",
            "language": "en",
            "metadata": {"company_name": "Narvar"},
            "content": "<p>Build ML systems with Python and SQL.</p>",
            "departments": [{"name": "Engineering"}],
            "offices": [{"name": "Bengaluru"}],
        }
    )
    adapter = GreenhouseJobSourceAdapter(
        board_tokens=[],
        http_session=fake_session,
    )

    response = adapter.resolve_url("https://boards.greenhouse.io/narvar/jobs/123")

    assert response.status == "ok"
    assert response.job_posting is not None
    assert response.job_posting.company == "Narvar"
    assert response.source_details["narvar"] == "resolved"


def test_greenhouse_adapter_repairs_common_html_and_mojibake_artifacts():
    fake_session = _FakeSession(
        {
            "id": 123,
            "internal_job_id": 456,
            "title": "Sr. AI Engineer",
            "updated_at": "2026-03-19T09:00:00Z",
            "requisition_id": "REQ-1",
            "location": {"name": "Remote - Canada"},
            "absolute_url": "https://job-boards.greenhouse.io/narvar/jobs/123",
            "language": "en",
            "metadata": {"company_name": "narvar"},
            "content": "<p>We&amp;rsquo;re building agentic AI &amp;mdash; with&nbsp;Python.</p>",
            "departments": [{"name": "Engineering"}],
            "offices": [{"name": "Remote - Canada"}],
        }
    )
    adapter = GreenhouseJobSourceAdapter(
        board_tokens=[],
        http_session=fake_session,
    )

    response = adapter.resolve_url("https://job-boards.greenhouse.io/narvar/jobs/123")

    assert response.job_posting is not None
    assert response.job_posting.company == "Narvar"
    assert "We’re building agentic AI — with Python." in response.job_posting.description_text
