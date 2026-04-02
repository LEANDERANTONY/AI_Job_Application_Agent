import html
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

from src.config import LEVER_SITE_NAMES
from src.job_sources.base import JobSourceAdapter
from src.job_sources.matching import detect_role_families, extract_query_terms, title_matches_role_families
from src.schemas import JobPosting, JobResolutionResult, JobSearchQuery, JobSourceSearchResponse


_HTML_TAG_RE = re.compile(r"<[^>]+>")
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


def _normalize_text(value: str) -> str:
    text = str(value or "")
    for _ in range(3):
        next_text = html.unescape(text)
        if next_text == text:
            break
        text = next_text
    text = _HTML_TAG_RE.sub(" ", text)
    text = text.replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()
def _parse_created_at(value):
    if value in {None, ""}:
        return None
    try:
        timestamp_ms = int(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(timestamp_ms / 1000.0, tz=timezone.utc)


def _format_created_at(value) -> str:
    parsed = _parse_created_at(value)
    return parsed.isoformat() if parsed is not None else ""


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
    if normalized_location and normalized_location in haystack:
        return True
    if location_terms and all(term in haystack for term in location_terms):
        return True
    return not normalized_location


def _matches_posted_window(job_posting: JobPosting, posted_within_days: int | None) -> bool:
    if posted_within_days is None:
        return True
    parsed_posted_at = None
    raw_posted_at = str(job_posting.posted_at or "").strip()
    if raw_posted_at:
        try:
            if raw_posted_at.endswith("Z"):
                raw_posted_at = raw_posted_at[:-1] + "+00:00"
            parsed_posted_at = datetime.fromisoformat(raw_posted_at)
        except ValueError:
            parsed_posted_at = None
    if parsed_posted_at is None:
        return False
    if parsed_posted_at.tzinfo is None:
        parsed_posted_at = parsed_posted_at.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - parsed_posted_at.astimezone(timezone.utc)
    return age.days <= max(0, int(posted_within_days))


def _job_sort_key(job_posting: JobPosting, normalized_query: str, query_terms: list[str]) -> tuple:
    title = str(job_posting.title or "").lower()
    summary = str(job_posting.summary or "").lower()
    raw_posted_at = str(job_posting.posted_at or "").strip()
    posted_ts = 0.0
    if raw_posted_at:
        try:
            normalized = raw_posted_at[:-1] + "+00:00" if raw_posted_at.endswith("Z") else raw_posted_at
            posted_ts = datetime.fromisoformat(normalized).timestamp()
        except ValueError:
            posted_ts = 0.0
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


def _strip_html(value: str) -> str:
    return _normalize_text(value)


def _build_description_text(job_payload: dict) -> str:
    parts = []
    opening = _normalize_text(job_payload.get("openingPlain", ""))
    description = _normalize_text(job_payload.get("descriptionBodyPlain", "") or job_payload.get("descriptionPlain", ""))
    if opening:
        parts.append(opening)
    if description and description not in parts:
        parts.append(description)

    for list_payload in job_payload.get("lists", []) or []:
        if not isinstance(list_payload, dict):
            continue
        heading = _normalize_text(list_payload.get("text", ""))
        content = _strip_html(list_payload.get("content", ""))
        if heading and content:
            parts.append(f"{heading}: {content}")
        elif content:
            parts.append(content)

    additional = _normalize_text(job_payload.get("additionalPlain", ""))
    if additional:
        parts.append(additional)

    return "\n\n".join(part for part in parts if part).strip()


def _salary_text(job_payload: dict) -> str:
    salary_range = job_payload.get("salaryRange") or {}
    if not isinstance(salary_range, dict):
        salary_range = {}
    min_value = salary_range.get("min")
    max_value = salary_range.get("max")
    currency = str(salary_range.get("currency", "") or "").strip()
    interval = str(salary_range.get("interval", "") or "").strip().replace("-", " ")
    if min_value is None and max_value is None:
        return _normalize_text(job_payload.get("salaryDescriptionPlain", ""))
    parts = []
    if min_value is not None:
        parts.append(f"{int(min_value):,}")
    if max_value is not None:
        parts.append(f"{int(max_value):,}")
    if len(parts) == 2:
        amount = f"{parts[0]} - {parts[1]}"
    else:
        amount = parts[0]
    prefix = f"{currency} " if currency else ""
    suffix = f" {interval}" if interval else ""
    extra = _normalize_text(job_payload.get("salaryDescriptionPlain", ""))
    if extra:
        return f"{prefix}{amount}{suffix} | {extra}".strip()
    return f"{prefix}{amount}{suffix}".strip()


class LeverJobSourceAdapter(JobSourceAdapter):
    source_name = "lever"

    def __init__(self, site_names=None, http_session: requests.Session | None = None, timeout_seconds: int = 15):
        self._site_names = tuple(LEVER_SITE_NAMES if site_names is None else site_names)
        self._http_session = http_session or requests.Session()
        self._timeout_seconds = timeout_seconds

    def _list_url(self, site_name: str) -> str:
        return f"https://api.lever.co/v0/postings/{site_name}"

    def _detail_url(self, site_name: str, posting_id: str, *, eu: bool = False) -> str:
        base = "https://api.eu.lever.co/v0/postings" if eu else "https://api.lever.co/v0/postings"
        return f"{base}/{site_name}/{posting_id}"

    def can_resolve_url(self, url: str) -> bool:
        parsed = urlparse(str(url or "").strip())
        if parsed.netloc.lower() not in {"jobs.lever.co", "jobs.eu.lever.co"}:
            return False
        parts = [part for part in (parsed.path or "").split("/") if part]
        return len(parts) >= 2

    def search(self, query: JobSearchQuery) -> JobSourceSearchResponse:
        if not self._site_names:
            return JobSourceSearchResponse(
                source=self.source_name,
                status="not_configured",
                error_message="No Lever site names configured.",
                source_details={"lever": "not_configured"},
            )

        normalized_query = str(query.query or "").strip().lower()
        normalized_location = str(query.location or "").strip().lower()
        query_terms = extract_query_terms(normalized_query)
        location_terms = extract_query_terms(normalized_location)
        role_families = detect_role_families(normalized_query)
        postings: list[JobPosting] = []
        site_statuses: dict[str, str] = {}

        for site_name in self._site_names:
            try:
                response = self._http_session.get(
                    self._list_url(site_name),
                    params={"mode": "json", "limit": 100},
                    timeout=self._timeout_seconds,
                )
                response.raise_for_status()
            except requests.RequestException:
                site_statuses[site_name] = "error"
                continue

            payload = response.json()
            matched_results: list[JobPosting] = []
            for job_payload in payload or []:
                job_posting = self._to_job_posting(site_name, job_payload)
                if not _has_technical_title_signal(job_posting):
                    continue
                if not title_matches_role_families(job_posting.title, role_families):
                    continue
                if not _matches_query(job_posting, normalized_query, query_terms):
                    continue
                if not _matches_location(job_posting, normalized_location, location_terms):
                    continue
                if query.remote_only and "remote" not in " ".join(
                    [job_posting.location, str(job_posting.metadata.get("workplace_type", ""))]
                ).lower():
                    continue
                if not _matches_posted_window(job_posting, query.posted_within_days):
                    continue
                matched_results.append(job_posting)
            if matched_results:
                postings.extend(matched_results)
                site_statuses[site_name] = "matched"
            elif payload:
                site_statuses[site_name] = "no_match"
            else:
                site_statuses[site_name] = "empty"

        postings.sort(
            key=lambda posting: _job_sort_key(posting, normalized_query, query_terms),
            reverse=True,
        )
        postings = postings[: query.page_size]
        overall_status = "ok"
        if site_statuses and all(status == "error" for status in site_statuses.values()):
            overall_status = "error"
        return JobSourceSearchResponse(
            source=self.source_name,
            results=postings,
            status=overall_status,
            source_details=site_statuses,
        )

    def resolve_url(self, url: str) -> JobResolutionResult:
        parsed = urlparse(str(url or "").strip())
        parts = [part for part in (parsed.path or "").split("/") if part]
        if len(parts) < 2:
            return JobResolutionResult(
                source=self.source_name,
                status="unsupported",
                error_message="URL is not a supported Lever job URL.",
            )
        site_name, posting_id = parts[0], parts[1]
        is_eu = parsed.netloc.lower() == "jobs.eu.lever.co"
        try:
            response = self._http_session.get(
                self._detail_url(site_name, posting_id, eu=is_eu),
                params={"mode": "json"},
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            return JobResolutionResult(
                source=self.source_name,
                status="error",
                error_message=str(exc),
                source_details={site_name: "error"},
            )
        return JobResolutionResult(
            source=self.source_name,
            status="ok",
            job_posting=self._to_job_posting(site_name, response.json()),
            source_details={site_name: "resolved"},
        )

    def _to_job_posting(self, site_name: str, job_payload: dict) -> JobPosting:
        categories = job_payload.get("categories") or {}
        description_text = _build_description_text(job_payload)
        salary_text = _salary_text(job_payload)
        if salary_text and salary_text not in description_text:
            description_text = f"{description_text}\n\nCompensation: {salary_text}".strip()
        company_name = site_name.replace("-", " ").replace("_", " ").title()
        location = _normalize_text(categories.get("location", ""))
        workplace_type = _normalize_text(job_payload.get("workplaceType", ""))
        if workplace_type and workplace_type not in location.lower():
            location = f"{location} | {workplace_type.title()}".strip(" |")
        return JobPosting(
            id=f"lever:{site_name}:{job_payload.get('id')}",
            source=self.source_name,
            title=_normalize_text(job_payload.get("text", "")),
            company=company_name,
            location=location,
            employment_type=_normalize_text(categories.get("commitment", "")),
            url=str(job_payload.get("hostedUrl", "") or "").strip(),
            summary=_normalize_text(job_payload.get("descriptionPlain", ""))[:280],
            description_text=description_text,
            posted_at=_format_created_at(job_payload.get("createdAt")),
            scraped_at=datetime.now(timezone.utc).isoformat(),
            metadata={
                "site_name": site_name,
                "team": _normalize_text(categories.get("team", "")),
                "department": _normalize_text(categories.get("department", "")),
                "all_locations": [str(item).strip() for item in categories.get("allLocations", []) or [] if str(item).strip()],
                "workplace_type": workplace_type,
                "apply_url": str(job_payload.get("applyUrl", "") or "").strip(),
                "salary_text": salary_text,
            },
        )
