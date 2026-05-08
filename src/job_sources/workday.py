"""Workday job-board adapter.

Workday is the standard ATS for most Fortune 500 companies (NVIDIA,
Adobe, Walmart, Citi, Disney, HP, BlackRock, Boeing, Workday itself,
…). Its API is more involved than Greenhouse/Lever/Ashby:

  * Each company runs its own Workday TENANT on a numbered host
    (wd1.myworkdayjobs.com, wd5.myworkdayjobs.com, etc.) at a named
    SITE (ExternalCareerSite, NVIDIAExternalCareerSite, ...). So a
    single board needs THREE pieces of identifying info:
      - tenant: the company subdomain (e.g. "nvidia")
      - host: "wd1" / "wd5" / etc.
      - site: the public site name
  * The job-search endpoint accepts POST (not GET) with a JSON body:
      {"appliedFacets": {}, "limit": 50, "offset": 0, "searchText": ""}
  * The list response only carries title / locationsText /
    externalPath / postedOn / bulletFields (req id). Descriptions
    require a per-job follow-up call — too expensive at refresh time
    for thousands of rows. We cache the list-level data; full
    descriptions get fetched on demand via resolve_url.
  * The `postedOn` field is a human-readable string ("Posted Today",
    "Posted 5 Days Ago", "Posted 30+ Days Ago") — we parse to a
    timestamp so the cache's posted_at column can be ORDER BY-able.

Token format in the env var: comma-separated `tenant:host:site`
triples, e.g.
  WORKDAY_BOARD_TOKENS=nvidia:wd5:NVIDIAExternalCareerSite,adobe:wd5:external_experienced
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
import re
import time
from urllib.parse import urlparse

import requests

from src.config import WORKDAY_BOARD_TOKENS
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


# How many jobs to pull per Workday board per refresh. Workday allows
# higher pagination but most users want recent listings; 250 covers
# 90% of a typical Fortune 500 hiring window without ballooning the
# refresh into hundreds of HTTP calls.
_MAX_JOBS_PER_BOARD = 250
# Workday accepts up to 50 per page reliably; 20 is the browser default.
_PAGE_SIZE = 50
# Workday IP-rate-limits aggressively (we got 400s after ~80 POSTs in
# a few minutes during validation). Two throttles below mitigate:
#   1) Lower per-provider concurrency (3 not 8) so we don't slam them
#      with 11 simultaneous board fans.
#   2) Sleep between paginated POSTs to the same board.
_PER_BOARD_PAGE_DELAY_SECONDS = 0.4
_MAX_CONCURRENT_BOARDS = 3

# Heuristic: Workday's "postedOn" parser.
_POSTED_TODAY_RE = re.compile(r"posted\s+today", re.IGNORECASE)
_POSTED_YESTERDAY_RE = re.compile(r"posted\s+yesterday", re.IGNORECASE)
_POSTED_DAYS_AGO_RE = re.compile(
    r"posted\s+(\d+)\+?\s+days?\s+ago", re.IGNORECASE
)


def _parse_posted_on(value: str) -> str:
    """Convert Workday's posted-on label into an ISO timestamp.

    Returns '' when we can't parse — caller treats empty posted_at as
    'unknown' and falls back to last_seen_at for sorting.
    """
    text = (value or "").strip()
    if not text:
        return ""
    today = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    if _POSTED_TODAY_RE.search(text):
        return today.isoformat()
    if _POSTED_YESTERDAY_RE.search(text):
        return (today - timedelta(days=1)).isoformat()
    match = _POSTED_DAYS_AGO_RE.search(text)
    if match:
        days = int(match.group(1))
        # "30+ days ago" matches as `30` here — that's fine, treat as
        # at-least-30 (we lose precision past 30, which is what
        # Workday hides too).
        return (today - timedelta(days=days)).isoformat()
    return ""


def _parse_token(token: str) -> tuple[str, str, str] | None:
    """Split a tenant:host:site token into its three parts."""
    parts = [p.strip() for p in str(token or "").split(":")]
    if len(parts) != 3 or not all(parts):
        return None
    return (parts[0], parts[1], parts[2])


def _normalize_text(value) -> str:
    return str(value or "").strip()


def _has_technical_title_signal(posting: JobPosting) -> bool:
    """Same intent as the other adapters — drop sales / HR / exec
    roles when the user is searching for engineering work."""
    title = (posting.title or "").lower()
    keywords = (
        "engineer", "engineering", "developer", "scientist", "analyst",
        "architect", "sre", "devops", "data", "machine learning", "ml ",
        "backend", "back-end", "frontend", "front-end", "fullstack",
        "full-stack", "platform", "infra", "infrastructure", "research",
        "product manager", "design", "designer",
    )
    return any(kw in title for kw in keywords)


class WorkdayJobSourceAdapter(JobSourceAdapter):
    source_name = "workday"

    def __init__(
        self,
        board_tokens=None,
        http_session: requests.Session | None = None,
        timeout_seconds: int = 15,
    ):
        # Parse all configured tokens up front so the rest of the
        # adapter works with structured tuples instead of raw strings.
        # Invalid tokens are dropped silently — the env-validator
        # gives the user the friendly error.
        raw_tokens = WORKDAY_BOARD_TOKENS if board_tokens is None else board_tokens
        self._boards: list[tuple[str, str, str]] = []
        for token in raw_tokens:
            parsed = _parse_token(token)
            if parsed is not None:
                self._boards.append(parsed)
        self._http_session = http_session or requests.Session()
        self._timeout_seconds = timeout_seconds

    # ---- Live-fanout search ------------------------------------------

    def search(self, query: JobSearchQuery) -> JobSourceSearchResponse:
        if not self._boards:
            return JobSourceSearchResponse(
                source=self.source_name,
                status="not_configured",
                error_message="No Workday board tokens configured.",
                source_details={"workday": "not_configured"},
            )

        normalized_query = str(query.query or "").strip().lower()
        normalized_location = str(query.location or "").strip().lower()
        query_terms = extract_query_terms(normalized_query)
        role_families = detect_role_families(normalized_query)
        postings: list[JobPosting] = []
        board_statuses: dict[str, str] = {}

        max_workers = min(_MAX_CONCURRENT_BOARDS, len(self._boards)) or 1
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_board = {
                executor.submit(self._fetch_board_jobs, board): board
                for board in self._boards
            }
            for future in as_completed(future_to_board):
                board = future_to_board[future]
                board_label = self._board_label(board)
                try:
                    job_payloads = future.result()
                except requests.RequestException:
                    board_statuses[board_label] = "error"
                    continue

                matched_any = False
                matched_results: list[JobPosting] = []
                for jp in job_payloads:
                    posting = self._to_job_posting(board, jp)
                    if not _has_technical_title_signal(posting):
                        continue
                    if not title_matches_role_families(posting.title, role_families):
                        continue
                    if normalized_query and normalized_query not in posting.title.lower() \
                            and not any(t in posting.title.lower() for t in query_terms):
                        continue
                    if normalized_location and not location_matches_text(
                        posting.location.lower(), normalized_location
                    ):
                        continue
                    if query.remote_only and "remote" not in posting.location.lower():
                        continue
                    matched_any = True
                    matched_results.append(posting)
                if matched_any:
                    postings.extend(matched_results)
                    board_statuses[board_label] = "matched"
                elif job_payloads:
                    board_statuses[board_label] = "no_match"
                else:
                    board_statuses[board_label] = "empty"

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
        """Yield (board_label, status, postings | error_msg) per board.

        Mirrors Greenhouse / Lever / Ashby. board_label is the
        tenant for human-readable error reporting (e.g., 'nvidia').
        """
        if not self._boards:
            return

        max_workers = min(_MAX_CONCURRENT_BOARDS, len(self._boards)) or 1
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_board = {
                executor.submit(self._fetch_board_jobs, board): board
                for board in self._boards
            }
            for future in as_completed(future_to_board):
                board = future_to_board[future]
                label = self._board_label(board)
                try:
                    job_payloads = future.result()
                except requests.RequestException as exc:
                    yield (label, "error", str(exc))
                    continue
                if not job_payloads:
                    yield (label, "empty", [])
                    continue
                postings = [
                    self._to_job_posting(board, jp) for jp in job_payloads
                ]
                yield (label, "ok", postings)

    # ---- URL resolution ----------------------------------------------

    def can_resolve_url(self, url: str) -> bool:
        parsed = urlparse(str(url or "").strip())
        return parsed.netloc.endswith("myworkdayjobs.com") and bool(parsed.path)

    def resolve_url(self, url: str) -> JobResolutionResult:
        """Workday URLs are deeply per-tenant
        (tenant.wd5.myworkdayjobs.com/site/job/...). We don't have a
        single-job lookup endpoint — the resolve path would need the
        cached_jobs row anyway. Return unsupported and let the caller
        fall back to the cache lookup."""
        return JobResolutionResult(
            source=self.source_name,
            status="unsupported",
            error_message=(
                "Workday job URLs aren't directly resolvable via the "
                "list API; look up the job by id in cached_jobs instead."
            ),
        )

    # ---- Internals ---------------------------------------------------

    def _api_url(self, board: tuple[str, str, str]) -> str:
        tenant, host, site = board
        return (
            f"https://{tenant}.{host}.myworkdayjobs.com/wday/cxs/"
            f"{tenant}/{site}/jobs"
        )

    def _board_label(self, board: tuple[str, str, str]) -> str:
        tenant, _host, _site = board
        return tenant

    def _fetch_board_jobs(self, board: tuple[str, str, str]) -> list[dict]:
        """Paginate Workday's POST /jobs API up to _MAX_JOBS_PER_BOARD.

        Stops early when the API reports fewer total jobs than our
        cap, or when a page returns empty. Each request is its own
        POST — Workday doesn't expose a streaming endpoint.
        """
        api = self._api_url(board)
        all_jobs: list[dict] = []
        offset = 0
        while offset < _MAX_JOBS_PER_BOARD:
            # Throttle between pages of the SAME board. The first page
            # has no preceding call, so skip the sleep then. Workday
            # blocks bursts; spreading pages by ~400ms keeps us under
            # the per-IP threshold during the refresh worker's run.
            if offset > 0:
                time.sleep(_PER_BOARD_PAGE_DELAY_SECONDS)
            body = {
                "appliedFacets": {},
                "limit": _PAGE_SIZE,
                "offset": offset,
                "searchText": "",
            }
            response = self._http_session.post(
                api,
                json=body,
                timeout=self._timeout_seconds,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            response.raise_for_status()
            payload = response.json()
            page = payload.get("jobPostings") or []
            if not page:
                break
            all_jobs.extend(page)
            total = int(payload.get("total") or 0)
            offset += _PAGE_SIZE
            if offset >= total:
                break
        return all_jobs[:_MAX_JOBS_PER_BOARD]

    def _to_job_posting(
        self, board: tuple[str, str, str], job_payload: dict
    ) -> JobPosting:
        tenant, host, site = board
        external_path = _normalize_text(job_payload.get("externalPath"))
        # Browser-facing job URL. Workday's path already starts with
        # `/job/...`; we just prefix the host.
        job_url = (
            f"https://{tenant}.{host}.myworkdayjobs.com/{site}{external_path}"
            if external_path
            else ""
        )
        # Workday gives us the requisition id in bulletFields.
        bullet_fields = job_payload.get("bulletFields") or []
        req_id = bullet_fields[0] if bullet_fields else ""
        # Composite id includes the tenant so jobs from different
        # Workday tenants don't collide on the (source, job_id) unique
        # constraint in cached_jobs.
        composite_id = f"workday:{tenant}:{req_id or external_path}"

        # Tenant → display company name (capitalize, hyphens to spaces).
        company = tenant.replace("-", " ").replace("_", " ").title()

        return JobPosting(
            id=composite_id,
            source=self.source_name,
            title=_normalize_text(job_payload.get("title")),
            company=company,
            location=_normalize_text(job_payload.get("locationsText")),
            employment_type="",  # not in list endpoint
            url=job_url,
            summary="",  # description requires per-job follow-up
            description_text="",  # same — fetched lazily on click
            posted_at=_parse_posted_on(job_payload.get("postedOn")),
            scraped_at="",
            metadata={
                "tenant": tenant,
                "host": host,
                "site": site,
                "external_path": external_path,
                "requisition_id": req_id,
                "posted_on_label": _normalize_text(job_payload.get("postedOn")),
            },
        )
