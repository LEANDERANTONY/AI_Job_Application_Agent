"""Ashby job-board adapter.

Ashby exposes a clean, public, no-auth JSON API at
  https://api.ashbyhq.com/posting-api/job-board/{token}
where {token} is the company's public board slug (linear, vercel,
cursor, etc.). Returns `{"jobs": [...]}` with rich per-job objects:
title, location, jobUrl, publishedAt, isRemote, employmentType,
descriptionPlain, descriptionHtml, department, team, address.

Used by:
- /jobs/search live fan-out (.search())
- /jobs/resolve URL inversion (.resolve_url() — Ashby URLs look like
  https://jobs.ashbyhq.com/{board}/{job_id})
- /admin/refresh-cache bulk pull (.fetch_all_postings())
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import re
from urllib.parse import urlparse

import requests

from src.config import ASHBY_BOARD_TOKENS
from src.job_sources.base import JobSourceAdapter
from src.job_sources.matching import (
    detect_role_families,
    extract_query_terms,
    location_matches_text,
    title_matches_role_families,
)
from src.schemas import (
    JobPosting,
    JobResolutionResult,
    JobSearchQuery,
    JobSourceSearchResponse,
)


_HTML_TAG_RE = re.compile(r"<[^>]+>")
# Ashby job URLs: jobs.ashbyhq.com/{board}/{uuid} OR
# jobs.ashbyhq.com/{board}/job/{uuid} (the apply variant). The UUID
# pattern is fixed.
_ASHBY_JOB_URL_RE = re.compile(
    r"^/(?P<board>[A-Za-z0-9._-]+)/(?:job/)?(?P<job_id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/?$",
    re.IGNORECASE,
)


def _strip_html(text: str) -> str:
    """Convert descriptionHtml → plain text. Ashby usually provides
    descriptionPlain too, but a few boards omit it — this is the
    fallback."""
    if not text:
        return ""
    return _HTML_TAG_RE.sub("", str(text)).strip()


def _normalize_text(value) -> str:
    return str(value or "").strip()


def _has_technical_title_signal(posting: JobPosting) -> bool:
    """Same intent as the Greenhouse + Lever filters: the board
    sometimes lists non-tech roles (recruiting, exec assistants) that
    pollute search. Filter to titles with at least one technical-role
    word so search results stay relevant."""
    title = (posting.title or "").lower()
    keywords = (
        "engineer", "engineering", "developer", "scientist", "analyst",
        "architect", "sre", "devops", "data", "machine learning", "ml ",
        "backend", "back-end", "frontend", "front-end", "fullstack",
        "full-stack", "platform", "infra", "infrastructure", "research",
        "product manager", "design", "designer",
    )
    return any(kw in title for kw in keywords)


class AshbyJobSourceAdapter(JobSourceAdapter):
    source_name = "ashby"
    _API_BASE_URL = "https://api.ashbyhq.com/posting-api/job-board/{token}"

    def __init__(
        self,
        board_tokens=None,
        http_session: requests.Session | None = None,
        timeout_seconds: int = 15,
    ):
        self._board_tokens = tuple(
            ASHBY_BOARD_TOKENS if board_tokens is None else board_tokens
        )
        self._http_session = http_session or requests.Session()
        self._timeout_seconds = timeout_seconds

    # ---- Live-fanout search (used by /jobs/search?live=true) ----------

    def search(self, query: JobSearchQuery) -> JobSourceSearchResponse:
        if not self._board_tokens:
            return JobSourceSearchResponse(
                source=self.source_name,
                status="not_configured",
                error_message="No Ashby board tokens configured.",
                source_details={"ashby": "not_configured"},
            )

        normalized_query = str(query.query or "").strip().lower()
        normalized_location = str(query.location or "").strip().lower()
        query_terms = extract_query_terms(normalized_query)
        role_families = detect_role_families(normalized_query)
        postings: list[JobPosting] = []
        board_statuses: dict[str, str] = {}

        max_workers = min(8, len(self._board_tokens)) or 1
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_board = {
                executor.submit(self._fetch_board_payload, token): token
                for token in self._board_tokens
            }
            for future in as_completed(future_to_board):
                token = future_to_board[future]
                try:
                    payload = future.result()
                except requests.RequestException:
                    board_statuses[token] = "error"
                    continue

                jobs = payload.get("jobs") or []
                matched_any = False
                matched_results: list[JobPosting] = []
                for job_payload in jobs:
                    posting = self._to_job_posting(token, job_payload)
                    if not _has_technical_title_signal(posting):
                        continue
                    if not title_matches_role_families(posting.title, role_families):
                        continue
                    if normalized_query and normalized_query not in (
                        posting.title.lower() + " " + posting.summary.lower()
                    ) and not any(t in posting.title.lower() for t in query_terms):
                        continue
                    if normalized_location and not location_matches_text(
                        posting.location.lower(), normalized_location
                    ):
                        continue
                    if query.remote_only and not _is_remote(posting):
                        continue
                    matched_any = True
                    matched_results.append(posting)
                if matched_any:
                    postings.extend(matched_results)
                    board_statuses[token] = "matched"
                elif jobs:
                    board_statuses[token] = "no_match"
                else:
                    board_statuses[token] = "empty"

        postings = postings[: query.page_size]
        overall_status = "ok"
        if board_statuses and all(s == "error" for s in board_statuses.values()):
            overall_status = "error"
        return JobSourceSearchResponse(
            source=self.source_name,
            results=postings,
            status=overall_status,
            source_details=board_statuses,
        )

    # ---- Bulk fetch for the cache refresh worker ---------------------

    def fetch_all_postings(self):
        """Yield (token, status, postings | error_msg) per board.

        Mirrors Greenhouse + Lever — same generator contract so the
        refresh worker can iterate uniformly across providers.
        """
        if not self._board_tokens:
            return

        max_workers = min(8, len(self._board_tokens)) or 1
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_board = {
                executor.submit(self._fetch_board_payload, token): token
                for token in self._board_tokens
            }
            for future in as_completed(future_to_board):
                token = future_to_board[future]
                try:
                    payload = future.result()
                except requests.RequestException as exc:
                    yield (token, "error", str(exc))
                    continue

                jobs = payload.get("jobs") or []
                if not jobs:
                    yield (token, "empty", [])
                    continue
                postings = [
                    self._to_job_posting(token, job_payload)
                    for job_payload in jobs
                ]
                yield (token, "ok", postings)

    # ---- URL resolution (used by /jobs/resolve) ----------------------

    def can_resolve_url(self, url: str) -> bool:
        parsed = urlparse(str(url or "").strip())
        if parsed.netloc.lower() != "jobs.ashbyhq.com":
            return False
        return bool(_ASHBY_JOB_URL_RE.match(parsed.path or ""))

    def resolve_url(self, url: str) -> JobResolutionResult:
        parsed = urlparse(str(url or "").strip())
        match = _ASHBY_JOB_URL_RE.match(parsed.path or "")
        if match is None:
            return JobResolutionResult(
                source=self.source_name,
                status="unsupported",
                error_message="URL is not a supported Ashby job URL.",
            )
        board_token = match.group("board")
        job_id = match.group("job_id")
        # Ashby's posting-api doesn't expose a single-job lookup —
        # we fetch the whole board and find the job by id. Same
        # network cost we'd pay for the full search anyway.
        try:
            payload = self._fetch_board_payload(board_token)
        except requests.RequestException as exc:
            return JobResolutionResult(
                source=self.source_name,
                status="error",
                error_message=str(exc),
                source_details={board_token: "error"},
            )
        for job_payload in payload.get("jobs", []) or []:
            if str(job_payload.get("id", "")) == job_id:
                return JobResolutionResult(
                    source=self.source_name,
                    status="ok",
                    job_posting=self._to_job_posting(board_token, job_payload),
                    source_details={board_token: "resolved"},
                )
        return JobResolutionResult(
            source=self.source_name,
            status="not_found",
            error_message="Job id not found on this Ashby board.",
            source_details={board_token: "not_found"},
        )

    # ---- Internals ---------------------------------------------------

    def _fetch_board_payload(self, board_token: str) -> dict:
        response = self._http_session.get(
            self._API_BASE_URL.format(token=board_token),
            params={"includeCompensation": "true"},
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        return response.json()

    def _to_job_posting(self, board_token: str, job_payload: dict) -> JobPosting:
        # Ashby gives both descriptionPlain and descriptionHtml; prefer
        # the plain version so we don't need to strip HTML downstream.
        # Fall back to HTML→stripped if descriptionPlain is missing.
        description = (
            _normalize_text(job_payload.get("descriptionPlain"))
            or _strip_html(job_payload.get("descriptionHtml"))
        )
        # Short summary = first 280 chars of the description, like
        # Greenhouse/Lever do downstream.
        summary = description[:280].rsplit(" ", 1)[0] if description else ""

        # Company name fallback: Ashby payloads don't include the
        # company name directly (the board IS the company). Use the
        # board_token, capitalized for display.
        company_name = board_token.replace("-", " ").replace("_", " ").title()

        # Build the canonical job URL. Ashby returns one in `jobUrl`
        # but we double-check it has the expected shape.
        job_url = _normalize_text(job_payload.get("jobUrl")) or _normalize_text(
            job_payload.get("applyUrl")
        )

        return JobPosting(
            id="ashby:{board}:{jid}".format(
                board=board_token, jid=job_payload.get("id", "")
            ),
            source=self.source_name,
            title=_normalize_text(job_payload.get("title")),
            company=company_name,
            location=_normalize_text(job_payload.get("location")),
            employment_type=_normalize_text(job_payload.get("employmentType")),
            url=job_url,
            summary=summary,
            description_text=description,
            posted_at=_normalize_text(job_payload.get("publishedAt")),
            scraped_at="",
            metadata={
                "board_token": board_token,
                "job_id": _normalize_text(job_payload.get("id")),
                "is_remote": bool(job_payload.get("isRemote")),
                "department": _normalize_text(
                    (job_payload.get("department") or {}).get("name")
                    if isinstance(job_payload.get("department"), dict)
                    else job_payload.get("department")
                ),
                "team": _normalize_text(
                    (job_payload.get("team") or {}).get("name")
                    if isinstance(job_payload.get("team"), dict)
                    else job_payload.get("team")
                ),
                "workplace_type": _normalize_text(job_payload.get("workplaceType")),
            },
        )


def _is_remote(posting: JobPosting) -> bool:
    """Read the cached metadata.is_remote flag, with a textual fallback
    on the location string."""
    if isinstance(posting.metadata, dict) and posting.metadata.get("is_remote"):
        return True
    return "remote" in (posting.location or "").lower()
