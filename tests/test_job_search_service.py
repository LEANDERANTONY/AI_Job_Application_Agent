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
