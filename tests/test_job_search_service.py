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


class _BulkSource(JobSourceAdapter):
    """Emits `count` deterministically-ordered postings (newest first by
    construction) so offset windows are stable across pages."""

    source_name = "greenhouse"

    def __init__(self, count: int):
        self._count = count

    def can_resolve_url(self, url: str) -> bool:
        return False

    def search(self, query):
        from src.schemas import JobPosting, JobSourceSearchResponse

        return JobSourceSearchResponse(
            source=self.source_name,
            status="ok",
            results=[
                JobPosting(
                    id=f"job-{i:03d}",
                    source=self.source_name,
                    title=f"Engineer {i:03d}",
                    company=f"Company {i:03d}",
                    url=f"https://example.com/jobs/{i}",
                    # Strictly-decreasing day → newest is i=0, so the
                    # post-sort order equals insertion order.
                    posted_at=f"2026-03-{(self._count - i):02d}T09:00:00+00:00",
                )
                for i in range(self._count)
            ],
        )

    def resolve_url(self, url: str):
        raise AssertionError("resolve should not run")


def test_live_search_first_page_signals_has_more_when_corpus_exceeds_page():
    service = JobSearchService(sources=[_BulkSource(25)])

    result = service.search(JobSearchQuery(query="engineer", page_size=10, offset=0))

    assert len(result.results) == 10
    assert [p.id for p in result.results] == [f"job-{i:03d}" for i in range(10)]
    assert result.has_more is True


def test_live_search_offset_windows_and_clears_has_more_on_last_page():
    service = JobSearchService(sources=[_BulkSource(25)])

    page2 = service.search(JobSearchQuery(query="engineer", page_size=10, offset=10))
    assert [p.id for p in page2.results] == [f"job-{i:03d}" for i in range(10, 20)]
    assert page2.has_more is True

    page3 = service.search(JobSearchQuery(query="engineer", page_size=10, offset=20))
    assert [p.id for p in page3.results] == [f"job-{i:03d}" for i in range(20, 25)]
    # 25 rows, window [20, 30) — nothing past it, so no "Load more".
    assert page3.has_more is False


def test_live_search_offset_past_end_returns_empty_and_no_more():
    service = JobSearchService(sources=[_BulkSource(5)])

    result = service.search(JobSearchQuery(query="engineer", page_size=10, offset=50))

    assert result.results == []
    assert result.has_more is False


class _FakeCacheStore:
    """Minimal CachedJobsStore stand-in: configured, and slices its
    canned rows by the offset/limit the service passes — exactly what
    the real search_cached_jobs_ranked RPC does server-side."""

    def __init__(self, row_count: int):
        self._rows = [
            {
                "job_id": f"c{i:03d}",
                "source": "greenhouse",
                "title": f"Cached {i:03d}",
                "company": "Acme",
                "url": f"https://cache.example.com/{i}",
                "posted_at": f"2026-03-{((i % 27) + 1):02d}T09:00:00+00:00",
            }
            for i in range(row_count)
        ]
        self.calls: list[dict] = []

    def is_configured(self) -> bool:
        return True

    def search(
        self,
        *,
        query,
        location,
        sources,
        remote_only,
        posted_within_days,
        limit,
        offset,
    ):
        self.calls.append({"limit": limit, "offset": offset})
        return self._rows[offset : offset + limit]


def test_cached_search_threads_offset_and_sets_has_more():
    store = _FakeCacheStore(row_count=25)
    service = JobSearchService(sources=[], cache_store=store)

    page1 = service.search_cached(
        JobSearchQuery(query="engineer", page_size=10, offset=0)
    )
    assert len(page1.results) == 10
    assert page1.results[0].id == "c000"
    assert page1.has_more is True
    assert page1.source_status["cache"] == "ok"

    last = service.search_cached(
        JobSearchQuery(query="engineer", page_size=10, offset=20)
    )
    assert [p.id for p in last.results] == [f"c{i:03d}" for i in range(20, 25)]
    # Partial final page (5 < page_size) → no more pages.
    assert last.has_more is False

    # The offset must reach the store unmodified (it's the RPC's
    # p_offset); page_size is the RPC limit.
    assert store.calls == [
        {"limit": 10, "offset": 0},
        {"limit": 10, "offset": 20},
    ]


def test_cached_search_full_final_page_still_reports_has_more():
    # Exactly page_size rows back → has_more stays True (the backend
    # has no cheap COUNT; "full page" is the pragmatic signal and the
    # next fetch returning 0 is what finally clears the CTA).
    store = _FakeCacheStore(row_count=10)
    service = JobSearchService(sources=[], cache_store=store)

    result = service.search_cached(
        JobSearchQuery(query="engineer", page_size=10, offset=0)
    )

    assert len(result.results) == 10
    assert result.has_more is True
