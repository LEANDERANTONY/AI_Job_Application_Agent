import html
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

from src.config import GREENHOUSE_BOARD_TOKENS
from src.job_sources.base import JobSourceAdapter
from src.schemas import JobPosting, JobResolutionResult, JobSearchQuery, JobSourceSearchResponse


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_GREENHOUSE_JOB_URL_RE = re.compile(
    r"^/([^/]+)/jobs/(\d+)",
    re.IGNORECASE,
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
            for job_payload in payload.get("jobs", []) or []:
                job_posting = self._to_job_posting(board_token, job_payload)
                haystack = " ".join(
                    [
                        job_posting.title,
                        job_posting.company,
                        job_posting.location,
                        job_posting.summary,
                        job_posting.description_text,
                    ]
                ).lower()
                if normalized_query and normalized_query not in haystack:
                    continue
                if normalized_location and normalized_location not in haystack:
                    continue
                matched_any = True
                postings.append(job_posting)
                if len(postings) >= query.page_size:
                    board_statuses[board_token] = "matched"
                    return JobSourceSearchResponse(
                        source=self.source_name,
                        results=postings,
                        status="ok",
                        source_details=board_statuses,
                    )
            if matched_any:
                board_statuses[board_token] = "matched"
            elif payload.get("jobs"):
                board_statuses[board_token] = "no_match"
            else:
                board_statuses[board_token] = "empty"

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
        metadata = job_payload.get("metadata") or {}
        company_name = _normalize_company_name(
            metadata.get("company_name") or metadata.get("company") or "",
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
            employment_type=str(metadata.get("employment_type", "")).strip(),
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
