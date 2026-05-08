"""Tests for src/job_sources/workday.WorkdayJobSourceAdapter.

Workday's contract is more involved than the other adapters:
3-tuple tokens (`tenant:host:site`), POST API, paginated, no
descriptions in the list endpoint, and a `postedOn` field that's a
human-readable string ("Posted Today" / "Posted 5 Days Ago" / etc.)
which the adapter parses into a real timestamp. Tests pin each
of those pieces.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.job_sources.workday import (
    WorkdayJobSourceAdapter,
    _parse_posted_on,
    _parse_token,
)
from src.schemas import JobSearchQuery


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")
        return None

    def json(self):
        return self._payload


class _FakeSession:
    """Records POST calls + serves canned page responses by url+offset."""

    def __init__(self, pages_by_url):
        # pages_by_url = {url: [page1, page2, ...]} OR a callable
        self.pages_by_url = pages_by_url
        self.calls = []

    def post(self, url, json=None, timeout=None, headers=None):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        if callable(self.pages_by_url):
            payload = self.pages_by_url(url, json)
        else:
            offset = (json or {}).get("offset", 0)
            page_index = offset // (json or {}).get("limit", 50)
            pages = self.pages_by_url.get(url) or []
            payload = pages[page_index] if page_index < len(pages) else {"jobPostings": [], "total": 0}
        return _FakeResponse(payload)


# ---------------------------------------------------------------------------
# Token parsing
# ---------------------------------------------------------------------------


def test_parse_token_splits_tenant_host_site():
    """Three-part tokens are normalized into (tenant, host, site)
    tuples; bad shapes return None so the adapter can skip them."""
    assert _parse_token("nvidia:wd5:NVIDIAExternalCareerSite") == (
        "nvidia", "wd5", "NVIDIAExternalCareerSite",
    )
    # Missing parts → None
    assert _parse_token("nvidia:wd5") is None
    assert _parse_token("nvidia") is None
    assert _parse_token("") is None
    # Whitespace tolerated
    assert _parse_token("  adobe : wd5 : external_experienced  ") == (
        "adobe", "wd5", "external_experienced",
    )


# ---------------------------------------------------------------------------
# postedOn parsing
# ---------------------------------------------------------------------------


def test_parse_posted_on_today():
    """'Posted Today' parses to today's noon UTC. We use noon (not
    now) because Workday doesn't expose the hour, so any consistent
    intra-day choice works for ORDER BY purposes."""
    iso = _parse_posted_on("Posted Today")
    parsed = datetime.fromisoformat(iso)
    today = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0)
    assert parsed.date() == today.date()


def test_parse_posted_on_yesterday():
    iso = _parse_posted_on("Posted Yesterday")
    parsed = datetime.fromisoformat(iso)
    expected = datetime.now(timezone.utc).date() - timedelta(days=1)
    assert parsed.date() == expected


def test_parse_posted_on_n_days_ago():
    """'Posted 5 Days Ago' maps to today − 5 days. The '30+ Days
    Ago' bucket is treated as exactly 30 (best info Workday gives)."""
    iso = _parse_posted_on("Posted 5 Days Ago")
    parsed = datetime.fromisoformat(iso)
    expected = datetime.now(timezone.utc).date() - timedelta(days=5)
    assert parsed.date() == expected
    iso30 = _parse_posted_on("Posted 30+ Days Ago")
    parsed30 = datetime.fromisoformat(iso30)
    expected30 = datetime.now(timezone.utc).date() - timedelta(days=30)
    assert parsed30.date() == expected30


def test_parse_posted_on_unknown_returns_empty():
    """Anything we don't recognize comes back as '' so the cache
    column stays NULL (rather than mis-parsed gibberish)."""
    assert _parse_posted_on("") == ""
    assert _parse_posted_on("Some weird format") == ""
    assert _parse_posted_on(None) == ""


# ---------------------------------------------------------------------------
# Adapter behavior
# ---------------------------------------------------------------------------


def _job_payload(*, title="Senior Software Engineer", location="US, CA, Santa Clara",
                 path="/job/US-CA-Santa-Clara/Senior-Software-Engineer_JR2017000",
                 req_id="JR2017000", posted="Posted Today"):
    return {
        "title": title,
        "locationsText": location,
        "externalPath": path,
        "postedOn": posted,
        "bulletFields": [req_id] if req_id else [],
    }


def test_adapter_normalizes_workday_payload_to_jobposting():
    """Workday payload → JobPosting with the right field aliasing
    (locationsText → location, externalPath → URL prefix, bulletFields[0]
    → requisition_id, postedOn → parsed posted_at)."""
    api_url = (
        "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/"
        "nvidia/NVIDIAExternalCareerSite/jobs"
    )
    fake = _FakeSession({api_url: [
        {"jobPostings": [_job_payload()], "total": 1},
        {"jobPostings": [], "total": 1},  # empty 2nd page short-circuits pagination
    ]})
    adapter = WorkdayJobSourceAdapter(
        board_tokens=["nvidia:wd5:NVIDIAExternalCareerSite"],
        http_session=fake,
    )
    response = adapter.search(JobSearchQuery(query="software engineer", page_size=10))

    assert response.status == "ok"
    assert len(response.results) == 1
    posting = response.results[0]
    assert posting.source == "workday"
    # Composite id includes tenant + req_id so cross-tenant dupes can't collide.
    assert posting.id == "workday:nvidia:JR2017000"
    assert posting.title == "Senior Software Engineer"
    assert posting.company == "Nvidia"
    assert posting.location == "US, CA, Santa Clara"
    # URL is built from tenant + host + site + externalPath.
    assert posting.url.startswith(
        "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite"
    )
    assert posting.url.endswith("Senior-Software-Engineer_JR2017000")
    # posted_at parsed from "Posted Today".
    assert posting.posted_at  # non-empty
    # Description is empty — Workday list endpoint doesn't include it.
    assert posting.description_text == ""
    # Metadata carries the Workday-only fields for resolve / debugging.
    assert posting.metadata["tenant"] == "nvidia"
    assert posting.metadata["host"] == "wd5"
    assert posting.metadata["site"] == "NVIDIAExternalCareerSite"
    assert posting.metadata["requisition_id"] == "JR2017000"
    assert posting.metadata["posted_on_label"] == "Posted Today"


def test_adapter_paginates_until_max_or_total():
    """The adapter walks pages until it hits MAX_JOBS_PER_BOARD OR the
    payload's `total`, whichever fires first. Pin both: verify the
    right number of POSTs went out and the union of results came
    through.

    Test reads `_PAGE_SIZE` from the module instead of hard-coding so
    a later page-size change (e.g. when Workday tightens API limits
    again) doesn't re-break the test. We just need the math to land
    cleanly: PAGES_TO_RETURN pages × _PAGE_SIZE per page = total,
    so the early-stop hits exactly when `offset == total`.
    """
    from src.job_sources.workday import _PAGE_SIZE

    api_url = (
        "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/"
        "nvidia/NVIDIAExternalCareerSite/jobs"
    )

    PAGES_TO_RETURN = 3
    total = _PAGE_SIZE * PAGES_TO_RETURN
    pages = [
        {
            "jobPostings": [
                _job_payload(req_id=f"R{p * _PAGE_SIZE + i}", title=f"Job {p * _PAGE_SIZE + i}")
                for i in range(_PAGE_SIZE)
            ],
            "total": total,
        }
        for p in range(PAGES_TO_RETURN)
    ]
    fake = _FakeSession({api_url: pages})
    adapter = WorkdayJobSourceAdapter(
        board_tokens=["nvidia:wd5:NVIDIAExternalCareerSite"],
        http_session=fake,
    )
    results = list(adapter.fetch_all_postings())
    assert len(results) == 1
    label, status, postings = results[0]
    assert status == "ok"
    assert len(postings) == total
    # PAGES_TO_RETURN POSTs — the next page never gets requested
    # because the offset == total early-stop trips immediately after
    # the last full page.
    assert len(fake.calls) == PAGES_TO_RETURN


def test_adapter_unconfigured_returns_not_configured():
    adapter = WorkdayJobSourceAdapter(board_tokens=[])
    response = adapter.search(JobSearchQuery(query="anything", page_size=10))
    assert response.status == "not_configured"
    assert response.results == []


def test_adapter_drops_invalid_tokens_silently():
    """Tokens that don't match tenant:host:site shape are dropped
    at __init__ time. The remaining valid tokens still work."""
    api_url = (
        "https://nvidia.wd5.myworkdayjobs.com/wday/cxs/"
        "nvidia/NVIDIAExternalCareerSite/jobs"
    )
    fake = _FakeSession({api_url: [
        {"jobPostings": [_job_payload()], "total": 1},
        {"jobPostings": [], "total": 1},
    ]})
    adapter = WorkdayJobSourceAdapter(
        board_tokens=[
            "bad-token-no-colons",
            "nvidia:wd5:NVIDIAExternalCareerSite",
            "still:bad",  # only two parts
        ],
        http_session=fake,
    )
    response = adapter.search(JobSearchQuery(query="engineer", page_size=10))
    # Only the well-formed token contributed.
    assert response.status == "ok"
    assert len(response.results) == 1


def test_can_resolve_url_recognizes_workday_hosts():
    adapter = WorkdayJobSourceAdapter(board_tokens=[])
    assert adapter.can_resolve_url(
        "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/foo"
    )
    assert adapter.can_resolve_url(
        "https://adobe.wd5.myworkdayjobs.com/external_experienced/job/x"
    )
    assert not adapter.can_resolve_url("https://boards.greenhouse.io/stripe/jobs/1")
    assert not adapter.can_resolve_url("")
