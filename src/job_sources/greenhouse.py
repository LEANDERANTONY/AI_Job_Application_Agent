import html
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

from src.config import GREENHOUSE_BOARD_TOKENS
from src.job_sources.base import JobSourceAdapter
from src.job_sources.matching import (
    detect_role_families,
    extract_query_terms,
    location_matches_text,
    title_matches_role_families,
)
from src.schemas import JobPosting, JobResolutionResult, JobSearchQuery, JobSourceSearchResponse


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_GREENHOUSE_JOB_URL_RE = re.compile(
    r"^/([^/]+)/jobs/(\d+)",
    re.IGNORECASE,
)
_GENERIC_ROLE_TERMS = {
    "engineer",
    "engineering",
    "developer",
    "development",
    "software",
    "scientist",
    "analyst",
    "manager",
    "technical",
    "lead",
    "senior",
    "staff",
    "principal",
    "fullstack",
    "full",
    "stack",
}
_TECHNICAL_TITLE_PATTERNS = (
    re.compile(r"\bengineer\b"),
    re.compile(r"\bengineering\b"),
    re.compile(r"\bdeveloper\b"),
    re.compile(r"\bdevops\b"),
    re.compile(r"\bscientist\b"),
    re.compile(r"\banalyst\b"),
    re.compile(r"\barchitect\b"),
    re.compile(r"\bsre\b"),
    re.compile(r"\bqa\b"),
    re.compile(r"\bfront[\s-]?end\b"),
    re.compile(r"\bback[\s-]?end\b"),
    re.compile(r"\bfull[\s-]?stack\b"),
    re.compile(r"\bplatform\b"),
    re.compile(r"\bmachine learning\b"),
    re.compile(r"\bml\b"),
    re.compile(r"\bai\b"),
    re.compile(r"\bdata (?:engineer|engineering|scientist|science|analyst|analytics|architect)\b"),
)


def _repair_mojibake(text: str) -> str:
    value = str(text or "")
    replacements = {
        "\u00a0": " ",
        "â€™": "'",
        "â€˜": "'",
        "â€œ": '"',
        "â€": '"',
        "â€“": "-",
        "â€”": "-",
        "â€¦": "...",
        "â€¢": "-",
    }
    for source, target in replacements.items():
        value = value.replace(source, target)
    return value


def _normalize_text(value: str) -> str:
    text = str(value or "")
    for _ in range(3):
        next_text = html.unescape(text)
        if next_text == text:
            break
        text = next_text
    text = _repair_mojibake(text)
    text = _HTML_TAG_RE.sub(" ", text)
    text = text.replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _strip_html(value: str) -> str:
    return _normalize_text(value)


def _normalize_company_name(value: str, fallback: str) -> str:
    normalized = _normalize_text(value)
    if normalized:
        if normalized.islower():
            return normalized.title()
        return normalized
    return fallback.replace("-", " ").replace("_", " ").title()


def _normalize_metadata_lookup(metadata_payload) -> dict[str, str]:
    if isinstance(metadata_payload, dict):
        return {
            str(key).strip().lower(): str(value).strip()
            for key, value in metadata_payload.items()
            if str(key).strip() and value is not None
        }
    if isinstance(metadata_payload, list):
        lookup = {}
        for item in metadata_payload:
            if not isinstance(item, dict):
                continue
            key = str(item.get("name", "") or "").strip().lower()
            value = item.get("value")
            if key and value is not None:
                lookup[key] = str(value).strip()
        return lookup
    return {}
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


def _is_remote_job(job_posting: JobPosting) -> bool:
    haystack = " ".join(
        [
            job_posting.title,
            job_posting.location,
            job_posting.summary,
        ]
    ).lower()
    return "remote" in haystack


def _has_technical_title_signal(job_posting: JobPosting) -> bool:
    title = str(job_posting.title or "").lower()
    return any(pattern.search(title) for pattern in _TECHNICAL_TITLE_PATTERNS)


def _matches_query(job_posting: JobPosting, normalized_query: str, query_terms: list[str]) -> bool:
    title_haystack = " ".join(
        [
            job_posting.title,
            job_posting.company,
        ]
    ).lower()
    haystack = " ".join(
        [
            job_posting.title,
            job_posting.company,
            job_posting.location,
            job_posting.summary,
            job_posting.description_text,
        ]
    ).lower()
    if normalized_query and normalized_query in haystack:
        return True
    significant_terms = [term for term in query_terms if term not in _GENERIC_ROLE_TERMS]
    title_signal_terms = significant_terms or query_terms
    if query_terms and all(term in haystack for term in query_terms) and any(term in title_haystack for term in title_signal_terms):
        return True
    return not normalized_query


def _matches_location(job_posting: JobPosting, normalized_location: str, location_terms: list[str]) -> bool:
    haystack = " ".join(
        [
            job_posting.location,
            job_posting.summary,
            job_posting.description_text,
        ]
    ).lower()
    if location_matches_text(haystack, normalized_location):
        return True
    if location_terms and location_matches_text(haystack, " ".join(location_terms)):
        return True
    return not normalized_location


def _matches_posted_window(job_posting: JobPosting, posted_within_days: int | None) -> bool:
    if posted_within_days is None:
        return True
    posted_at = _parse_posted_at(job_posting.posted_at)
    if posted_at is None:
        return False
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - posted_at.astimezone(timezone.utc)
    return age.days <= max(0, int(posted_within_days))


def _job_sort_key(job_posting: JobPosting, normalized_query: str, query_terms: list[str]) -> tuple:
    title = str(job_posting.title or "").lower()
    summary = str(job_posting.summary or "").lower()
    posted_at = _parse_posted_at(job_posting.posted_at)
    posted_ts = posted_at.timestamp() if posted_at is not None else 0.0
    exact_phrase_in_title = int(bool(normalized_query and normalized_query in title))
    exact_phrase_anywhere = int(bool(normalized_query and (normalized_query in summary or normalized_query in title)))
    title_term_hits = sum(1 for term in query_terms if term in title)
    summary_term_hits = sum(1 for term in query_terms if term in summary)
    return (
        posted_ts,
        exact_phrase_in_title,
        exact_phrase_anywhere,
        title_term_hits,
        summary_term_hits,
    )


class GreenhouseJobSourceAdapter(JobSourceAdapter):
    source_name = "greenhouse"
    _API_BASE_URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"

    def __init__(self, board_tokens=None, http_session: requests.Session | None = None, timeout_seconds: int = 15):
        self._board_tokens = tuple(GREENHOUSE_BOARD_TOKENS if board_tokens is None else board_tokens)
        self._http_session = http_session or requests.Session()
        self._timeout_seconds = timeout_seconds

    def search(self, query: JobSearchQuery) -> JobSourceSearchResponse:
        if not self._board_tokens:
            return JobSourceSearchResponse(
                source=self.source_name,
                status="not_configured",
                error_message="No Greenhouse board tokens configured.",
                source_details={"greenhouse": "not_configured"},
            )

        normalized_query = str(query.query or "").strip().lower()
        normalized_location = str(query.location or "").strip().lower()
        query_terms = extract_query_terms(normalized_query)
        location_terms = extract_query_terms(normalized_location)
        role_families = detect_role_families(normalized_query)
        postings: list[JobPosting] = []
        board_statuses: dict[str, str] = {}

        for board_token in self._board_tokens:
            try:
                response = self._http_session.get(
                    self._API_BASE_URL.format(token=board_token),
                    params={"content": "true"},
                    timeout=self._timeout_seconds,
                )
                response.raise_for_status()
            except requests.RequestException as exc:
                board_statuses[board_token] = "error"
                continue

            payload = response.json()
            matched_any = False
            matched_results: list[JobPosting] = []
            for job_payload in payload.get("jobs", []) or []:
                job_posting = self._to_job_posting(board_token, job_payload)
                if not _has_technical_title_signal(job_posting):
                    continue
                if not title_matches_role_families(job_posting.title, role_families):
                    continue
                if not _matches_query(job_posting, normalized_query, query_terms):
                    continue
                if not _matches_location(job_posting, normalized_location, location_terms):
                    continue
                if query.remote_only and not _is_remote_job(job_posting):
                    continue
                if not _matches_posted_window(job_posting, query.posted_within_days):
                    continue
                matched_any = True
                matched_results.append(job_posting)
            if matched_any:
                postings.extend(matched_results)
                board_statuses[board_token] = "matched"
            elif payload.get("jobs"):
                board_statuses[board_token] = "no_match"
            else:
                board_statuses[board_token] = "empty"
        postings.sort(
            key=lambda posting: _job_sort_key(posting, normalized_query, query_terms),
            reverse=True,
        )
        postings = postings[: query.page_size]

        overall_status = "ok"
        if board_statuses and all(status == "error" for status in board_statuses.values()):
            overall_status = "error"
        return JobSourceSearchResponse(
            source=self.source_name,
            results=postings,
            status=overall_status,
            source_details=board_statuses,
        )

    def can_resolve_url(self, url: str) -> bool:
        parsed = urlparse(str(url or "").strip())
        if parsed.netloc.lower() not in {"boards.greenhouse.io", "job-boards.greenhouse.io"}:
            return False
        return bool(_GREENHOUSE_JOB_URL_RE.match(parsed.path or ""))

    def resolve_url(self, url: str) -> JobResolutionResult:
        parsed = urlparse(str(url or "").strip())
        match = _GREENHOUSE_JOB_URL_RE.match(parsed.path or "")
        if match is None:
            return JobResolutionResult(
                source=self.source_name,
                status="unsupported",
                error_message="URL is not a supported Greenhouse job URL.",
            )
        board_token, job_id = match.groups()
        try:
            response = self._http_session.get(
                self._API_BASE_URL.format(token=board_token) + "/{job_id}".format(job_id=job_id),
                params={"questions": "false"},
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            return JobResolutionResult(
                source=self.source_name,
                status="error",
                error_message=str(exc),
                source_details={board_token: "error"},
            )
        job_payload = response.json()
        return JobResolutionResult(
            source=self.source_name,
            status="ok",
            job_posting=self._to_job_posting(board_token, job_payload),
            source_details={board_token: "resolved"},
        )

    def _to_job_posting(self, board_token: str, job_payload: dict) -> JobPosting:
        location_payload = job_payload.get("location") or {}
        metadata_lookup = _normalize_metadata_lookup(job_payload.get("metadata"))
        company_name = _normalize_company_name(
            job_payload.get("company_name")
            or metadata_lookup.get("company_name")
            or metadata_lookup.get("company")
            or "",
            fallback=board_token,
        )
        normalized_title = _normalize_text(job_payload.get("title", ""))
        normalized_location = _normalize_text(location_payload.get("name", ""))
        normalized_url = str(job_payload.get("absolute_url", "")).strip()
        normalized_content = _strip_html(job_payload.get("content", ""))
        scraped_at = datetime.now(timezone.utc).isoformat()
        return JobPosting(
            id="greenhouse:{board}:{job_id}".format(
                board=board_token,
                job_id=job_payload.get("id"),
            ),
            source=self.source_name,
            title=normalized_title,
            company=company_name,
            location=normalized_location,
            employment_type=(
                metadata_lookup.get("employment_type")
                or metadata_lookup.get("time type")
                or metadata_lookup.get("employment type")
                or ""
            ).strip(),
            url=normalized_url,
            summary=normalized_content[:280],
            description_text=normalized_content,
            posted_at=str(job_payload.get("updated_at", "")).strip(),
            scraped_at=scraped_at,
            metadata={
                "board_token": board_token,
                "internal_job_id": job_payload.get("internal_job_id"),
                "requisition_id": job_payload.get("requisition_id"),
                "departments": [item.get("name", "") for item in job_payload.get("departments", []) or []],
                "offices": [item.get("name", "") for item in job_payload.get("offices", []) or []],
                "language": job_payload.get("language", ""),
            },
        )
