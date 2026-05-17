from datetime import datetime, timezone

from src.cached_jobs_store import CachedJobsStore
from src.job_sources.registry import build_default_job_sources
from src.schemas import JobPosting, JobResolutionResult, JobSearchQuery, JobSearchResult


def _row_to_job_posting(row: dict) -> JobPosting:
    """Convert a cached_jobs row dict (as returned by Supabase) into a
    JobPosting dataclass so the response model is unchanged.

    Column-to-attr remap: cached_jobs.job_id → JobPosting.id,
    cached_jobs.description → JobPosting.description_text. Everything
    else passes through 1:1.
    """
    posted_at_value = row.get("posted_at") or ""
    return JobPosting(
        id=str(row.get("job_id", "") or ""),
        source=str(row.get("source", "") or ""),
        title=str(row.get("title", "") or ""),
        company=str(row.get("company", "") or ""),
        location=str(row.get("location", "") or ""),
        employment_type=str(row.get("employment_type", "") or ""),
        url=str(row.get("url", "") or ""),
        summary=str(row.get("summary", "") or ""),
        description_text=str(row.get("description", "") or ""),
        posted_at=str(posted_at_value or ""),
        scraped_at=str(row.get("last_seen_at", "") or ""),
        metadata=row.get("metadata") if isinstance(row.get("metadata"), dict) else {},
    )


def _dedupe_key(posting) -> str:
    normalized_url = str(getattr(posting, "url", "") or "").strip().lower()
    if normalized_url:
        return f"url:{normalized_url}"

    source = str(getattr(posting, "source", "") or "").strip().lower()
    posting_id = str(getattr(posting, "id", "") or "").strip().lower()
    if source and posting_id:
        return f"id:{source}:{posting_id}"

    title = str(getattr(posting, "title", "") or "").strip().lower()
    company = str(getattr(posting, "company", "") or "").strip().lower()
    location = str(getattr(posting, "location", "") or "").strip().lower()
    return f"title:{title}|company:{company}|location:{location}"


def _parse_posted_at(value: str):
    raw_value = str(value or "").strip()
    if not raw_value:
        return None
    try:
        if raw_value.endswith("Z"):
            raw_value = raw_value[:-1] + "+00:00"
        return datetime.fromisoformat(raw_value)
    except ValueError:
        return None


def _posted_timestamp(value: str) -> float:
    parsed = _parse_posted_at(value)
    if parsed is None:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


class JobSearchService:
    """Initial backend boundary for provider-backed job search."""

    def __init__(self, sources=None, cache_store: CachedJobsStore | None = None):
        self._sources = list(sources or build_default_job_sources())
        # Constructed lazily so unconfigured deployments (no service-role
        # key) don't blow up at import time — only when search_cached
        # is actually invoked. Tests can inject a fake store directly.
        self._cache_store = cache_store

    def _get_cache_store(self) -> CachedJobsStore:
        if self._cache_store is None:
            self._cache_store = CachedJobsStore()
        return self._cache_store

    def search_cached(self, query: JobSearchQuery) -> JobSearchResult:
        """Cache-backed search. Default path for /jobs/search.

        Hits the cached_jobs Supabase table via Postgres FTS instead of
        fanning out to every Greenhouse / Lever board. ~30ms vs ~1-3s
        for the live path. Stays compatible with the existing
        JobSearchResult shape so the response model is unchanged.

        Falls back to the live path automatically when the cache is
        unconfigured (no SUPABASE_SERVICE_ROLE_KEY) — keeps local-dev
        environments working without forcing every developer to wire
        up the service role key.
        """
        normalized_query = JobSearchQuery(
            query=str(query.query or "").strip(),
            location=str(query.location or "").strip(),
            source_filters=list(query.source_filters or []),
            remote_only=bool(query.remote_only),
            posted_within_days=query.posted_within_days,
            page_size=max(1, min(int(query.page_size or 20), 50)),
            offset=max(0, int(query.offset or 0)),
        )

        store = self._get_cache_store()
        if not store.is_configured():
            # Graceful degradation — local dev or staging without the
            # service-role key falls back to the live fan-out so the
            # endpoint still returns results.
            result = self.search(normalized_query)
            result.source_status["cache"] = "not_configured"
            return result

        try:
            rows = store.search(
                query=normalized_query.query,
                location=normalized_query.location,
                sources=list(normalized_query.source_filters) or None,
                remote_only=normalized_query.remote_only,
                posted_within_days=normalized_query.posted_within_days,
                limit=normalized_query.page_size,
                offset=normalized_query.offset,
            )
        except Exception as exc:  # noqa: BLE001 — cache outage shouldn't kill search
            # Fall through to the live path. The cache is a perf
            # optimisation, not a correctness boundary.
            result = self.search(normalized_query)
            result.source_status["cache"] = f"error: {type(exc).__name__}"
            return result

        postings = [_row_to_job_posting(row) for row in rows]
        # A full page back → there is (probably) at least one more page.
        # The RPC has no cheap COUNT(*), so "page came back full" is the
        # pragmatic has_more signal that powers the frontend "Load more".
        has_more = len(postings) == normalized_query.page_size
        return JobSearchResult(
            query=normalized_query,
            results=postings,
            total_results=len(postings),
            has_more=has_more,
            source_status={"cache": "ok", "backend": "ready"},
        )

    def search(self, query: JobSearchQuery) -> JobSearchResult:
        normalized_query = JobSearchQuery(
            query=str(query.query or "").strip(),
            location=str(query.location or "").strip(),
            source_filters=list(query.source_filters or []),
            remote_only=bool(query.remote_only),
            posted_within_days=query.posted_within_days,
            page_size=max(1, min(int(query.page_size or 20), 50)),
            offset=max(0, int(query.offset or 0)),
        )
        requested_sources = {
            str(item).strip().lower()
            for item in normalized_query.source_filters
            if str(item).strip()
        }
        active_sources = [
            source for source in self._sources
            if not requested_sources or source.source_name.lower() in requested_sources
        ]
        results = []
        source_status = {"backend": "ready"}
        for source in active_sources:
            response = source.search(normalized_query)
            source_status[source.source_name] = response.status
            source_status.update(response.source_details)
            results.extend(response.results)
        results.sort(key=lambda posting: _posted_timestamp(getattr(posting, "posted_at", "")), reverse=True)
        deduped_results = []
        seen_keys = set()
        for posting in results:
            key = _dedupe_key(posting)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            deduped_results.append(posting)
        # The live fan-out has the full deduped set in memory, so it can
        # paginate exactly: slice [offset, offset+page_size) and report
        # has_more from whether anything survives past the window.
        offset = normalized_query.offset
        page_size = normalized_query.page_size
        results = deduped_results[offset : offset + page_size]
        has_more = len(deduped_results) > offset + page_size
        return JobSearchResult(
            query=normalized_query,
            results=results,
            total_results=len(results),
            has_more=has_more,
            source_status=source_status,
        )

    def resolve_url(self, url: str) -> JobResolutionResult:
        normalized_url = str(url or "").strip()
        for source in self._sources:
            if source.can_resolve_url(normalized_url):
                return source.resolve_url(normalized_url)
        return JobResolutionResult(
            source="unknown",
            status="unsupported",
            error_message="No configured provider can resolve that job URL.",
        )


def get_job_search_service() -> JobSearchService:
    return JobSearchService()
