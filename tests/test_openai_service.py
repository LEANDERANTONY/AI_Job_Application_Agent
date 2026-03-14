from types import SimpleNamespace

import pytest

from src.errors import AgentExecutionError
from src.openai_service import OpenAIService


class FakeCompletions:
    def __init__(self, responses):
        self._responses = list(responses)

    def create(self, **kwargs):
        return self._responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.responses = FakeCompletions(responses)


def _build_response(content, *, response_id="resp_1", prompt_tokens=10, completion_tokens=5):
    return SimpleNamespace(
        id=response_id,
        status="completed",
        output_text=content,
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
                content=[
                    SimpleNamespace(type="output_text", text=content),
                ],
            )
        ],
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