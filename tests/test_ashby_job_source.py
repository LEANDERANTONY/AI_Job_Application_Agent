"""Tests for src/job_sources/ashby.AshbyJobSourceAdapter.

Mirrors the test_lever_job_source pattern: a fake HTTP session
returns canned API payloads and we assert on the JobPosting shape +
search filtering + URL resolution + bulk-fetch generator contract.
"""
from __future__ import annotations

from src.job_sources.ashby import AshbyJobSourceAdapter
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
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        payload = self.payload(url, params) if callable(self.payload) else self.payload
        return _FakeResponse(payload)


def _ashby_job_payload(*, job_id="d3bc1ced-3ce4-4086-a050-555055dbb1ff",
                       title="Senior Backend Engineer",
                       location="San Francisco",
                       is_remote=False,
                       description="Build distributed systems with Python."):
    return {
        "id": job_id,
        "title": title,
        "location": location,
        "isRemote": is_remote,
        "employmentType": "FullTime",
        "jobUrl": f"https://jobs.ashbyhq.com/example/{job_id}",
        "applyUrl": f"https://jobs.ashbyhq.com/example/{job_id}/application",
        "publishedAt": "2026-04-01T12:00:00.000+00:00",
        "descriptionPlain": description,
        "descriptionHtml": f"<p>{description}</p>",
        "department": {"name": "Engineering"},
        "team": {"name": "Backend Platform"},
        "workplaceType": "Hybrid",
        "address": {"city": "San Francisco"},
    }


def test_ashby_adapter_to_job_posting_shape():
    """The adapter maps Ashby's payload shape into our JobPosting
    dataclass with the right field aliases (id → namespaced id,
    descriptionPlain → description_text, publishedAt → posted_at)
    and stuffs the Ashby-only metadata (is_remote, department, team)
    into JobPosting.metadata."""
    fake = _FakeSession({"jobs": [_ashby_job_payload()]})
    adapter = AshbyJobSourceAdapter(board_tokens=["example"], http_session=fake)
    response = adapter.search(JobSearchQuery(query="backend engineer", page_size=10))

    assert response.status == "ok"
    assert len(response.results) == 1
    posting = response.results[0]
    assert posting.source == "ashby"
    # Composite id includes board + Ashby's UUID — keeps duplicates
    # from collisions across boards safely.
    assert posting.id.startswith("ashby:example:")
    assert posting.title == "Senior Backend Engineer"
    assert posting.company == "Example"  # title-cased from board token
    assert posting.location == "San Francisco"
    assert posting.url.startswith("https://jobs.ashbyhq.com/example/")
    assert "distributed systems" in posting.description_text.lower()
    # Metadata carries the Ashby-only fields.
    assert posting.metadata["is_remote"] is False
    assert posting.metadata["department"] == "Engineering"
    assert posting.metadata["team"] == "Backend Platform"


def test_ashby_adapter_filters_non_technical_titles_out():
    """The board sometimes lists exec assistants / recruiters /
    sales roles. The technical-title gate filters them out so a
    user searching 'engineer' doesn't get a flood of HR jobs."""
    fake = _FakeSession({"jobs": [
        _ashby_job_payload(job_id="11111111-1111-1111-1111-111111111111",
                           title="Recruiter, Engineering"),
        _ashby_job_payload(job_id="22222222-2222-2222-2222-222222222222",
                           title="Senior Software Engineer"),
        _ashby_job_payload(job_id="33333333-3333-3333-3333-333333333333",
                           title="Executive Assistant"),
    ]})
    adapter = AshbyJobSourceAdapter(board_tokens=["example"], http_session=fake)
    response = adapter.search(JobSearchQuery(query="engineer", page_size=10))

    titles = [p.title for p in response.results]
    assert "Senior Software Engineer" in titles
    assert "Executive Assistant" not in titles
    # Recruiter passes the technical-title gate (contains "Engineering")
    # but role-family matching can drop it depending on the query.
    # We're not asserting on it either way.


def test_ashby_adapter_can_resolve_canonical_url():
    """can_resolve_url accepts jobs.ashbyhq.com/{board}/{uuid} URLs
    and rejects everything else."""
    adapter = AshbyJobSourceAdapter(board_tokens=["example"])
    assert adapter.can_resolve_url(
        "https://jobs.ashbyhq.com/example/d3bc1ced-3ce4-4086-a050-555055dbb1ff"
    )
    # Apply variant with /job/ infix
    assert adapter.can_resolve_url(
        "https://jobs.ashbyhq.com/example/job/d3bc1ced-3ce4-4086-a050-555055dbb1ff"
    )
    # Non-Ashby URLs
    assert not adapter.can_resolve_url("https://boards.greenhouse.io/example/jobs/123")
    assert not adapter.can_resolve_url("")
    # Missing UUID
    assert not adapter.can_resolve_url("https://jobs.ashbyhq.com/example/")


def test_ashby_adapter_resolve_url_returns_matching_job():
    """resolve_url fetches the board, finds the job by id, returns
    a normalized JobPosting. Ashby has no single-job lookup so we
    pay the full-board fetch every time — same network cost as
    search() so it's fine."""
    target_id = "d3bc1ced-3ce4-4086-a050-555055dbb1ff"
    fake = _FakeSession({"jobs": [
        _ashby_job_payload(job_id="11111111-1111-1111-1111-111111111111",
                           title="Other Role"),
        _ashby_job_payload(job_id=target_id,
                           title="The Right One"),
    ]})
    adapter = AshbyJobSourceAdapter(board_tokens=["example"], http_session=fake)
    result = adapter.resolve_url(f"https://jobs.ashbyhq.com/example/{target_id}")

    assert result.status == "ok"
    assert result.job_posting is not None
    assert result.job_posting.title == "The Right One"


def test_ashby_adapter_fetch_all_postings_yields_per_board_results():
    """fetch_all_postings is the cache-refresh entry point. Yields
    (token, status, postings) per board. Mirrors Greenhouse / Lever
    so the refresh worker's per-source-failure isolation works
    uniformly across providers."""
    payloads = {
        "linear": {"jobs": [_ashby_job_payload(title="Senior Engineer")]},
        "vercel": {"jobs": []},  # empty board
    }

    def per_url(url, params):
        for token, payload in payloads.items():
            if token in url:
                return payload
        raise AssertionError(f"unexpected url {url}")

    fake = _FakeSession(per_url)
    adapter = AshbyJobSourceAdapter(
        board_tokens=["linear", "vercel"], http_session=fake
    )
    results = list(adapter.fetch_all_postings())
    by_token = {token: (status, payload) for token, status, payload in results}
    assert by_token["linear"][0] == "ok"
    assert len(by_token["linear"][1]) == 1
    assert by_token["vercel"][0] == "empty"
    assert by_token["vercel"][1] == []


def test_ashby_adapter_unconfigured_returns_not_configured_status():
    """Empty board list → search returns a graceful 'not_configured'
    response instead of raising. Lets backends boot without an Ashby
    seed list and report the gap."""
    adapter = AshbyJobSourceAdapter(board_tokens=[])
    response = adapter.search(JobSearchQuery(query="anything", page_size=10))
    assert response.status == "not_configured"
    assert response.results == []
