"""Tests for backend/services/job_cache_service.refresh_cached_jobs.

Uses fake adapters + a fake CachedJobsStore so we can drive the
refresh report shape and the per-source cleanup gating without
touching Supabase or Greenhouse/Lever's real APIs.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.services.job_cache_service import refresh_cached_jobs


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeAdapter:
    """Yields the (board_token, status, payload) sequence we configure."""

    def __init__(self, fetches):
        self._fetches = fetches

    def fetch_all_postings(self):
        for fetch in self._fetches:
            yield fetch


class _FakeStore:
    """Records upsert calls + cleanup invocations. Mirrors the part of
    CachedJobsStore that refresh_cached_jobs actually uses."""

    def __init__(self, *, raise_on_upsert: Exception | None = None):
        self.upsert_calls = []
        self.cleanup_calls = []
        self.raise_on_upsert = raise_on_upsert
        self.active_count = 100

    def is_configured(self):
        return True

    def upsert_postings(self, source, postings):
        if self.raise_on_upsert:
            raise self.raise_on_upsert
        rows = list(postings)
        self.upsert_calls.append((source, len(rows)))
        return len(rows)

    def cleanup_missing(self, *, sources_refreshed, cutoff_iso):
        self.cleanup_calls.append((tuple(sources_refreshed), cutoff_iso))
        # Returns (tombstoned, deleted)
        return (3, 7)

    def count_active(self):
        return self.active_count


def _posting(job_id, title="Senior Engineer", company="Acme"):
    return SimpleNamespace(
        id=job_id,
        source="greenhouse",
        title=title,
        company=company,
        location="",
        employment_type="",
        url=f"https://example.com/{job_id}",
        summary="",
        description_text="",
        posted_at="",
        scraped_at="",
        metadata={},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_refresh_collects_postings_and_runs_cleanup():
    """Happy path: two providers, both succeed → upsert per-source +
    one cleanup pass that targets both providers."""
    gh_adapter = _FakeAdapter(
        fetches=[
            ("stripe", "ok", [_posting("gh-1"), _posting("gh-2")]),
            ("anthropic", "empty", []),
        ]
    )
    lever_adapter = _FakeAdapter(
        fetches=[("shopify", "ok", [_posting("lv-1")])]
    )
    store = _FakeStore()

    report = refresh_cached_jobs(
        store=store,
        adapters=[("greenhouse", gh_adapter), ("lever", lever_adapter)],
    )

    # Upserts happened per-source.
    assert ("greenhouse", 2) in store.upsert_calls
    assert ("lever", 1) in store.upsert_calls
    # One cleanup pass; both providers eligible (boards_succeeded > 0).
    assert len(store.cleanup_calls) == 1
    sources_refreshed, _cutoff = store.cleanup_calls[0]
    assert set(sources_refreshed) == {"greenhouse", "lever"}
    # Report shape.
    assert report["providers"]["greenhouse"]["boards_succeeded"] == 2  # ok + empty
    assert report["providers"]["greenhouse"]["postings_upserted"] == 2
    assert report["providers"]["lever"]["boards_succeeded"] == 1
    assert report["providers"]["lever"]["postings_upserted"] == 1
    # Cleanup totals folded into per-provider report.
    assert report["providers"]["greenhouse"]["tombstoned"] == 1  # 3 // 2
    assert report["providers"]["greenhouse"]["deleted"] == 3  # 7 // 2
    assert report["total_active_after"] == 100


def test_refresh_skips_cleanup_for_provider_with_all_boards_failed():
    """If EVERY board for a provider errors, that provider is excluded
    from cleanup — protects the cache during a short-term provider
    outage. Other providers still get their cleanup run."""
    gh_adapter = _FakeAdapter(
        fetches=[
            ("stripe", "error", "Connection timeout"),
            ("anthropic", "error", "503"),
        ]
    )
    lever_adapter = _FakeAdapter(
        fetches=[("shopify", "ok", [_posting("lv-1")])]
    )
    store = _FakeStore()

    report = refresh_cached_jobs(
        store=store,
        adapters=[("greenhouse", gh_adapter), ("lever", lever_adapter)],
    )

    # Only lever in the cleanup eligibility list.
    assert len(store.cleanup_calls) == 1
    sources_refreshed, _cutoff = store.cleanup_calls[0]
    assert sources_refreshed == ("lever",)
    # Greenhouse report still surfaces the failures even though no
    # cleanup ran for it.
    assert report["providers"]["greenhouse"]["boards_failed"] == 2
    assert report["providers"]["greenhouse"]["boards_succeeded"] == 0
    assert len(report["providers"]["greenhouse"]["errors"]) == 2


def test_refresh_status_partial_when_some_boards_fail():
    """Mixed success: a provider with 1 ok + 1 failed board is
    'partial' status, eligible for cleanup."""
    gh_adapter = _FakeAdapter(
        fetches=[
            ("stripe", "ok", [_posting("gh-1")]),
            ("anthropic", "error", "rate limited"),
        ]
    )
    store = _FakeStore()

    report = refresh_cached_jobs(
        store=store, adapters=[("greenhouse", gh_adapter)]
    )

    assert report["providers"]["greenhouse"]["status"] == "partial"
    assert report["providers"]["greenhouse"]["boards_succeeded"] == 1
    assert report["providers"]["greenhouse"]["boards_failed"] == 1
    # Cleanup still ran (boards_succeeded > 0).
    assert len(store.cleanup_calls) == 1


def test_refresh_continues_on_per_chunk_upsert_failure():
    """An upsert failure for one chunk doesn't kill the run — the
    error is captured in the report and the rest of the providers
    still get processed."""
    gh_adapter = _FakeAdapter(
        fetches=[("stripe", "ok", [_posting("gh-1")])]
    )
    store = _FakeStore(raise_on_upsert=RuntimeError("supabase 500"))

    report = refresh_cached_jobs(
        store=store, adapters=[("greenhouse", gh_adapter)]
    )

    # Upsert failed → status partial, error recorded.
    assert report["providers"]["greenhouse"]["status"] == "partial"
    assert report["providers"]["greenhouse"]["postings_upserted"] == 0
    assert any(
        "supabase 500" in err["message"]
        for err in report["providers"]["greenhouse"]["errors"]
    )
    # boards_succeeded > 0 so cleanup still ran.
    assert len(store.cleanup_calls) == 1


def test_refresh_raises_when_store_unconfigured():
    """No service-role key → fail fast with a clear message rather
    than silently no-op."""

    class _UnconfiguredStore:
        def is_configured(self):
            return False

    with pytest.raises(RuntimeError, match="not configured"):
        refresh_cached_jobs(store=_UnconfiguredStore(), adapters=[])


# ---------------------------------------------------------------------------
# Cutover tests: JobSearchService.search_cached delegates to the store and
# wraps rows back into JobPosting objects so the response model is unchanged.
# ---------------------------------------------------------------------------


def test_search_cached_returns_jobpostings_from_cache_rows():
    """search_cached() reads rows from a fake CachedJobsStore and
    converts them into JobPosting objects with the right column-to-attr
    remapping (job_id → id, description → description_text)."""
    from backend.services.job_search_service import JobSearchService
    from src.schemas import JobSearchQuery

    class _FakeCacheStore:
        def __init__(self):
            self.search_calls = []

        def is_configured(self):
            return True

        def search(self, **kwargs):
            self.search_calls.append(kwargs)
            return [
                {
                    "job_id": "gh-123",
                    "source": "greenhouse",
                    "title": "Senior ML Engineer",
                    "company": "Stripe",
                    "location": "San Francisco",
                    "url": "https://example.com/123",
                    "summary": "",
                    "description": "<p>Long HTML</p>",
                    "posted_at": "2026-04-01T00:00:00+00:00",
                    "last_seen_at": "2026-05-07T18:00:00+00:00",
                    "metadata": {"departments": ["Engineering"]},
                },
            ]

    store = _FakeCacheStore()
    service = JobSearchService(sources=[], cache_store=store)
    result = service.search_cached(
        JobSearchQuery(query="machine learning", page_size=20)
    )

    # Forwarded the search kwargs through to the store.
    assert len(store.search_calls) == 1
    call = store.search_calls[0]
    assert call["query"] == "machine learning"
    # Result wrapped into JobPosting objects with the column remap.
    assert result.total_results == 1
    assert result.results[0].id == "gh-123"  # job_id → id
    assert result.results[0].source == "greenhouse"
    assert result.results[0].description_text == "<p>Long HTML</p>"  # description → description_text
    assert result.source_status == {"cache": "ok", "backend": "ready"}


def test_search_cached_falls_back_to_live_when_cache_unconfigured():
    """No service-role key → search_cached() transparently falls back
    to the live fan-out path so local-dev environments still work."""
    from backend.services.job_search_service import JobSearchService
    from src.schemas import JobPosting, JobSearchQuery, JobSourceSearchResponse

    class _UnconfiguredCacheStore:
        def is_configured(self):
            return False

    class _FakeSource:
        source_name = "fake"

        def search(self, query):
            return JobSourceSearchResponse(
                source="fake",
                results=[
                    JobPosting(id="x", source="fake", title="Live Job", company="Live Co"),
                ],
                status="ok",
                source_details={},
            )

    service = JobSearchService(sources=[_FakeSource()], cache_store=_UnconfiguredCacheStore())
    result = service.search_cached(JobSearchQuery(query="anything", page_size=20))

    # Live path returned the result.
    assert result.total_results == 1
    assert result.results[0].title == "Live Job"
    # Source status flags the cache miss explicitly.
    assert result.source_status["cache"] == "not_configured"


def test_search_cached_falls_back_to_live_when_cache_errors():
    """Cache outage → fall back to live, surface 'cache: error: ...'
    in source_status so the client / monitoring can see what happened
    without losing the user-visible result."""
    from backend.services.job_search_service import JobSearchService
    from src.schemas import JobPosting, JobSearchQuery, JobSourceSearchResponse

    class _ErroringCacheStore:
        def is_configured(self):
            return True

        def search(self, **kwargs):
            raise RuntimeError("supabase connection refused")

    class _FakeSource:
        source_name = "fake"

        def search(self, query):
            return JobSourceSearchResponse(
                source="fake",
                results=[JobPosting(id="x", source="fake", title="Live Fallback", company="Co")],
                status="ok",
                source_details={},
            )

    service = JobSearchService(
        sources=[_FakeSource()],
        cache_store=_ErroringCacheStore(),
    )
    result = service.search_cached(JobSearchQuery(query="anything", page_size=20))

    assert result.total_results == 1
    assert result.results[0].title == "Live Fallback"
    assert result.source_status["cache"].startswith("error: RuntimeError")
