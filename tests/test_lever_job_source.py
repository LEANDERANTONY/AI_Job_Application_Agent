from src.job_sources.lever import LeverJobSourceAdapter
from src.schemas import JobSearchQuery


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("request failed")
        return None

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        payload = self.payload(url, params) if callable(self.payload) else self.payload
        return _FakeResponse(payload)


def test_lever_adapter_returns_normalized_results():
    fake_session = _FakeSession(
        [
            {
                "id": "abc-123",
                "text": "Senior Backend Engineer",
                "categories": {
                    "commitment": "Employee: Full Time",
                    "location": "Bengaluru, India",
                    "team": "Engineering",
                    "allLocations": ["Bengaluru, India"],
                },
                "descriptionPlain": "Build backend systems with Python and APIs.",
                "descriptionBodyPlain": "Build backend systems with Python and APIs.",
                "additionalPlain": "",
                "hostedUrl": "https://jobs.lever.co/example/abc-123",
                "applyUrl": "https://jobs.lever.co/example/abc-123/apply",
                "salaryRange": {"currency": "INR", "min": 3000000, "max": 4500000, "interval": "per-year-salary"},
                "salaryDescriptionPlain": "Plus bonus",
                "workplaceType": "hybrid",
                "createdAt": 1774015783631,
                "lists": [{"text": "Requirements", "content": "<ul><li>Python</li><li>APIs</li></ul>"}],
            }
        ]
    )
    adapter = LeverJobSourceAdapter(site_names=["example"], http_session=fake_session)

    response = adapter.search(
        JobSearchQuery(query="backend engineer", location="Bengaluru", page_size=10)
    )

    assert response.status == "ok"
    assert len(response.results) == 1
    assert response.results[0].source == "lever"
    assert response.results[0].company == "Example"
    assert response.results[0].metadata["site_name"] == "example"
    assert response.results[0].metadata["salary_text"].startswith("INR 3,000,000 - 4,500,000")
    assert response.source_details["example"] == "matched"
    assert fake_session.calls[0]["params"] == {"mode": "json", "limit": 100}


def test_lever_adapter_matches_bangalore_query_to_bengaluru_location():
    fake_session = _FakeSession(
        [
            {
                "id": "abc-123",
                "text": "Senior Backend Engineer",
                "categories": {
                    "commitment": "Employee: Full Time",
                    "location": "Bengaluru, India",
                    "team": "Engineering",
                    "allLocations": ["Bengaluru, India"],
                },
                "descriptionPlain": "Build backend systems with Python and APIs.",
                "descriptionBodyPlain": "Build backend systems with Python and APIs.",
                "additionalPlain": "",
                "hostedUrl": "https://jobs.lever.co/example/abc-123",
                "applyUrl": "https://jobs.lever.co/example/abc-123/apply",
                "salaryRange": {},
                "workplaceType": "hybrid",
                "createdAt": 1774015783631,
                "lists": [],
            }
        ]
    )
    adapter = LeverJobSourceAdapter(site_names=["example"], http_session=fake_session)

    response = adapter.search(
        JobSearchQuery(query="backend engineer", location="Bangalore", page_size=10)
    )

    assert response.status == "ok"
    assert len(response.results) == 1


def test_lever_adapter_reports_not_configured_without_site_names():
    adapter = LeverJobSourceAdapter(site_names=[])

    response = adapter.search(JobSearchQuery(query="software engineer"))

    assert response.status == "not_configured"
    assert response.results == []
    assert response.source_details["lever"] == "not_configured"


def test_lever_adapter_can_resolve_job_url():
    adapter = LeverJobSourceAdapter(site_names=[])

    assert adapter.can_resolve_url("https://jobs.lever.co/dnb/1c877a65-5423-49cc-9e8f-45b5a9f72fb5")
    assert adapter.can_resolve_url("https://jobs.eu.lever.co/example/12345")
    assert not adapter.can_resolve_url("https://example.com/jobs/12345")


def test_lever_adapter_resolves_job_url_to_posting():
    fake_session = _FakeSession(
        {
            "id": "abc-123",
            "text": "Senior Backend Engineer",
            "categories": {
                "commitment": "Employee: Full Time",
                "location": "Remote - India",
                "team": "Engineering",
                "allLocations": ["Remote - India"],
            },
            "descriptionPlain": "Build backend systems with Python and APIs.",
            "descriptionBodyPlain": "Build backend systems with Python and APIs.",
            "additionalPlain": "",
            "hostedUrl": "https://jobs.lever.co/example/abc-123",
            "applyUrl": "https://jobs.lever.co/example/abc-123/apply",
            "salaryRange": {"currency": "INR", "min": 3000000, "max": 4500000, "interval": "per-year-salary"},
            "workplaceType": "remote",
            "createdAt": 1774015783631,
            "lists": [],
        }
    )
    adapter = LeverJobSourceAdapter(site_names=[], http_session=fake_session)

    response = adapter.resolve_url("https://jobs.lever.co/example/abc-123")

    assert response.status == "ok"
    assert response.job_posting is not None
    assert response.job_posting.company == "Example"
    assert response.source_details["example"] == "resolved"


def test_lever_adapter_avoids_false_positive_without_title_signal():
    fake_session = _FakeSession(
        [
            {
                "id": "sales-1",
                "text": "New Business Sales Executive",
                "categories": {
                    "commitment": "Employee: Full Time",
                    "location": "Remote",
                    "team": "Sales",
                },
                "descriptionPlain": "Work with data products and partner closely with the engineering team.",
                "descriptionBodyPlain": "Work with data products and partner closely with the engineering team.",
                "additionalPlain": "",
                "hostedUrl": "https://jobs.lever.co/example/sales-1",
                "applyUrl": "https://jobs.lever.co/example/sales-1/apply",
                "workplaceType": "remote",
                "createdAt": 1774015783631,
                "lists": [],
            }
        ]
    )
    adapter = LeverJobSourceAdapter(site_names=["example"], http_session=fake_session)

    response = adapter.search(JobSearchQuery(query="data engineer", page_size=10))

    assert response.status == "ok"
    assert response.results == []


def test_lever_adapter_respects_role_family_for_data_engineer_queries():
    fake_session = _FakeSession(
        [
            {
                "id": "manager-1",
                "text": "Engineering Manager - Data Partnerships",
                "categories": {
                    "commitment": "Employee: Full Time",
                    "location": "Remote",
                    "team": "Engineering",
                },
                "descriptionPlain": "Lead data partnership initiatives.",
                "descriptionBodyPlain": "Lead data partnership initiatives.",
                "additionalPlain": "",
                "hostedUrl": "https://jobs.lever.co/example/manager-1",
                "applyUrl": "https://jobs.lever.co/example/manager-1/apply",
                "workplaceType": "remote",
                "createdAt": 1774015783631,
                "lists": [],
            },
            {
                "id": "de-1",
                "text": "Senior Data Engineer",
                "categories": {
                    "commitment": "Employee: Full Time",
                    "location": "Remote",
                    "team": "Engineering",
                },
                "descriptionPlain": "Build ETL pipelines and warehouse systems.",
                "descriptionBodyPlain": "Build ETL pipelines and warehouse systems.",
                "additionalPlain": "",
                "hostedUrl": "https://jobs.lever.co/example/de-1",
                "applyUrl": "https://jobs.lever.co/example/de-1/apply",
                "workplaceType": "remote",
                "createdAt": 1774015783632,
                "lists": [],
            },
        ]
    )
    adapter = LeverJobSourceAdapter(site_names=["example"], http_session=fake_session)

    response = adapter.search(JobSearchQuery(query="data engineer", page_size=10))

    assert [posting.title for posting in response.results] == ["Senior Data Engineer"]


def test_lever_adapter_filters_ai_engineer_queries_away_from_non_engineering_ai_roles():
    fake_session = _FakeSession(
        [
            {
                "id": "pm-1",
                "text": "Staff Product Manager, Applied AI",
                "categories": {
                    "commitment": "Employee: Full Time",
                    "location": "Remote",
                    "team": "Product",
                },
                "descriptionPlain": "Drive applied AI product strategy.",
                "descriptionBodyPlain": "Drive applied AI product strategy.",
                "additionalPlain": "",
                "hostedUrl": "https://jobs.lever.co/example/pm-1",
                "applyUrl": "https://jobs.lever.co/example/pm-1/apply",
                "workplaceType": "remote",
                "createdAt": 1774015783631,
                "lists": [],
            },
            {
                "id": "ai-1",
                "text": "Applied AI, Forward Deployed AI Engineer",
                "categories": {
                    "commitment": "Employee: Full Time",
                    "location": "Remote",
                    "team": "Engineering",
                },
                "descriptionPlain": "Build and deploy AI systems.",
                "descriptionBodyPlain": "Build and deploy AI systems.",
                "additionalPlain": "",
                "hostedUrl": "https://jobs.lever.co/example/ai-1",
                "applyUrl": "https://jobs.lever.co/example/ai-1/apply",
                "workplaceType": "remote",
                "createdAt": 1774015783632,
                "lists": [],
            },
        ]
    )
    adapter = LeverJobSourceAdapter(site_names=["example"], http_session=fake_session)

    response = adapter.search(JobSearchQuery(query="ai engineer", page_size=10))

    assert [posting.title for posting in response.results] == ["Applied AI, Forward Deployed AI Engineer"]


def test_lever_adapter_keeps_machine_learning_family_narrower_than_generic_ai():
    fake_session = _FakeSession(
        [
            {
                "id": "ai-1",
                "text": "Applied AI, Forward Deployed AI Engineer",
                "categories": {
                    "commitment": "Employee: Full Time",
                    "location": "Remote",
                    "team": "Engineering",
                },
                "descriptionPlain": "Build and deploy AI systems.",
                "descriptionBodyPlain": "Build and deploy AI systems.",
                "additionalPlain": "",
                "hostedUrl": "https://jobs.lever.co/example/ai-1",
                "applyUrl": "https://jobs.lever.co/example/ai-1/apply",
                "workplaceType": "remote",
                "createdAt": 1774015783631,
                "lists": [],
            },
            {
                "id": "ml-1",
                "text": "Senior Machine Learning Engineer",
                "categories": {
                    "commitment": "Employee: Full Time",
                    "location": "Remote",
                    "team": "Engineering",
                },
                "descriptionPlain": "Build ML systems and model pipelines.",
                "descriptionBodyPlain": "Build ML systems and model pipelines.",
                "additionalPlain": "",
                "hostedUrl": "https://jobs.lever.co/example/ml-1",
                "applyUrl": "https://jobs.lever.co/example/ml-1/apply",
                "workplaceType": "remote",
                "createdAt": 1774015783632,
                "lists": [],
            },
        ]
    )
    adapter = LeverJobSourceAdapter(site_names=["example"], http_session=fake_session)

    response = adapter.search(JobSearchQuery(query="machine learning engineer", page_size=10))

    assert [posting.title for posting in response.results] == ["Senior Machine Learning Engineer"]
