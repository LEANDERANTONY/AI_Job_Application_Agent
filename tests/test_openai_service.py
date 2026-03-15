from types import SimpleNamespace

import pytest

from src.errors import AgentExecutionError
from src.openai_service import OpenAIService


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


def test_openai_service_retries_without_temperature_when_model_rejects_it():
    client = FakeClient(
        [
            RuntimeError(
                "Error code: 400 - {'error': {'message': \"Unsupported parameter: 'temperature' is not supported with this model.\"}}"
            ),
            _build_response('{"approved": true}', response_id="resp_retry"),
        ]
    )
    service = OpenAIService(client=client)

    payload = service.run_json_prompt("system", "user", expected_keys=["approved"], temperature=0.2)

    assert payload["approved"] is True
    assert len(client.responses.calls) == 2
    assert client.responses.calls[0]["temperature"] == 0.2
    assert "temperature" not in client.responses.calls[1]
    assert client.responses.calls[1]["reasoning"] == {"effort": "medium"}


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


def test_openai_service_uses_high_reasoning_for_high_trust_tasks():
    client = FakeClient([_build_response('{"approved": true}', response_id="resp_high")])
    service = OpenAIService(client=client)

    payload = service.run_json_prompt("system", "user", expected_keys=["approved"], task_name="review")

    assert payload["approved"] is True
    assert client.responses.calls[0]["reasoning"] == {"effort": "high"}


def test_openai_service_uses_low_reasoning_for_product_help_tasks():
    client = FakeClient([_build_response('{"approved": true}', response_id="resp_low")])
    service = OpenAIService(client=client)

    payload = service.run_json_prompt(
        "system",
        "user",
        expected_keys=["approved"],
        task_name="assistant_product_help",
        temperature=None,
    )

    assert payload["approved"] is True
    assert client.responses.calls[0]["reasoning"] == {"effort": "low"}
    assert "temperature" not in client.responses.calls[0]


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