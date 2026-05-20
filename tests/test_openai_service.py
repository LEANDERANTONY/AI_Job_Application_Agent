from types import SimpleNamespace

import pytest

from pydantic import BaseModel

import openai

from src.errors import AgentExecutionError, OpenAIUnavailableError
from src.openai_service import OpenAIService, _classify_openai_exception


class FakeCompletions:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(dict(kwargs))
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeClient:
    def __init__(self, responses):
        self.responses = FakeCompletions(responses)


def _build_response(
    content,
    *,
    response_id="resp_1",
    prompt_tokens=10,
    completion_tokens=5,
    status="completed",
    incomplete_reason=None,
    include_message=True,
):
    return SimpleNamespace(
        id=response_id,
        status=status,
        output_text=content,
        incomplete_details=SimpleNamespace(reason=incomplete_reason) if incomplete_reason else None,
        usage=SimpleNamespace(
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            output_tokens_details=SimpleNamespace(reasoning_tokens=0),
        ),
        output=(
            [
                SimpleNamespace(
                    type="message",
                    role="assistant",
                    content=[
                        SimpleNamespace(type="output_text", text=content),
                    ],
                )
            ]
            if include_message
            else [SimpleNamespace(type="reasoning", summary=[])]
        ),
    )


def test_openai_service_tracks_usage_across_requests():
    client = FakeClient(
        [
            _build_response('{"approved": true}', response_id="resp_1", prompt_tokens=12, completion_tokens=8),
            _build_response('{"approved": false}', response_id="resp_2", prompt_tokens=15, completion_tokens=6),
        ]
    )
    service = OpenAIService(client=client)

    first = service.run_json_prompt("system", "user", expected_keys=["approved"])
    second = service.run_json_prompt("system", "user", expected_keys=["approved"])
    usage = service.get_usage_snapshot()

    assert first["approved"] is True
    assert second["approved"] is False
    assert usage["request_count"] == 2
    assert usage["prompt_tokens"] == 27
    assert usage["completion_tokens"] == 14
    assert usage["total_tokens"] == 41
    assert usage["last_response_metadata"]["response_id"] == "resp_2"
    assert usage["model_usage"][service.default_model]["request_count"] == 2
    assert client.responses.calls[0]["reasoning"] == {"effort": "medium"}
    assert "json" in client.responses.calls[0]["input"].lower()


def test_openai_service_blocks_when_call_budget_is_reached():
    client = FakeClient([_build_response('{"approved": true}')])
    service = OpenAIService(
        client=client,
        usage_budget={"max_calls": 1, "max_total_tokens": 100},
        starting_usage={"request_count": 1, "prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
    )

    with pytest.raises(AgentExecutionError) as error:
        service.run_json_prompt("system", "user", expected_keys=["approved"])

    assert "session call limit" in error.value.user_message.lower()


def test_openai_service_blocks_when_token_budget_is_reached():
    client = FakeClient([_build_response('{"approved": true}')])
    service = OpenAIService(
        client=client,
        usage_budget={"max_calls": 5, "max_total_tokens": 20},
        starting_usage={"request_count": 1, "prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
    )

    with pytest.raises(AgentExecutionError) as error:
        service.run_json_prompt("system", "user", expected_keys=["approved"])

    assert "session token budget" in error.value.user_message.lower()


def test_openai_service_records_usage_event_after_successful_request():
    client = FakeClient([_build_response('{"approved": true}', response_id="resp_3", prompt_tokens=9, completion_tokens=4)])
    captured = []
    service = OpenAIService(client=client, usage_event_recorder=lambda payload: captured.append(payload))

    payload = service.run_json_prompt("system", "user", expected_keys=["approved"], task_name="review")

    assert payload["approved"] is True
    assert captured == [
        {
            "task_name": "review",
            "model_name": service._resolve_model(task_name="review"),
            "request_count": 1,
            "prompt_tokens": 9,
            "completion_tokens": 4,
            "total_tokens": 13,
            "response_id": "resp_3",
            "status": "completed",
        }
    ]


def test_openai_service_does_not_fail_when_usage_event_recording_breaks():
    client = FakeClient([_build_response('{"approved": true}')])
    service = OpenAIService(
        client=client,
        usage_event_recorder=lambda payload: (_ for _ in ()).throw(RuntimeError("db offline")),
    )

    payload = service.run_json_prompt("system", "user", expected_keys=["approved"])

    assert payload["approved"] is True


def test_openai_service_does_not_send_temperature_even_when_requested():
    client = FakeClient([_build_response('{"approved": true}', response_id="resp_retry")])
    service = OpenAIService(client=client)

    payload = service.run_json_prompt("system", "user", expected_keys=["approved"], temperature=0.2)

    assert payload["approved"] is True
    assert len(client.responses.calls) == 1
    assert "temperature" not in client.responses.calls[0]
    assert client.responses.calls[0]["reasoning"] == {"effort": "medium"}


def test_openai_service_retries_with_higher_output_budget_after_incomplete_response():
    client = FakeClient(
        [
            _build_response(
                "",
                response_id="resp_incomplete",
                status="incomplete",
                incomplete_reason="max_output_tokens",
                include_message=False,
            ),
            _build_response('{"approved": true}', response_id="resp_complete"),
        ]
    )
    service = OpenAIService(client=client)

    payload = service.run_json_prompt("system", "user", expected_keys=["approved"], max_completion_tokens=100)

    assert payload["approved"] is True
    assert len(client.responses.calls) == 2
    assert client.responses.calls[0]["max_output_tokens"] == 100
    assert client.responses.calls[1]["max_output_tokens"] == 500


def test_openai_service_retries_when_incomplete_response_contains_partial_json():
    client = FakeClient(
        [
            _build_response(
                '{"approved": ',
                response_id="resp_partial_json",
                status="incomplete",
                incomplete_reason="max_output_tokens",
                include_message=True,
            ),
            _build_response('{"approved": true}', response_id="resp_complete_after_partial"),
        ]
    )
    service = OpenAIService(client=client)

    payload = service.run_json_prompt("system", "user", expected_keys=["approved"], max_completion_tokens=100)

    assert payload["approved"] is True
    assert len(client.responses.calls) == 2
    assert client.responses.calls[0]["max_output_tokens"] == 100
    assert client.responses.calls[1]["max_output_tokens"] == 500


def test_openai_service_retries_when_incomplete_response_is_missing_required_fields():
    client = FakeClient(
        [
            _build_response(
                '{"answer": "partial"}',
                response_id="resp_partial_fields",
                status="incomplete",
                incomplete_reason="max_output_tokens",
                include_message=True,
            ),
            _build_response('{"answer": "done", "sources": []}', response_id="resp_complete_after_missing_fields"),
        ]
    )
    service = OpenAIService(client=client)

    payload = service.run_json_prompt(
        "system",
        "user",
        expected_keys=["answer", "sources"],
        max_completion_tokens=100,
    )

    assert payload["answer"] == "done"
    assert payload["sources"] == []
    assert len(client.responses.calls) == 2
    assert client.responses.calls[1]["max_output_tokens"] == 500


def test_openai_service_can_disable_higher_output_budget_retry():
    client = FakeClient(
        [
            _build_response(
                '{"approved": ',
                response_id="resp_partial_json_no_retry",
                status="incomplete",
                incomplete_reason="max_output_tokens",
                include_message=True,
            )
        ]
    )
    service = OpenAIService(client=client)

    with pytest.raises(AgentExecutionError) as error:
        service.run_json_prompt(
            "system",
            "user",
            expected_keys=["approved"],
            max_completion_tokens=100,
            allow_output_budget_retry=False,
        )

    assert "invalid json response" in error.value.user_message.lower()
    assert len(client.responses.calls) == 1


def test_openai_service_uses_medium_reasoning_for_review_tasks():
    client = FakeClient([_build_response('{"approved": true}', response_id="resp_high")])
    service = OpenAIService(client=client)

    payload = service.run_json_prompt("system", "user", expected_keys=["approved"], task_name="review")

    assert payload["approved"] is True
    assert client.responses.calls[0]["reasoning"] == {"effort": "medium"}


def test_openai_service_uses_default_reasoning_for_unified_assistant_task():
    # 2026-05-21: assistant default dropped from "medium" to "low"
    # after the Slice 1K eval showed gpt-5.4-mini@low matched
    # mini@medium with perfect 1.000 quality at -32% latency / -15%
    # cost on the same 12 scenarios. See
    # `docs/eval-runs/2026-05-21-assistant-eval-report.md` (addendum
    # for the head-to-head). The test asserts the resolver returns
    # the NEW default; if a future operator overrides via env var
    # they'd see the override value here, but the in-process default
    # is what production ships with.
    client = FakeClient([_build_response('{"approved": true}', response_id="resp_low")])
    service = OpenAIService(client=client)

    payload = service.run_json_prompt(
        "system",
        "user",
        expected_keys=["approved"],
        task_name="assistant",
        temperature=None,
    )

    assert payload["approved"] is True
    assert client.responses.calls[0]["reasoning"] == {"effort": "low"}
    assert "temperature" not in client.responses.calls[0]


def test_openai_service_exposes_prompt_budget_metadata_in_usage_snapshot():
    client = FakeClient([_build_response('{"approved": true}', response_id="resp_budget")])
    service = OpenAIService(client=client)

    payload = service.run_json_prompt(
        "system",
        "user",
        expected_keys=["approved"],
        metadata={
            "estimated_input_chars": "1234",
            "compacted_sections": "2",
            "compacted_labels": "Candidate Profile, Job Description",
            "prompt_budget_mode": "compacted",
        },
    )
    usage = service.get_usage_snapshot()

    assert payload["approved"] is True
    assert usage["last_response_metadata"]["estimated_input_chars"] == "1234"
    assert usage["last_response_metadata"]["compacted_sections"] == "2"
    assert usage["last_response_metadata"]["compacted_labels"] == "Candidate Profile, Job Description"
    assert usage["last_response_metadata"]["prompt_budget_mode"] == "compacted"


def test_openai_service_preserves_user_prompt_when_it_already_mentions_json():
    client = FakeClient([_build_response('{"approved": true}', response_id="resp_json_prompt")])
    service = OpenAIService(client=client)

    payload = service.run_json_prompt(
        "system",
        "Return json with the approved field.",
        expected_keys=["approved"],
    )

    assert payload["approved"] is True
    assert client.responses.calls[0]["input"] == "Return json with the approved field."


def test_openai_service_escalates_output_budget_across_multiple_steps():
    """Resilience: the budget no longer stops at a single 6000-capped
    bump. It keeps doubling until the response is complete, so a
    content-rich payload never falls back to deterministic just
    because it needed more output room."""
    client = FakeClient(
        [
            _build_response(
                "",
                response_id="inc_1",
                status="incomplete",
                incomplete_reason="max_output_tokens",
                include_message=False,
            ),
            _build_response(
                "",
                response_id="inc_2",
                status="incomplete",
                incomplete_reason="max_output_tokens",
                include_message=False,
            ),
            _build_response(
                "",
                response_id="inc_3",
                status="incomplete",
                incomplete_reason="max_output_tokens",
                include_message=False,
            ),
            _build_response('{"approved": true}', response_id="resp_done"),
        ]
    )
    service = OpenAIService(client=client)

    payload = service.run_json_prompt(
        "system", "user", expected_keys=["approved"], max_completion_tokens=100
    )

    assert payload["approved"] is True
    # Initial @100, then escalating re-issues until complete.
    budgets = [call["max_output_tokens"] for call in client.responses.calls]
    assert budgets == [100, 500, 1000, 2000]


def test_openai_service_classifies_transport_failure_as_openai_unavailable():
    """A hard transport failure is an OUTAGE, not a content failure:
    it must raise OpenAIUnavailableError so the orchestrator surfaces
    an honest notice instead of silently degrading. Still a subclass
    of AgentExecutionError so every existing handler keeps working."""
    client = FakeClient([RuntimeError("connection reset by peer")])
    service = OpenAIService(client=client)

    with pytest.raises(OpenAIUnavailableError) as error:
        service.run_json_prompt("system", "user", expected_keys=["approved"])

    assert isinstance(error.value, AgentExecutionError)


class _ApprovalModel(BaseModel):
    approved: bool


def test_run_structured_prompt_escalates_on_truncated_partial_json():
    """Parity fix: structured-output agents (tailoring, review) used
    to hard-fail on a truncated partial JSON. They must now escalate
    the budget and re-parse, same as run_json_prompt."""
    client = FakeClient(
        [
            _build_response(
                '{"approved": ',
                response_id="struct_partial",
                status="incomplete",
                incomplete_reason="max_output_tokens",
                include_message=True,
            ),
            _build_response('{"approved": true}', response_id="struct_done"),
        ]
    )
    service = OpenAIService(client=client)

    validated = service.run_structured_prompt(
        "system",
        "user",
        response_model=_ApprovalModel,
        max_completion_tokens=100,
    )

    assert validated.approved is True
    assert len(client.responses.calls) == 2
    assert client.responses.calls[1]["max_output_tokens"] == 500


def _exc(cls):
    """Instantiate an openai SDK exception for isinstance checks
    without satisfying its real (response/body) constructor."""
    return type(f"_T{cls.__name__}", (cls,), {"__init__": lambda self: None})()


def test_classify_openai_exception_maps_each_failure_to_the_right_policy():
    """Pins the intelligent-failure taxonomy. These exceptions have
    already survived the SDK's 2 retries + our app retry, so we
    classify the NATURE of what persisted: 429 → throttled, 4xx
    auth/perm/notfound → our misconfig (not an outage), 400/422 →
    a per-request content problem (None → stays per-agent, NOT a
    pipeline-wide outage), everything else → genuine outage."""
    assert _classify_openai_exception(_exc(openai.RateLimitError)) == "rate_limited"
    assert _classify_openai_exception(_exc(openai.AuthenticationError)) == "misconfigured"
    assert _classify_openai_exception(_exc(openai.PermissionDeniedError)) == "misconfigured"
    assert _classify_openai_exception(_exc(openai.NotFoundError)) == "misconfigured"
    # 400 / 422 → content problem, NOT a provider outage.
    assert _classify_openai_exception(_exc(openai.BadRequestError)) is None
    assert _classify_openai_exception(_exc(openai.UnprocessableEntityError)) is None
    # conn / timeout / 5xx / anything unrecognised → outage.
    assert _classify_openai_exception(_exc(openai.APITimeoutError)) == "outage"
    assert _classify_openai_exception(_exc(openai.InternalServerError)) == "outage"
    assert _classify_openai_exception(RuntimeError("socket reset")) == "outage"


class _BadRequest400(openai.BadRequestError):
    def __init__(self):  # bypass the SDK ctor's required args
        pass

    def __str__(self):
        return "context_length_exceeded"


def test_bad_request_becomes_content_error_not_provider_outage():
    """A 400 (e.g. prompt too long) is specific to THIS call's payload
    — it must surface as a content AgentExecutionError so it stays
    isolated to the one agent, NOT as an OpenAIUnavailableError that
    would trip the pipeline-wide circuit breaker."""
    client = FakeClient([_BadRequest400()])
    service = OpenAIService(client=client)

    with pytest.raises(AgentExecutionError) as error:
        service.run_json_prompt("system", "user", expected_keys=["approved"])

    assert not isinstance(error.value, OpenAIUnavailableError)


class _RateLimit429(openai.RateLimitError):
    def __init__(self):
        pass

    def __str__(self):
        return "rate limit exceeded"


def test_rate_limit_is_classified_outage_error_with_category():
    """A 429 that outlived the SDK's retry-after → OpenAIUnavailableError
    tagged rate_limited (the orchestrator uses the category for the
    'try again shortly' copy and to NOT keep hammering)."""
    client = FakeClient([_RateLimit429()])
    service = OpenAIService(client=client)

    with pytest.raises(OpenAIUnavailableError) as error:
        service.run_json_prompt("system", "user", expected_keys=["approved"])

    assert error.value.category == "rate_limited"


def test_reasoning_effort_override_wins_over_task_routing():
    """ADR-028 D2: an explicit reasoning_effort overrides the
    task-routed default; omitting it keeps the routed value so
    standard/free callers are unaffected. `review` routes to
    "medium"; premium passes "high"."""
    client = FakeClient(
        [
            _build_response('{"approved": true}', response_id="r_routed"),
            _build_response('{"approved": true}', response_id="r_override"),
        ]
    )
    service = OpenAIService(client=client)

    # No override → routed default for `review` ("medium").
    service.run_json_prompt(
        "system", "user", expected_keys=["approved"], task_name="review"
    )
    assert client.responses.calls[0]["reasoning"] == {"effort": "medium"}

    # Explicit override wins.
    service.run_json_prompt(
        "system",
        "user",
        expected_keys=["approved"],
        task_name="review",
        reasoning_effort="high",
    )
    assert client.responses.calls[1]["reasoning"] == {"effort": "high"}