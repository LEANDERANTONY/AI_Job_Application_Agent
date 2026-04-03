from pathlib import Path

from backend.services.job_search_service import JobSearchService
from src.job_sources.base import JobSourceAdapter
from src.job_sources.demo import DemoJobSourceAdapter
from src.schemas import JobResolutionResult, JobSearchQuery


def test_job_search_service_returns_demo_job_results_for_matching_query(tmp_path: Path):
    demo_dir = tmp_path / "demo_jobs"
    demo_dir.mkdir()
    (demo_dir / "ml_engineer.txt").write_text(
        "Machine Learning Engineer\n"
        "Location: Bengaluru, India\n"
        "Required: Python, SQL, Docker.\n",
        encoding="utf-8",
    )

    service = JobSearchService(sources=[DemoJobSourceAdapter(base_dir=demo_dir)])

    result = service.search(
        JobSearchQuery(query="machine learning engineer", location="Bengaluru", page_size=10)
    )

    assert result.total_results == 1
    assert result.results[0].title == "Machine Learning Engineer"
    assert result.results[0].source == "demo"
    assert result.source_status["demo"] == "ok"


def test_job_search_service_filters_to_requested_sources(tmp_path: Path):
    demo_dir = tmp_path / "demo_jobs"
    demo_dir.mkdir()
    (demo_dir / "data_scientist.txt").write_text(
        "Data Scientist\n"
        "Location: Chennai, India\n"
        "Required: Python, SQL.\n",
        encoding="utf-8",
    )

    service = JobSearchService(sources=[DemoJobSourceAdapter(base_dir=demo_dir)])

    result = service.search(
        JobSearchQuery(query="data scientist", source_filters=["other_source"], page_size=10)
    )

    assert result.total_results == 0
    assert result.source_status == {"backend": "ready"}


def test_job_search_service_resolves_url_with_first_matching_source():
    class FakeSource(JobSourceAdapter):
        source_name = "fake"

        def can_resolve_url(self, url: str) -> bool:
            return "greenhouse" in url

        def search(self, query):
            raise AssertionError("search should not run")

        def resolve_url(self, url: str):
            return JobResolutionResult(
                source=self.source_name,
                status="ok",
            )

    service = JobSearchService(sources=[FakeSource()])

    result = service.resolve_url("https://boards.greenhouse.io/example/jobs/123")

    assert result.source == "fake"
    assert result.status == "ok"


def test_job_search_service_sorts_results_recent_first_across_sources():
    class FakeSource(JobSourceAdapter):
        def __init__(self, source_name, posting):
            self.source_name = source_name
            self._posting = posting

        def can_resolve_url(self, url: str) -> bool:
            return False

        def search(self, query):
            from src.schemas import JobPosting, JobSourceSearchResponse

            return JobSourceSearchResponse(
                source=self.source_name,
                status="ok",
                results=[
                    JobPosting(
                        id=f"{self.source_name}:1",
                        source=self.source_name,
                        title=self._posting["title"],
                        company=self._posting["company"],
                        posted_at=self._posting["posted_at"],
                    )
                ],
                source_details={self.source_name: "matched"},
            )

        def resolve_url(self, url: str):
            raise AssertionError("resolve should not run")

    service = JobSearchService(
        sources=[
            FakeSource(
                "greenhouse",
                {"title": "Older Role", "company": "Alpha", "posted_at": "2026-03-18T09:00:00+00:00"},
            ),
            FakeSource(
                "lever",
                {"title": "Newer Role", "company": "Beta", "posted_at": "2026-03-20T09:00:00+00:00"},
            ),
        ]
    )

    result = service.search(JobSearchQuery(query="engineer", page_size=10))

    assert [posting.title for posting in result.results] == ["Newer Role", "Older Role"]


def test_job_search_service_dedupes_same_url_across_sources():
    class FakeSource(JobSourceAdapter):
        def __init__(self, source_name, posting):
            self.source_name = source_name
            self._posting = posting

        def can_resolve_url(self, url: str) -> bool:
            return False

        def search(self, query):
            from src.schemas import JobPosting, JobSourceSearchResponse

            return JobSourceSearchResponse(
                source=self.source_name,
                status="ok",
                results=[
                    JobPosting(
                        id=f"{self.source_name}:1",
                        source=self.source_name,
                        title=self._posting["title"],
                        company=self._posting["company"],
                        location=self._posting["location"],
                        url=self._posting["url"],
                        posted_at=self._posting["posted_at"],
                    )
                ],
                source_details={self.source_name: "matched"},
            )

        def resolve_url(self, url: str):
            raise AssertionError("resolve should not run")

    shared_url = "https://example.com/jobs/shared-role"
    service = JobSearchService(
        sources=[
            FakeSource(
                "greenhouse",
                {
                    "title": "Backend Engineer",
                    "company": "Example",
                    "location": "Remote",
                    "url": shared_url,
                    "posted_at": "2026-03-18T09:00:00+00:00",
                },
            ),
            FakeSource(
                "lever",
                {
                    "title": "Backend Engineer",
                    "company": "Example",
                    "location": "Remote",
                    "url": shared_url,
                    "posted_at": "2026-03-20T09:00:00+00:00",
                },
            ),
        ]
    )

    result = service.search(JobSearchQuery(query="backend engineer", page_size=10))

    assert len(result.results) == 1
    assert result.results[0].source == "lever"
