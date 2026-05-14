"""Cost-per-LLM-call recording tests.

Three layers of coverage:

  * ``compute_call_cost_usd`` returns the right USD figure for each
    model in the pricing map. Drift in the pricing map is the single
    most common cause of stale COGS numbers — these are unit tests so
    a price change without a code change can't slip past CI.
  * ``record_trace`` writes through to the in-memory backend with the
    right shape, swallows backend errors, and respects the
    ``user_id`` nullable column.
  * The ``OpenAIService`` integration: when a ``user_id`` is configured
    on the service, every successful call writes a cost row via the
    bridge. When the ``cost_trace_recorder`` callable is injected,
    rows go there instead of the real recorder.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from backend import run_traces
from backend.run_traces import TraceRecord, record_trace, reset_in_memory_backend
from src.errors import AgentExecutionError
from src.openai_service import (
    OpenAIService,
    compute_call_cost_usd,
    _MODEL_PRICING_USD_PER_MILLION,
)
from src.schemas_llm_outputs import TailoringOutput


# ---------------------------------------------------------------------
# Fake OpenAI client (same shape as test_structured_outputs.py)
# ---------------------------------------------------------------------


class _FakeCompletions:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(dict(kwargs))
        return self._responses.pop(0)


class _FakeClient:
    def __init__(self, responses):
        self.responses = _FakeCompletions(responses)


def _build_response(content: str, *, prompt_tokens: int = 100, completion_tokens: int = 50) -> SimpleNamespace:
    return SimpleNamespace(
        id="resp_cost_1",
        status="completed",
        output_text=content,
        incomplete_details=None,
        usage=SimpleNamespace(
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            output_tokens_details=SimpleNamespace(reasoning_tokens=0),
        ),
        output=[
            SimpleNamespace(
                type="message",
                role="assistant",
                content=[SimpleNamespace(type="output_text", text=content)],
            )
        ],
    )


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_in_memory_backend(monkeypatch):
    """Force every test onto the in-memory backend with a fresh state.

    Mirrors the ``_fresh_quota_store`` fixture in
    ``test_quota.py``. Forcing ``_SUPABASE_BACKEND.is_configured() →
    False`` defends against a local shell that happens to have prod
    Supabase credentials in the environment."""
    monkeypatch.setattr(
        run_traces, "_SUPABASE_BACKEND", _NeverConfiguredBackend()
    )
    reset_in_memory_backend()
    yield
    reset_in_memory_backend()


class _NeverConfiguredBackend:
    def is_configured(self) -> bool:
        return False


# ---------------------------------------------------------------------
# compute_call_cost_usd
# ---------------------------------------------------------------------


def test_pricing_map_carries_all_four_known_models():
    assert set(_MODEL_PRICING_USD_PER_MILLION.keys()) == {
        "gpt-5.4-nano",
        "gpt-5.4-mini",
        "gpt-5.4",
        "gpt-5.5",
    }


def test_compute_cost_for_nano_per_million_baseline():
    """gpt-5.4-nano: $0.10 / $0.40 per 1M (in / out). 1M each =
    $0.10 input + $0.40 output = $0.50."""
    cost = compute_call_cost_usd("gpt-5.4-nano", 1_000_000, 1_000_000)
    assert cost == 0.5


def test_compute_cost_for_mini_typical_call():
    """gpt-5.4-mini: $0.75 / $4.50 per 1M.
    1000 input + 500 output → 0.001 * 0.75 + 0.0005 * 4.50 = $0.003."""
    cost = compute_call_cost_usd("gpt-5.4-mini", 1000, 500)
    assert cost == pytest.approx(0.003, rel=1e-6)


def test_compute_cost_for_high_trust_call():
    """gpt-5.4: $2 / $10 per 1M.
    5000 input + 2000 output → 0.005 * 2 + 0.002 * 10 = $0.03."""
    cost = compute_call_cost_usd("gpt-5.4", 5000, 2000)
    assert cost == pytest.approx(0.03, rel=1e-6)


def test_compute_cost_for_premium_call():
    """gpt-5.5: $5 / $30 per 1M.
    10000 input + 5000 output → 0.01 * 5 + 0.005 * 30 = $0.20."""
    cost = compute_call_cost_usd("gpt-5.5", 10000, 5000)
    assert cost == pytest.approx(0.20, rel=1e-6)


def test_compute_cost_unknown_model_returns_zero():
    """Unknown model names produce $0 — the row is still recorded so
    we can backfill, but the cost field doesn't bias COGS rollups
    silently."""
    assert compute_call_cost_usd("gpt-99", 1000, 1000) == 0.0


def test_compute_cost_handles_zero_tokens():
    assert compute_call_cost_usd("gpt-5.4-mini", 0, 0) == 0.0


def test_compute_cost_rejects_negative_tokens_as_zero():
    """Defensive: a negative token count shouldn't produce a negative
    cost. We floor at zero rather than raise so a malformed usage
    object can't kill the recording path."""
    assert compute_call_cost_usd("gpt-5.4-mini", -5, 100) == pytest.approx(0.00045, rel=1e-6)


def test_compute_cost_rounds_to_six_decimals():
    """SQL column is numeric(10,6); the helper rounds here so the
    in-memory backend's rows match what's persisted byte-for-byte."""
    cost = compute_call_cost_usd("gpt-5.4-mini", 1, 1)
    # 0.00000075 + 0.0000045 = 5.25e-6 → 0.000005 after rounding.
    assert cost == 0.000005


# ---------------------------------------------------------------------
# record_trace (in-memory backend)
# ---------------------------------------------------------------------


def test_record_trace_writes_row_to_in_memory_backend():
    record_trace(
        task_name="tailoring",
        model_name="gpt-5.4-mini",
        prompt_tokens=1000,
        completion_tokens=500,
        cost_usd=0.003,
        user_id="user-abc",
    )
    rows = run_traces.in_memory_rows()
    assert len(rows) == 1
    row = rows[0]
    assert row["task_name"] == "tailoring"
    assert row["model_name"] == "gpt-5.4-mini"
    assert row["prompt_tokens"] == 1000
    assert row["completion_tokens"] == 500
    assert row["cost_usd"] == pytest.approx(0.003, rel=1e-6)
    assert row["user_id"] == "user-abc"
    assert row["success"] is True


def test_record_trace_accepts_null_user_id():
    """The DB schema permits NULL on user_id; the application path
    should be able to record a trace without an auth context (e.g.
    background admin jobs). The row still has all the other fields."""
    record_trace(
        task_name="admin_refresh",
        model_name="gpt-5.4-mini",
        prompt_tokens=10,
        completion_tokens=5,
        cost_usd=0.0001,
        user_id=None,
    )
    rows = run_traces.in_memory_rows()
    assert len(rows) == 1
    assert rows[0]["user_id"] is None


def test_record_trace_swallows_backend_errors(monkeypatch):
    """A backend exception must not propagate — cost tracking is
    best-effort, and a Supabase outage shouldn't turn a successful
    OpenAI call into a workflow failure."""
    class _ExplodingBackend:
        def is_configured(self) -> bool:
            return True

        def insert(self, record: TraceRecord) -> None:
            raise RuntimeError("simulated supabase outage")

    monkeypatch.setattr(run_traces, "_SUPABASE_BACKEND", _ExplodingBackend())
    # Should NOT raise.
    record_trace(
        task_name="tailoring",
        model_name="gpt-5.4-mini",
        prompt_tokens=10,
        completion_tokens=5,
        cost_usd=0.0001,
        user_id="user-a",
    )


def test_record_trace_marks_failed_calls():
    record_trace(
        task_name="tailoring",
        model_name="gpt-5.4-mini",
        prompt_tokens=100,
        completion_tokens=0,
        cost_usd=0.0001,
        user_id="user-a",
        success=False,
    )
    rows = run_traces.in_memory_rows()
    assert rows[0]["success"] is False


# ---------------------------------------------------------------------
# OpenAIService integration — does it actually call the bridge?
# ---------------------------------------------------------------------


def test_run_json_prompt_records_cost_trace_via_recorder_when_user_id_set():
    """When ``user_id`` is configured AND a ``cost_trace_recorder``
    callable is supplied, every successful call hands a payload to
    the recorder (and skips the real ``backend.run_traces.record_trace``
    path)."""
    payload_json = json.dumps({"approved": True})
    captured: list[dict] = []
    client = _FakeClient(
        [_build_response(payload_json, prompt_tokens=1000, completion_tokens=500)]
    )
    service = OpenAIService(
        client=client,
        user_id="user-test",
        cost_trace_recorder=captured.append,
    )
    service.run_json_prompt("system", "user", expected_keys=["approved"])

    assert len(captured) == 1
    trace = captured[0]
    assert trace["task_name"] == ""  # no task_name passed
    assert trace["model_name"] == service.default_model
    assert trace["prompt_tokens"] == 1000
    assert trace["completion_tokens"] == 500
    assert trace["user_id"] == "user-test"
    assert trace["success"] is True
    # gpt-5.4-mini is the default; 1000 in + 500 out = $0.003.
    assert trace["cost_usd"] == pytest.approx(0.003, rel=1e-6)


def test_run_structured_prompt_records_cost_trace():
    payload_json = json.dumps(
        {
            "professional_summary": "",
            "rewritten_bullets": [],
            "highlighted_skills": [],
            "cover_letter_themes": [],
        }
    )
    captured: list[dict] = []
    client = _FakeClient(
        [_build_response(payload_json, prompt_tokens=200, completion_tokens=100)]
    )
    service = OpenAIService(
        client=client,
        user_id="user-test",
        cost_trace_recorder=captured.append,
    )
    service.run_structured_prompt(
        "system",
        "user",
        response_model=TailoringOutput,
        task_name="tailoring",
    )
    assert len(captured) == 1
    assert captured[0]["task_name"] == "tailoring"
    assert captured[0]["prompt_tokens"] == 200
    assert captured[0]["completion_tokens"] == 100


def test_cost_trace_skipped_when_no_user_id_and_no_recorder():
    """Without a ``user_id`` AND without a test recorder, the bridge
    is a no-op — we don't pollute the in-memory store with anonymous
    rows that wouldn't have made it to Supabase either."""
    payload_json = json.dumps({"approved": True})
    client = _FakeClient([_build_response(payload_json)])
    service = OpenAIService(client=client)  # no user_id, no recorder
    service.run_json_prompt("system", "user", expected_keys=["approved"])
    assert run_traces.in_memory_rows() == []


def test_cost_trace_recorder_errors_are_logged_and_swallowed(caplog):
    """An exception inside the recorder must not blow up the OpenAI
    call — log + swallow, parity with ``_record_usage_event``."""

    def _exploding(payload):
        raise RuntimeError("recorder is broken")

    payload_json = json.dumps({"approved": True})
    client = _FakeClient([_build_response(payload_json)])
    service = OpenAIService(
        client=client,
        user_id="user-test",
        cost_trace_recorder=_exploding,
    )
    # Should not raise.
    payload = service.run_json_prompt("system", "user", expected_keys=["approved"])
    assert payload == {"approved": True}


def test_in_memory_backend_isolates_tests():
    """Sanity: after a test writes a row, the autouse fixture must
    have wiped it before the next test runs."""
    assert run_traces.in_memory_rows() == []
    record_trace(
        task_name="tailoring",
        model_name="gpt-5.4-mini",
        prompt_tokens=10,
        completion_tokens=5,
        cost_usd=0.0001,
        user_id="user-isolated",
    )
    assert len(run_traces.in_memory_rows()) == 1


# ---------------------------------------------------------------------
# RLS / backend selection — documents the contract from the migration
# ---------------------------------------------------------------------


def test_select_backend_picks_in_memory_when_supabase_unconfigured(monkeypatch):
    """When SUPABASE_URL / SERVICE_ROLE_KEY aren't set,
    ``_select_backend`` falls back to the in-memory store. This
    mirrors the behavior in ``backend/quota.py`` — the same code path
    runs in tests as in production, the data just lives in different
    places."""
    backend = run_traces._select_backend()
    # The autouse fixture replaced _SUPABASE_BACKEND with a never-
    # configured stub, so the in-memory backend wins.
    assert backend is run_traces._IN_MEMORY_BACKEND
