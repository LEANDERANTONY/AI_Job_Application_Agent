"""Tests for scripts/backfill_job_embeddings.py (Tier 2).

The backfill is exercised through `run_backfill`, which takes an
injectable Supabase client + OpenAIService — so these tests drive it
with a fake Supabase client (records select/update chains, replays
queued responses) and a mocked OpenAIService (no real API calls).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from scripts.backfill_job_embeddings import (
    build_embedding_input,
    run_backfill,
)


# ---------------------------------------------------------------------------
# Fake Supabase client — enough of the builder chain for the backfill:
#   .table(t).select(cols).is_(col, "null").order(col).limit(n).execute()
#   .table(t).update(payload).eq(col, val).execute()
# ---------------------------------------------------------------------------


class _FakeQuery:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def select(self, fields):
        self.calls.append(("select", fields))
        return self

    def update(self, payload):
        self.calls.append(("update", payload))
        return self

    def is_(self, field, value):
        self.calls.append(("is_", field, value))
        return self

    def eq(self, field, value):
        self.calls.append(("eq", field, value))
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
    """Replays a queue of responses, one per `.table()` call."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.queries = []

    def table(self, name):
        if not self._responses:
            raise AssertionError(f"No queued response for table('{name}')")
        query = _FakeQuery(self._responses.pop(0))
        query.table_name = name
        self.queries.append(query)
        return query


class _FakeOpenAIService:
    """Mocked OpenAIService — returns deterministic vectors, or raises."""

    def __init__(self, *, raise_on_call=False, vector_count_override=None):
        self.calls = []
        self._raise = raise_on_call
        self._count_override = vector_count_override

    def is_available(self):
        return True

    def create_embeddings(self, inputs, *, model=None, task_name=None):
        self.calls.append(list(inputs))
        if self._raise:
            raise RuntimeError("embeddings API down")
        count = (
            self._count_override
            if self._count_override is not None
            else len(inputs)
        )
        # One small deterministic vector per input.
        return [[float(i), 0.5] for i in range(count)]


def _row(row_id, title="Engineer", company="Acme", description="Build things."):
    return {
        "id": row_id,
        "title": title,
        "company": company,
        "description": description,
    }


# ---------------------------------------------------------------------------
# build_embedding_input
# ---------------------------------------------------------------------------


def test_build_embedding_input_combines_fields_and_caps_description():
    row = _row(1, title="Data Scientist", company="Globex", description="X" * 5000)
    text = build_embedding_input(row, description_chars=2000)
    assert "Job title: Data Scientist" in text
    assert "Company: Globex" in text
    # Description capped at 2000 chars (+ the "Description: " label).
    assert text.count("X") == 2000


def test_build_embedding_input_drops_empty_fields():
    row = {"id": 2, "title": "", "company": "Initech", "description": ""}
    text = build_embedding_input(row, description_chars=2000)
    assert text == "Company: Initech"


def test_build_embedding_input_never_empty():
    """A row with no usable text still yields a non-empty string — the
    embeddings API rejects empty input."""
    row = {"id": 3, "title": "", "company": "", "description": ""}
    text = build_embedding_input(row, description_chars=2000)
    assert text.strip() != ""


# ---------------------------------------------------------------------------
# run_backfill — happy path
# ---------------------------------------------------------------------------


def test_run_backfill_embeds_all_null_rows_and_writes_back():
    """Three NULL rows → one embeddings batch → three write-backs."""
    select_response = SimpleNamespace(data=[_row(10), _row(11), _row(12)])
    # One table() call to select + one per row update = 4 total.
    client = _FakeClient(
        [
            select_response,
            SimpleNamespace(data=[]),  # update row 10
            SimpleNamespace(data=[]),  # update row 11
            SimpleNamespace(data=[]),  # update row 12
        ]
    )
    openai_service = _FakeOpenAIService()

    summary = run_backfill(
        client=client,
        openai_service=openai_service,
        table="cached_jobs",
        batch_size=100,
        description_chars=2000,
        limit=0,
        dry_run=False,
    )

    assert summary["rows_considered"] == 3
    assert summary["rows_embedded"] == 3
    assert summary["rows_failed"] == 0
    assert summary["batches_total"] == 1
    assert summary["batches_failed"] == 0
    # One embeddings call carrying all three inputs (batched).
    assert len(openai_service.calls) == 1
    assert len(openai_service.calls[0]) == 3
    # The select filtered on embedding IS NULL.
    select_query = client.queries[0]
    assert ("is_", "embedding", "null") in select_query.calls
    # Each update wrote an embedding keyed on the row id.
    update_ids = [
        q.calls[-1][2] for q in client.queries[1:] if q.calls[-1][0] == "eq"
    ]
    assert sorted(update_ids) == [10, 11, 12]


def test_run_backfill_no_null_rows_is_a_noop():
    """Everything already embedded → no API call, no writes, clean exit.
    This is the idempotent re-run case."""
    client = _FakeClient([SimpleNamespace(data=[])])
    openai_service = _FakeOpenAIService()

    summary = run_backfill(
        client=client,
        openai_service=openai_service,
        table="cached_jobs",
        batch_size=100,
        description_chars=2000,
        limit=0,
        dry_run=False,
    )

    assert summary["rows_considered"] == 0
    assert summary["rows_embedded"] == 0
    assert openai_service.calls == []
    # Only the one select query — no updates.
    assert len(client.queries) == 1


def test_run_backfill_batches_respect_batch_size():
    """5 rows with batch_size=2 → 3 embeddings calls (2+2+1)."""
    select_response = SimpleNamespace(data=[_row(i) for i in range(1, 6)])
    # 1 select + 5 updates.
    client = _FakeClient(
        [select_response] + [SimpleNamespace(data=[]) for _ in range(5)]
    )
    openai_service = _FakeOpenAIService()

    summary = run_backfill(
        client=client,
        openai_service=openai_service,
        table="cached_jobs",
        batch_size=2,
        description_chars=2000,
        limit=0,
        dry_run=False,
    )

    assert summary["batches_total"] == 3
    assert summary["rows_embedded"] == 5
    assert [len(c) for c in openai_service.calls] == [2, 2, 1]


# ---------------------------------------------------------------------------
# run_backfill — dry run
# ---------------------------------------------------------------------------


def test_run_backfill_dry_run_makes_no_api_calls_or_writes():
    """--dry-run counts what WOULD be embedded but calls nothing."""
    client = _FakeClient([SimpleNamespace(data=[_row(1), _row(2)])])
    openai_service = _FakeOpenAIService()

    summary = run_backfill(
        client=client,
        openai_service=openai_service,
        table="cached_jobs",
        batch_size=100,
        description_chars=2000,
        limit=0,
        dry_run=True,
    )

    assert summary["dry_run"] is True
    assert summary["rows_considered"] == 2
    assert summary["rows_embedded"] == 2  # counted, not actually embedded
    assert openai_service.calls == []  # no API call
    assert len(client.queries) == 1  # only the select, no updates


# ---------------------------------------------------------------------------
# run_backfill — resilience
# ---------------------------------------------------------------------------


def test_run_backfill_skips_failed_batch_and_continues():
    """A failed embeddings batch is logged + skipped; those rows stay
    NULL for a later re-run. One bad batch never aborts the backfill."""
    select_response = SimpleNamespace(data=[_row(1), _row(2)])
    client = _FakeClient([select_response])  # no updates — batch fails first
    openai_service = _FakeOpenAIService(raise_on_call=True)

    summary = run_backfill(
        client=client,
        openai_service=openai_service,
        table="cached_jobs",
        batch_size=100,
        description_chars=2000,
        limit=0,
        dry_run=False,
    )

    assert summary["batches_total"] == 1
    assert summary["batches_failed"] == 1
    assert summary["rows_failed"] == 2
    assert summary["rows_embedded"] == 0
    # The select happened; no update queries were issued.
    assert len(client.queries) == 1


def test_run_backfill_skips_batch_on_vector_count_mismatch():
    """If the API returns a different vector count than inputs sent, the
    batch is skipped — pairing the wrong vector to a job is worse than
    leaving it NULL."""
    select_response = SimpleNamespace(data=[_row(1), _row(2), _row(3)])
    client = _FakeClient([select_response])
    # Returns only 2 vectors for 3 inputs.
    openai_service = _FakeOpenAIService(vector_count_override=2)

    summary = run_backfill(
        client=client,
        openai_service=openai_service,
        table="cached_jobs",
        batch_size=100,
        description_chars=2000,
        limit=0,
        dry_run=False,
    )

    assert summary["batches_failed"] == 1
    assert summary["rows_failed"] == 3
    assert summary["rows_embedded"] == 0


def test_run_backfill_continues_when_a_single_write_fails():
    """A per-row write failure is isolated: the other rows still land,
    and the failed row is counted so the run exits non-zero."""

    class _PartialFailClient(_FakeClient):
        def table(self, name):
            query = super().table(name)
            # Make the update for row id=11 raise on execute.
            original_execute = query.execute

            def maybe_fail():
                eq_calls = [c for c in query.calls if c[0] == "eq"]
                if eq_calls and eq_calls[-1][2] == 11:
                    raise RuntimeError("supabase write 500")
                return original_execute()

            query.execute = maybe_fail
            return query

    select_response = SimpleNamespace(data=[_row(10), _row(11), _row(12)])
    client = _PartialFailClient(
        [select_response] + [SimpleNamespace(data=[]) for _ in range(3)]
    )
    openai_service = _FakeOpenAIService()

    summary = run_backfill(
        client=client,
        openai_service=openai_service,
        table="cached_jobs",
        batch_size=100,
        description_chars=2000,
        limit=0,
        dry_run=False,
    )

    # Rows 10 and 12 written; row 11 failed.
    assert summary["rows_embedded"] == 2
    assert summary["rows_failed"] == 1


def test_run_backfill_limit_caps_rows_via_query():
    """--limit threads through to the select query's .limit() call."""
    client = _FakeClient([SimpleNamespace(data=[])])
    openai_service = _FakeOpenAIService()

    run_backfill(
        client=client,
        openai_service=openai_service,
        table="cached_jobs",
        batch_size=100,
        description_chars=2000,
        limit=25,
        dry_run=True,
    )

    select_query = client.queries[0]
    assert ("limit", 25) in select_query.calls


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
