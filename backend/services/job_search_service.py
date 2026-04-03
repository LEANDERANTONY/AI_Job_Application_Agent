from datetime import datetime, timezone

from src.job_sources.registry import build_default_job_sources
from src.schemas import JobResolutionResult, JobSearchQuery, JobSearchResult


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

    def __init__(self, sources=None):
        self._sources = list(sources or build_default_job_sources())

    def search(self, query: JobSearchQuery) -> JobSearchResult:
        normalized_query = JobSearchQuery(
            query=str(query.query or "").strip(),
            location=str(query.location or "").strip(),
            source_filters=list(query.source_filters or []),
            remote_only=bool(query.remote_only),
            posted_within_days=query.posted_within_days,
            page_size=max(1, min(int(query.page_size or 20), 50)),
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
        results = deduped_results[: normalized_query.page_size]
        return JobSearchResult(
            query=normalized_query,
            results=results,
            total_results=len(results),
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
