"""Hermetic tests for the Kimi eval adapter (no network).

Injects a fake chat-completions client so the OpenAIService
duck-type + the provider-fidelity counter are verified-ready before
a real KIMI_API_KEY is supplied.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from src.errors import AgentExecutionError
from tests.quality.kimi_eval_service import KimiEvalService


def _completion(content: str, *, finish="stop", pt=10, ct=5):
    return SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=content), finish_reason=finish)],
        usage=SimpleNamespace(prompt_tokens=pt, completion_tokens=ct),
    )


class _FakeChatClient:
    def __init__(self, queued):
        self._q = list(queued)
        self.calls = []

        outer = self

        class _Completions:
            def create(self, **kwargs):
                outer.calls.append(kwargs)
                r = outer._q.pop(0)
                if isinstance(r, Exception):
                    raise r
                return r

        self.chat = SimpleNamespace(completions=_Completions())


def _svc(queued):
    return KimiEvalService(api_key="k", client=_FakeChatClient(queued))


class _Approval(BaseModel):
    approved: bool


def test_is_available_and_policy():
    assert KimiEvalService(api_key="").is_available() is False
    s = _svc([])
    assert s.is_available() is True
    assert "kimi" in s.describe_model_policy()


def test_run_json_prompt_happy_records_fidelity_and_usage():
    s = _svc([_completion('{"answer": "ok", "sources": []}')])
    out = s.run_json_prompt("sys", "usr", expected_keys=["answer", "sources"],
                            task_name="assistant")
    assert out == {"answer": "ok", "sources": []}
    snap = s.get_usage_snapshot()
    assert snap["request_count"] == 1 and snap["total_tokens"] == 15
    fid = snap["fidelity"]["assistant"]
    assert fid["calls"] == 1 and fid["schema_ok"] == 1
    assert fid["usable_rate"] == 1.0
    # JSON mode was actually requested.
    assert s._client.calls[0]["response_format"] == {"type": "json_object"}


def test_invalid_json_raises_and_counts_content_failure():
    s = _svc([_completion('{"answer": ')])
    with pytest.raises(AgentExecutionError) as e:
        s.run_json_prompt("sys", "usr", expected_keys=["answer"], task_name="job")
    assert "invalid json" in e.value.user_message.lower()
    fid = s.get_fidelity_report()["job"]
    assert fid["valid_json"] == 0 and fid["content_failures"] == 1
    assert fid["usable_rate"] == 0.0


def test_missing_keys_raises_and_counts():
    s = _svc([_completion('{"answer": "x"}')])
    with pytest.raises(AgentExecutionError) as e:
        s.run_json_prompt("sys", "usr", expected_keys=["answer", "sources"],
                          task_name="profile")
    assert "missing required fields" in e.value.user_message.lower()
    fid = s.get_fidelity_report()["profile"]
    assert fid["valid_json"] == 1 and fid["schema_ok"] == 0
    assert fid["content_failures"] == 1


def test_structured_prompt_happy_and_schema_drift():
    s = _svc([
        _completion('{"approved": true}'),
        _completion('{"approved": "not-a-bool-ish", "x": 1}'),
        _completion('{"nope": 1}'),
    ])
    ok = s.run_structured_prompt("sys", "usr", response_model=_Approval,
                                 task_name="review")
    assert ok.approved is True
    # pydantic coerces "true"-ish? "not-a-bool-ish" is NOT coercible → drift.
    with pytest.raises(AgentExecutionError) as e:
        s.run_structured_prompt("sys", "usr", response_model=_Approval,
                                task_name="review")
    assert "schema" in e.value.user_message.lower()
    with pytest.raises(AgentExecutionError):
        s.run_structured_prompt("sys", "usr", response_model=_Approval,
                                task_name="review")
    fid = s.get_fidelity_report()["review"]
    assert fid["calls"] == 3 and fid["schema_ok"] == 1
    assert fid["content_failures"] == 2
    assert fid["usable_rate"] == round(1 / 3, 3)


def test_truncation_is_counted():
    s = _svc([_completion('{"answer": "x"}', finish="length")])
    s.run_json_prompt("sys", "usr", expected_keys=["answer"], task_name="cover_letter")
    assert s.get_fidelity_report()["cover_letter"]["truncated"] == 1


def test_signature_accepts_everything_agents_pass():
    """ReviewAgent passes model=/reasoning_effort=/metadata=/
    max_completion_tokens=; parsers pass expected_keys=/temperature=.
    All must be absorbed without error (duck-type contract)."""
    s = _svc([_completion('{"approved": true}')])
    s.run_structured_prompt(
        "sys", "usr", response_model=_Approval, task_name="review",
        max_completion_tokens=4000, model="gpt-5.4", metadata={"x": 1},
        allow_output_budget_retry=True, previous_response_id=None,
        reasoning_effort="high",
    )
    assert s.get_fidelity_report()["review"]["schema_ok"] == 1
