"""Tests for src/cached_jobs_store.py.

The store is the only thing that talks to the Supabase service-role
client, so tests here use a hand-rolled fake client (mirroring the
pattern in test_saved_jobs_store.py) and assert on the shapes of the
queries / payloads we construct.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.cached_jobs_store import CachedJobsStore


# ---------------------------------------------------------------------------
# Fake supabase-py client. Records every call so tests can assert on the
# shape of the upsert / select / update / delete chain.
# ---------------------------------------------------------------------------


class _FakeQuery:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def select(self, fields, count=None):
        self.calls.append(("select", fields, count))
        return self

    def upsert(self, rows, on_conflict=None):
        self.calls.append(("upsert", rows, on_conflict))
        return self

    def update(self, payload):
        self.calls.append(("update", payload))
        return self

    def delete(self):
        self.calls.append(("delete",))
        return self

    def in_(self, field, values):
        self.calls.append(("in_", field, list(values)))
        return self

    def eq(self, field, value):
        self.calls.append(("eq", field, value))
        return self

    def is_(self, field, value):
        self.calls.append(("is_", field, value))
        return self

    def lt(self, field, value):
        self.calls.append(("lt", field, value))
        return self

    def gte(self, field, value):
        self.calls.append(("gte", field, value))
        return self

    def ilike(self, field, value):
        self.calls.append(("ilike", field, value))
        return self

    def text_search(self, field, value, config=None, type_=None):
        self.calls.append(("text_search", field, value, config, type_))
        return self

    def order(self, field, desc=False):
        self.calls.append(("order", field, desc))
        return self

    def limit(self, value):
        self.calls.append(("limit", value))
        return self

    def execute(self):
        return self.response


class _FakeClient:
    def __init__(self, responses_per_table: dict):
        # responses_per_table = {"cached_jobs": [resp1, resp2, ...]}
        self._responses = {k: list(v) for k, v in responses_per_table.items()}
        self.queries = []

    def table(self, name):
        if name not in self._responses or not self._responses[name]:
            raise AssertionError(f"No queued response for table '{name}'")
        response = self._responses[name].pop(0)
        query = _FakeQuery(response)
        query.table_name = name
        self.queries.append(query)
        return query


def _make_store(client):
    """Build a CachedJobsStore wired to a fake client + bypass the
    is_configured() gate. We can't pass create_client through the
    constructor cleanly so we patch _client directly."""
    store = CachedJobsStore(
        supabase_url="http://fake",
        service_role_key="fake-key",
        table_name="cached_jobs",
        saved_jobs_table_name="saved_jobs",
    )
    store._client = client
    return store


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_upsert_postings_maps_jobposting_attrs_to_columns(monkeypatch):
    """JobPosting (or any duck-type with the same attrs) → row dict
    with the right column names + a last_seen_at timestamp added."""
    monkeypatch.setattr(
        "src.cached_jobs_store.create_client", lambda url, key: None
    )
    client = _FakeClient({"cached_jobs": [SimpleNamespace(data=[{"id": 1}])]})
    store = _make_store(client)

    posting = SimpleNamespace(
        id="gh-12345",
        source="greenhouse",
        title="Senior Backend Engineer",
        company="Stripe",
        location="San Francisco, CA",
        employment_type="Full-time",
        url="https://boards.greenhouse.io/stripe/jobs/12345",
        summary="Own the rate-limiter rewrite.",
        description_text="<p>Long HTML description...</p>",
        posted_at="2026-04-01T12:00:00Z",
        scraped_at="2026-05-07T18:00:00Z",
        metadata={"departments": ["Engineering"]},
    )
    upserted = store.upsert_postings("greenhouse", [posting])

    assert upserted == 1
    assert len(client.queries) == 1
    upsert_call = next(c for c in client.queries[0].calls if c[0] == "upsert")
    rows = upsert_call[1]
    on_conflict = upsert_call[2]
    assert on_conflict == "source,job_id"
    assert len(rows) == 1
    row = rows[0]
    # Column mapping — JobPosting.id → cached_jobs.job_id, .description_text
    # → .description, etc.
    assert row["source"] == "greenhouse"
    assert row["job_id"] == "gh-12345"
    assert row["title"] == "Senior Backend Engineer"
    assert row["description"] == "<p>Long HTML description...</p>"
    # posted_at parsed and reformatted to ISO with timezone.
    assert row["posted_at"].startswith("2026-04-01T12:00:00")
    # last_seen_at set client-side, removed_at reset to None.
    assert "last_seen_at" in row
    assert row["removed_at"] is None
    # metadata passed through as-is.
    assert row["metadata"] == {"departments": ["Engineering"]}


def test_upsert_skips_postings_with_empty_id(monkeypatch):
    """A posting with no id can't be upserted (would collide on the
    unique constraint with every other empty-id row). Skip silently."""
    monkeypatch.setattr(
        "src.cached_jobs_store.create_client", lambda url, key: None
    )
    client = _FakeClient({"cached_jobs": [SimpleNamespace(data=[])]})
    store = _make_store(client)

    bad_posting = SimpleNamespace(
        id="",
        source="greenhouse",
        title="ghost",
        company="",
        location="",
        employment_type="",
        url="",
        summary="",
        description_text="",
        posted_at="",
        metadata={},
    )
    upserted = store.upsert_postings("greenhouse", [bad_posting])
    # No rows actually upserted, so the count is 0 — but we still
    # call .table() once to see if there's anything to upsert. Wait,
    # our implementation actually does NOT issue the call when rows
    # is empty.
    assert upserted == 0
    assert client.queries == []  # short-circuited before hitting the client


def test_cleanup_tombstones_saved_jobs_and_deletes_unsaved(monkeypatch):
    """The smart cleanup: missing rows split into 'someone saved this
    → tombstone' and 'nobody saved this → hard delete' buckets."""
    monkeypatch.setattr(
        "src.cached_jobs_store.create_client", lambda url, key: None
    )

    # Sequence of supabase responses:
    #   1. saved_jobs select → returns one bookmark for greenhouse:saved-1
    #   2. cached_jobs select → returns three missing rows
    #   3. cached_jobs update (tombstone)
    #   4. cached_jobs delete
    client = _FakeClient(
        {
            "saved_jobs": [
                SimpleNamespace(
                    data=[{"source": "greenhouse", "job_id": "saved-1"}]
                )
            ],
            "cached_jobs": [
                SimpleNamespace(
                    data=[
                        {"id": 10, "source": "greenhouse", "job_id": "saved-1"},
                        {"id": 11, "source": "greenhouse", "job_id": "unsaved-2"},
                        {"id": 12, "source": "greenhouse", "job_id": "unsaved-3"},
                    ]
                ),
                SimpleNamespace(data=[]),  # update response
                SimpleNamespace(data=[]),  # delete response
            ],
        }
    )
    store = _make_store(client)
    tombstoned, deleted = store.cleanup_missing(
        sources_refreshed=["greenhouse"], cutoff_iso="2026-05-07T18:00:00Z"
    )

    assert tombstoned == 1
    assert deleted == 2
    # Verify the update query targeted the saved id only.
    update_query = client.queries[2]
    update_call = next(c for c in update_query.calls if c[0] == "update")
    assert update_call[1]["removed_at"] is not None
    in_call = next(c for c in update_query.calls if c[0] == "in_")
    assert in_call[2] == [10]
    # Verify the delete query targeted the two unsaved ids.
    delete_query = client.queries[3]
    delete_in_call = next(c for c in delete_query.calls if c[0] == "in_")
    assert sorted(delete_in_call[2]) == [11, 12]


def test_cleanup_no_op_when_no_sources_refreshed(monkeypatch):
    """If a refresh failed across the board, we skip cleanup entirely
    — saves us from the 'every Greenhouse row vaporised because of
    one DNS hiccup' failure mode."""
    monkeypatch.setattr(
        "src.cached_jobs_store.create_client", lambda url, key: None
    )
    client = _FakeClient({})
    store = _make_store(client)
    tombstoned, deleted = store.cleanup_missing(
        sources_refreshed=[], cutoff_iso="2026-05-07T18:00:00Z"
    )
    assert (tombstoned, deleted) == (0, 0)
    assert client.queries == []


def test_search_uses_websearch_fts_with_filters(monkeypatch):
    """Sanity-check the search query chain: text_search applied with
    websearch type + english config, removed_at filter present."""
    monkeypatch.setattr(
        "src.cached_jobs_store.create_client", lambda url, key: None
    )
    client = _FakeClient({"cached_jobs": [SimpleNamespace(data=[{"id": 99}])]})
    store = _make_store(client)
    rows = store.search(
        query="machine learning",
        location="San Francisco",
        remote_only=True,
        posted_within_days=14,
        limit=10,
    )
    assert rows == [{"id": 99}]
    calls = client.queries[0].calls
    # text_search, ilike, eq(remote=True), gte(posted_at, ...), order, limit
    text_search_call = next(c for c in calls if c[0] == "text_search")
    assert text_search_call[1] == "search_tsv"
    assert text_search_call[2] == "machine learning"
    assert text_search_call[3] == "english"
    assert text_search_call[4] == "websearch"
    assert any(c == ("ilike", "location", "%San Francisco%") for c in calls)
    assert any(c == ("eq", "remote", True) for c in calls)
    # removed_at IS NULL filter is applied early in the chain.
    assert any(c == ("is_", "removed_at", "null") for c in calls)


def test_get_listing_status_map_flags_tombstoned_keys(monkeypatch):
    """The lookup that powers the saved-jobs Expired badge: rows with
    removed_at NOT NULL come back as is_active=False; rows with
    removed_at NULL come back as True; keys we don't have in the
    cache default to True (don't false-flag jobs we never tracked)."""
    monkeypatch.setattr(
        "src.cached_jobs_store.create_client", lambda url, key: None
    )
    client = _FakeClient(
        {
            "cached_jobs": [
                SimpleNamespace(
                    data=[
                        # Active row: removed_at None.
                        {"source": "greenhouse", "job_id": "live-1", "removed_at": None},
                        # Tombstoned row: removed_at set to a real timestamp.
                        {"source": "greenhouse", "job_id": "dead-2", "removed_at": "2026-05-08T00:00:00Z"},
                    ]
                ),
            ]
        }
    )
    store = _make_store(client)
    keys = [
        ("greenhouse", "live-1"),
        ("greenhouse", "dead-2"),
        ("greenhouse", "untracked-3"),  # not in cache at all
    ]
    result = store.get_listing_status_map(keys)
    assert result == {
        ("greenhouse", "live-1"): True,
        ("greenhouse", "dead-2"): False,
        ("greenhouse", "untracked-3"): True,  # default optimistic
    }


def test_get_listing_status_map_returns_optimistic_on_cache_error(monkeypatch):
    """Cache outage during the saved-jobs annotate pass → return all
    keys as active so we don't flag good listings as expired in the
    UI just because Supabase is having a moment."""
    monkeypatch.setattr(
        "src.cached_jobs_store.create_client", lambda url, key: None
    )

    class _ErroringClient:
        def table(self, name):
            raise RuntimeError("supabase 500")

    store = _make_store(_ErroringClient())
    keys = [("greenhouse", "x"), ("lever", "y")]
    result = store.get_listing_status_map(keys)
    assert result == {key: True for key in keys}
