"""Hermetic tests for the OpenRouterEvalService adapter.

No live network call — all tests use a stubbed Chat-Completions
client that returns canned responses. The unit under test is the
tool-loop translation logic: Responses-API tool spec ↔ Chat
Completions tool spec, OpenAI ``function_call`` items ↔
Chat Completions ``message.tool_calls`` + ``role:"tool"`` results.

These are what catch regressions in the adapter without paying for
live API calls on every CI run. The actual head-to-head OpenAI vs
Anthropic comparison lives in the agentic_runner with
``--provider openrouter`` and runs against the live API on demand.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.errors import AgentExecutionError
from tests.quality.openrouter_eval_service import (
    OpenRouterEvalService,
    _parse_provider_json,
    _translate_tools_to_chat_completions,
)


# ---------------------------------------------------------------------------
# _parse_provider_json — the markdown-fence + balanced-brace fallback
# parser. The first multi-provider eval run found this matters: Sonnet
# 4.5 via OpenRouter consistently wraps JSON in ```json ... ``` fences
# even when ``response_format=json_object`` is set, because Anthropic
# models don't honor that hint the way OpenAI/Mistral do.
# ---------------------------------------------------------------------------


def test_parse_provider_json_handles_bare_json():
    """Fast path — bare JSON passes through json.loads."""
    assert _parse_provider_json('{"reply": "hi"}') == {"reply": "hi"}


def test_parse_provider_json_strips_markdown_fence_with_lang_tag():
    """The Sonnet-through-OpenRouter case: ```json\n{...}\n```."""
    content = '```json\n{"reply": "hi", "n": 1}\n```'
    assert _parse_provider_json(content) == {"reply": "hi", "n": 1}


def test_parse_provider_json_strips_bare_fence_no_lang_tag():
    content = '```\n{"reply": "hi"}\n```'
    assert _parse_provider_json(content) == {"reply": "hi"}


def test_parse_provider_json_strips_fence_with_uppercase_lang_tag():
    """Some providers emit ```JSON instead of ```json."""
    content = '```JSON\n{"reply": "hi"}\n```'
    assert _parse_provider_json(content) == {"reply": "hi"}


def test_parse_provider_json_extracts_balanced_braces_from_prose():
    """When neither bare nor fenced parsing works, fall through to
    pulling the first balanced ``{...}`` substring."""
    content = "Here is your response: {\"reply\": \"hi\"} — let me know!"
    assert _parse_provider_json(content) == {"reply": "hi"}


def test_parse_provider_json_handles_braces_inside_string_literals():
    """The balanced-brace extractor must NOT count braces inside JSON
    string literals (e.g. ``"text": "use { for braces"``)."""
    content = 'Prelude... {"key": "value with } and { inside"} trailing'
    assert _parse_provider_json(content) == {"key": "value with } and { inside"}


def test_parse_provider_json_raises_on_empty_content():
    with pytest.raises(ValueError, match="Empty"):
        _parse_provider_json("")


def test_parse_provider_json_raises_on_nothing_parseable():
    with pytest.raises(ValueError, match="Could not parse"):
        _parse_provider_json("the model returned only prose, no json at all")


def test_run_tool_loop_accepts_markdown_fenced_response():
    """End-to-end: when the stub Chat-Completions response wraps JSON
    in a markdown fence (the Sonnet-via-OpenRouter pattern), the
    loop should still parse + return the payload — NOT raise
    ``invalid JSON``."""
    fenced_body = '```json\n{"assistant_message": "Hi", "draft_updates": {}}\n```'
    svc = _build_service(
        [_make_response(content=fenced_body, tool_calls=[])]
    )
    payload, trace = svc.run_tool_loop(
        "s", "u", tools=[], tool_executor=lambda n, a: "",
        expected_keys=["assistant_message"],
    )
    assert payload == {"assistant_message": "Hi", "draft_updates": {}}
    assert trace == []


# ---------------------------------------------------------------------------
# Translation helpers
# ---------------------------------------------------------------------------


def test_translate_tools_wraps_function_specs():
    """Responses-API flat shape gets wrapped under ``function`` for
    Chat Completions."""
    responses_shape = [
        {
            "type": "function",
            "name": "fetch_github_readme",
            "description": "Fetch a README.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        }
    ]
    translated = _translate_tools_to_chat_completions(responses_shape)
    assert len(translated) == 1
    spec = translated[0]
    assert spec["type"] == "function"
    assert spec["function"]["name"] == "fetch_github_readme"
    assert spec["function"]["description"] == "Fetch a README."
    assert spec["function"]["parameters"]["required"] == ["url"]


def test_translate_tools_drops_server_side_builtins():
    """OpenAI's built-in tools (web_search, code_interpreter, etc.) have
    no Chat Completions equivalent — drop them rather than break the
    request."""
    mixed = [
        {"type": "function", "name": "foo", "description": "", "parameters": {}},
        {"type": "web_search"},
        {"type": "code_interpreter"},
    ]
    translated = _translate_tools_to_chat_completions(mixed)
    assert len(translated) == 1
    assert translated[0]["function"]["name"] == "foo"


def test_translate_tools_handles_empty_input():
    assert _translate_tools_to_chat_completions([]) == []
    assert _translate_tools_to_chat_completions(None) == []  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Stub Chat-Completions client + response builders
# ---------------------------------------------------------------------------


def _make_tool_call(*, call_id: str, name: str, arguments: str | dict):
    """Build a fake tool_call entry matching the OpenAI SDK's shape."""
    args_str = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=args_str),
    )


def _make_response(*, content=None, tool_calls=None, usage=None):
    message = SimpleNamespace(
        content=content,
        tool_calls=tool_calls,
    )
    choice = SimpleNamespace(message=message, finish_reason="stop")
    return SimpleNamespace(
        choices=[choice],
        usage=usage or SimpleNamespace(
            prompt_tokens=10, completion_tokens=5, total_tokens=15
        ),
    )


class _StubChatClient:
    """Captures every chat.completions.create call payload + returns
    canned responses from a queue."""

    def __init__(self, response_queue):
        self._queue = list(response_queue)
        self.calls: list[dict] = []

        class _Completions:
            def __init__(_self, outer):
                _self._outer = outer

            def create(_self, **payload):
                _self._outer.calls.append(payload)
                if not _self._outer._queue:
                    raise AssertionError(
                        "Stub ran out of canned responses — test misconfigured."
                    )
                return _self._outer._queue.pop(0)

        self.chat = SimpleNamespace(completions=_Completions(self))


def _build_service(response_queue):
    """Build an OpenRouterEvalService backed by the stub client."""
    return OpenRouterEvalService(
        api_key="stub-key",
        client=_StubChatClient(response_queue),
    )


# ---------------------------------------------------------------------------
# run_tool_loop — happy paths
# ---------------------------------------------------------------------------


def test_run_tool_loop_returns_immediately_when_no_tool_calls():
    """The model returns a JSON envelope with no tool_calls on iteration
    one → loop parses and returns; never executes any tool."""
    expected_payload = {"assistant_message": "Hi", "draft_updates": {}}
    svc = _build_service(
        [_make_response(content=json.dumps(expected_payload), tool_calls=[])]
    )

    def _no_op_executor(name, args_json):
        raise AssertionError("Executor should NOT be called on a no-tool turn.")

    payload, trace = svc.run_tool_loop(
        "system",
        "user",
        tools=[],
        tool_executor=_no_op_executor,
        expected_keys=["assistant_message"],
    )
    assert payload == expected_payload
    assert trace == []


def test_run_tool_loop_dispatches_tool_call_and_continues():
    """Iteration 1: model emits a tool_call. The loop runs the
    executor, builds a role:"tool" message, sends iteration 2 with
    the full context. Iteration 2 returns the final JSON envelope."""
    executed_args: dict = {}

    def _executor(name, args_json):
        executed_args["name"] = name
        executed_args["args"] = json.loads(args_json)
        return json.dumps({"ok": True, "readme": "stub README content"})

    final_payload = {"assistant_message": "Read the readme.", "draft_updates": {}}
    svc = _build_service(
        [
            _make_response(
                content="",
                tool_calls=[
                    _make_tool_call(
                        call_id="call_001",
                        name="fetch_github_readme",
                        arguments={"url": "https://github.com/x/y"},
                    )
                ],
            ),
            _make_response(content=json.dumps(final_payload), tool_calls=[]),
        ]
    )
    tools = [
        {
            "type": "function",
            "name": "fetch_github_readme",
            "description": "fetch",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        }
    ]

    payload, trace = svc.run_tool_loop(
        "system",
        "user",
        tools=tools,
        tool_executor=_executor,
        expected_keys=["assistant_message"],
    )

    assert payload == final_payload
    assert executed_args == {"name": "fetch_github_readme", "args": {"url": "https://github.com/x/y"}}
    assert len(trace) == 1
    assert trace[0]["name"] == "fetch_github_readme"

    # Verify the iteration-2 messages carry the assistant tool_calls
    # turn AND the role:"tool" result message — both REQUIRED by Chat
    # Completions for proper tool-loop semantics.
    second_call_messages = svc._client.calls[1]["messages"]  # type: ignore[attr-defined]
    roles_in_order = [m["role"] for m in second_call_messages]
    assert "assistant" in roles_in_order
    assert "tool" in roles_in_order
    tool_msg = next(m for m in second_call_messages if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == "call_001"
    assert "stub README" in tool_msg["content"]


def test_run_tool_loop_handles_parallel_tool_calls_in_one_iteration():
    """Chat Completions can emit multiple tool_calls in a single
    response. The loop must execute all of them, append all results,
    and only THEN make the next call."""
    executed: list[str] = []

    def _executor(name, args_json):
        executed.append(name + ":" + args_json)
        return json.dumps({"ok": True, "name": name})

    final_payload = {"assistant_message": "Done.", "draft_updates": {}}
    svc = _build_service(
        [
            _make_response(
                content="",
                tool_calls=[
                    _make_tool_call(call_id="a", name="t1", arguments={"x": 1}),
                    _make_tool_call(call_id="b", name="t2", arguments={"y": 2}),
                ],
            ),
            _make_response(content=json.dumps(final_payload), tool_calls=[]),
        ]
    )

    tools = [
        {"type": "function", "name": "t1", "description": "", "parameters": {}},
        {"type": "function", "name": "t2", "description": "", "parameters": {}},
    ]

    payload, trace = svc.run_tool_loop(
        "s",
        "u",
        tools=tools,
        tool_executor=_executor,
        expected_keys=["assistant_message"],
    )
    assert payload == final_payload
    assert len(executed) == 2
    assert len(trace) == 2

    # Both tool messages must be in the second-call message list.
    messages = svc._client.calls[1]["messages"]  # type: ignore[attr-defined]
    tool_msgs = [m for m in messages if m["role"] == "tool"]
    assert len(tool_msgs) == 2
    assert {m["tool_call_id"] for m in tool_msgs} == {"a", "b"}


# ---------------------------------------------------------------------------
# run_tool_loop — error paths
# ---------------------------------------------------------------------------


def test_run_tool_loop_raises_on_invalid_json_content():
    svc = _build_service(
        [_make_response(content="not json", tool_calls=[])]
    )
    with pytest.raises(AgentExecutionError, match="invalid JSON"):
        svc.run_tool_loop(
            "s", "u", tools=[], tool_executor=lambda n, a: "", expected_keys=[]
        )


def test_run_tool_loop_raises_on_missing_expected_keys():
    svc = _build_service(
        [_make_response(content=json.dumps({"assistant_message": "Hi"}), tool_calls=[])]
    )
    with pytest.raises(AgentExecutionError, match="missing required keys"):
        svc.run_tool_loop(
            "s",
            "u",
            tools=[],
            tool_executor=lambda n, a: "",
            expected_keys=["assistant_message", "missing_key"],
        )


def test_run_tool_loop_raises_on_iteration_cap_exhaustion():
    """If the model keeps emitting tool_calls past the cap, the loop
    raises so the caller (resume-builder service) can fall back."""
    # Build infinite stub queue of tool-call responses.
    queue = [
        _make_response(
            content="",
            tool_calls=[_make_tool_call(call_id=f"c{i}", name="t", arguments={})],
        )
        for i in range(20)
    ]
    svc = _build_service(queue)
    tools = [{"type": "function", "name": "t", "description": "", "parameters": {}}]

    def _executor(name, args_json):
        return json.dumps({"ok": True})

    with pytest.raises(AgentExecutionError, match="iteration cap"):
        svc.run_tool_loop(
            "s",
            "u",
            tools=tools,
            tool_executor=_executor,
            expected_keys=[],
            max_iterations=3,
        )


def test_run_tool_loop_raises_when_unavailable():
    svc = OpenRouterEvalService(api_key="")  # no client, no key
    with pytest.raises(AgentExecutionError, match="not configured"):
        svc.run_tool_loop(
            "s", "u", tools=[], tool_executor=lambda n, a: "", expected_keys=[]
        )


# ---------------------------------------------------------------------------
# Tool executor exception → captured, not raised across the boundary
# ---------------------------------------------------------------------------


def test_run_tool_loop_captures_executor_exception_as_tool_output():
    """If the tool_executor raises, the loop must convert it into a
    tool output the model can react to (same contract as
    OpenAIService.run_tool_loop)."""

    def _bad_executor(name, args_json):
        raise RuntimeError("kaboom")

    final_payload = {"assistant_message": "Recovered.", "draft_updates": {}}
    svc = _build_service(
        [
            _make_response(
                content="",
                tool_calls=[_make_tool_call(call_id="c1", name="t", arguments={})],
            ),
            _make_response(content=json.dumps(final_payload), tool_calls=[]),
        ]
    )
    tools = [{"type": "function", "name": "t", "description": "", "parameters": {}}]

    payload, trace = svc.run_tool_loop(
        "s",
        "u",
        tools=tools,
        tool_executor=_bad_executor,
        expected_keys=["assistant_message"],
    )
    assert payload == final_payload
    # The exception was captured as a structured error in the tool_trace.
    assert trace[0]["output"]
    parsed = json.loads(trace[0]["output"])
    assert parsed["ok"] is False
    assert parsed["error"] == "executor_exception"


# ---------------------------------------------------------------------------
# is_available
# ---------------------------------------------------------------------------


def test_is_available_true_with_api_key():
    assert OpenRouterEvalService(api_key="some-key").is_available() is True


def test_is_available_false_without_key_or_client(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    assert OpenRouterEvalService(api_key="").is_available() is False
