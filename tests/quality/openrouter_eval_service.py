"""Eval-scoped OpenRouter adapter — multi-provider agentic eval.

NOT production-wired. This is the eval-time bridge that lets the
resume-builder agentic loop drive a non-OpenAI model (default:
``anthropic/claude-sonnet-4.5``) through OpenRouter's OpenAI-
Chat-Completions-compatible endpoint. It's a duck-type of
``OpenAIService.run_tool_loop`` — same call signature, same return
shape — so the existing
``tests/quality/resume_builder_agentic_runner.py`` can inject it as
the ``openai_service`` and score Claude side-by-side with GPT-5.4 on
identical scenarios.

Same-key story: OpenRouter sits in front of every provider in their
catalogue (Anthropic, Google, Mistral, the OpenAI family, Kimi, etc.).
The existing ``KimiEvalService`` already proves this pattern works for
plain JSON-prompt agents (resume parser / JD parser / analysis). What
that adapter does NOT have is ``run_tool_loop``, which is the only
surface the agentic intake actually uses. So a separate class — same
OpenRouter base_url + same env var — but with the tool-loop
translation glue between OpenAI's Responses-API shape (what the
agentic loop hands in) and Chat Completions (what OpenRouter speaks).

Two non-obvious translation details:

  - **Tool spec shape.** Responses API uses
    ``{"type":"function","name":...,"parameters":...}`` (flat).
    Chat Completions wraps it: ``{"type":"function","function":{"name":...
    "description":..., "parameters":...}}``. The translator
    ``_translate_tools_to_chat_completions`` handles the wrap.
  - **Tool call message shape.** Responses returns ``function_call``
    items in ``response.output``. Chat Completions returns
    ``message.tool_calls = [{id, type, function:{name, arguments}}]``.
    Tool results are then a separate message
    ``{role: "tool", tool_call_id, content}``. The loop iteration
    builds this message-list shape and feeds it back next iteration.

Scope deliberately small: no fidelity counters (the existing
KimiEvalService has those for the chat-completions provider eval
which is a separate question). This adapter is for OUTCOME
measurement on the agentic runner — does Sonnet fire the GitHub tool
when it should, does it produce the proactive_offer at the right
moments, does it preserve multi-turn corrections, does the
structuring-canary scenario pass.

Web search is OUT OF SCOPE for this adapter. The production
``web_search`` tool wraps an inner OpenAI Responses-API call to use
OpenAI's built-in web_search server-side tool — neither half of that
chain works through OpenRouter. The agentic runner's ``--provider
openrouter`` mode auto-skips the two web_search scenarios for
cross-provider fairness; revisit in a follow-up when an Anthropic-
native search path is wired.

Config:
    OPENROUTER_API_KEY — required (no key → is_available() False)
    OPENROUTER_BASE_URL — default https://openrouter.ai/api/v1
    OPENROUTER_MODEL — default anthropic/claude-sonnet-4.5
                       (override via --model on the runner)
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any, Callable, Iterable, Optional, Type

# Importing src.config triggers ``load_dotenv(BASE_DIR / ".env")`` so
# OPENROUTER_API_KEY (and any other project secrets) become visible
# via os.getenv. Without this import, a standalone
# ``python tests/quality/openrouter_eval_service.py`` invocation would
# see no env vars (the project's .env wouldn't auto-load).
import src.config  # noqa: F401 — side-effect import for dotenv
from src.errors import AgentExecutionError


LOGGER = logging.getLogger(__name__)


_DEFAULT_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").strip()
_DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "anthropic/claude-sonnet-4.5").strip()


# Match an optional markdown code fence at start of content, with or
# without a language tag (```json, ```, etc.). The captured group is
# the inner content; we then strip a trailing fence if present.
_MARKDOWN_FENCE_PATTERN = re.compile(
    r"^\s*```(?:json|JSON)?\s*\n?(.+?)\n?```\s*$",
    re.DOTALL,
)


def _parse_provider_json(content: str) -> Any:
    """Parse JSON from a provider response, tolerating markdown fences.

    OpenAI/Mistral models through OpenRouter honor
    ``response_format={"type":"json_object"}`` and return bare JSON.
    Anthropic models through OpenRouter often IGNORE that hint and
    return JSON wrapped in markdown fences like ``\\u0060\\u0060\\u0060json\\n{...}\\n\\u0060\\u0060\\u0060``
    — Anthropic's own API doesn't support a native JSON-mode
    constraint, so the OpenRouter shim's prompt-coerced
    "respond in JSON" reads as "format the JSON nicely".

    Strategy (each step falls through to the next on failure):
      1. ``json.loads(content)``  — fast path for compliant providers
      2. Strip markdown fences ``\\u0060\\u0060\\u0060json ... \\u0060\\u0060\\u0060`` then retry
      3. Extract the first balanced ``{...}`` substring then retry

    Raises ``ValueError`` if nothing parses — the caller wraps that
    in ``AgentExecutionError`` with the original content attached.
    """
    text = str(content or "").strip()
    if not text:
        raise ValueError("Empty response content.")

    # Fast path — bare JSON.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strip markdown fences (```json ... ``` or ``` ... ```).
    fenced = _MARKDOWN_FENCE_PATTERN.match(text)
    if fenced is not None:
        inner = fenced.group(1).strip()
        try:
            return json.loads(inner)
        except json.JSONDecodeError:
            pass

    # Last-ditch: extract the first balanced {...} substring. Walks
    # the string counting braces (string-literal aware so a brace
    # inside a JSON string doesn't throw the count off).
    start = text.find("{")
    if start >= 0:
        depth = 0
        in_str = False
        escaped = False
        for i in range(start, len(text)):
            ch = text[i]
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break

    raise ValueError(
        "Could not parse JSON from provider response (tried fast path + "
        "markdown-fence strip + balanced-brace extraction)."
    )


def _translate_tools_to_chat_completions(tools: Iterable[dict]) -> list[dict]:
    """Translate the Responses-API tool-spec shape to Chat-Completions.

    Responses uses: ``{"type":"function","name":...,"parameters":...}``
    Chat Completions wraps the function fields under a nested
    ``function`` key. Server-side built-in tools (e.g.
    ``{"type":"web_search"}``) have no Chat Completions equivalent —
    those are dropped here with a warning, and the runner's
    ``--provider openrouter`` mode is expected to skip scenarios that
    require them.
    """
    translated: list[dict] = []
    for spec in tools or []:
        if not isinstance(spec, dict):
            continue
        if spec.get("type") != "function":
            LOGGER.warning(
                "Dropping non-function tool %r — no Chat Completions equivalent.",
                spec.get("type"),
            )
            continue
        translated.append(
            {
                "type": "function",
                "function": {
                    "name": spec["name"],
                    "description": spec.get("description", ""),
                    "parameters": spec.get("parameters", {}),
                },
            }
        )
    return translated


class OpenRouterEvalService:
    """OpenAIService-duck-typed adapter that routes through OpenRouter.

    Implements only the surface the agentic eval actually exercises:
    ``is_available``, ``run_tool_loop``, ``run_json_prompt``,
    ``run_structured_prompt``. Anything the resume-builder service
    doesn't call on this object stays unimplemented by design — adding
    methods on demand keeps the eval shape small + auditable.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        client: Any = None,
    ):
        self._api_key = (
            api_key if api_key is not None else os.getenv("OPENROUTER_API_KEY", "")
        ).strip()
        self._base_url = (base_url or _DEFAULT_BASE_URL).strip()
        self.default_model = (model or _DEFAULT_MODEL).strip()
        self._client = client
        self._usage = {
            "request_count": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    def is_available(self) -> bool:
        return bool(self._api_key) or self._client is not None

    def describe_model_policy(self) -> str:
        return f"openrouter:{self.default_model}"

    def _get_client(self):
        if self._client is None:
            from openai import OpenAI

            # OpenAI SDK talks any OpenAI-compatible base_url. We pin
            # to OpenRouter; the OpenRouter API speaks Chat Completions.
            # Timeout=60s per call: a tool-loop iteration with full
            # history + reasoning is ~10-20s on a healthy provider;
            # 60s catches a slow provider quickly so one hung
            # candidate doesn't lock up the entire matrix eval.
            # max_retries=0: an OpenRouter 5xx is often a "this slug
            # is unhealthy right now" signal — retrying just doubles
            # the wait. Better to surface and move on.
            self._client = OpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
                timeout=60.0,
                max_retries=0,
            )
        return self._client

    # ------------------------------------------------------------------
    # run_tool_loop — the only path the agentic eval actually uses.
    # Mirrors OpenAIService.run_tool_loop's signature + return shape.
    # ------------------------------------------------------------------

    def run_tool_loop(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        tools: Iterable[dict],
        tool_executor: Callable[[str, str], str],
        expected_keys: Optional[Iterable[str]] = None,
        max_iterations: int = 12,
        temperature: Any = None,
        max_completion_tokens: int = 1200,
        task_name: Optional[str] = None,
        model: Optional[str] = None,
        metadata: Any = None,
        reasoning_effort: Any = None,
    ) -> tuple[dict, list[dict]]:
        """Drive a Chat-Completions tool-calling loop and return the
        parsed JSON envelope plus the trace of tool invocations.

        Each iteration is one ``chat.completions.create`` call:
          - If the response's ``message.tool_calls`` is non-empty,
            execute each via ``tool_executor(name, arguments_json)``,
            append the assistant message + per-call tool messages to
            the running list, and loop.
          - Otherwise, parse ``message.content`` as JSON, validate
            ``expected_keys``, return.

        On iteration-cap exhaustion: raises ``AgentExecutionError``
        (same contract as ``OpenAIService.run_tool_loop`` — the
        resume-builder service catches this and falls back to the
        deterministic step-machine, same way as production).
        """
        if not self.is_available():
            raise AgentExecutionError(
                "OpenRouter adapter is not configured (OPENROUTER_API_KEY)."
            )

        chat_tools = _translate_tools_to_chat_completions(tools)
        resolved_model = (model or self.default_model).strip()

        # Chat Completions messages list. The system prompt is its own
        # message; the user_prompt starts as one user message; tool
        # interactions extend the list as the loop iterates.
        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        tool_trace: list[dict] = []

        # Slice 1J'': reasoning_effort is only valid on reasoning-class
        # models (OpenAI o-series and gpt-5.x via OpenRouter). Passing
        # it to a non-reasoning slug (Sonnet, Haiku, DeepSeek v4) is a
        # 400. Threaded as an optional kwarg so the call ignores it when
        # the caller didn't ask. Truthy check rejects "" / None alike.
        extra_kwargs: dict[str, Any] = {}
        if reasoning_effort:
            extra_kwargs["reasoning_effort"] = reasoning_effort

        for iteration in range(max_iterations):
            started_at = time.perf_counter()
            try:
                response = self._get_client().chat.completions.create(
                    model=resolved_model,
                    messages=messages,
                    tools=chat_tools or None,
                    tool_choice="auto" if chat_tools else None,
                    response_format={"type": "json_object"},
                    max_tokens=max_completion_tokens,
                    temperature=0,
                    **extra_kwargs,
                )
            except Exception as exc:
                LOGGER.exception(
                    "OpenRouter tool-loop iteration %d failed.", iteration
                )
                raise AgentExecutionError(
                    "OpenRouter provider call failed.",
                    details=str(exc)[:400],
                ) from exc

            # Track usage best-effort (some OpenRouter models return
            # partial usage info; we just sum what's there).
            usage = getattr(response, "usage", None)
            self._usage["request_count"] += 1
            self._usage["prompt_tokens"] += getattr(usage, "prompt_tokens", 0) or 0
            self._usage["completion_tokens"] += (
                getattr(usage, "completion_tokens", 0) or 0
            )
            self._usage["total_tokens"] += getattr(usage, "total_tokens", 0) or 0

            choice = response.choices[0]
            message = choice.message
            tool_calls = list(getattr(message, "tool_calls", None) or [])

            if tool_calls:
                # Echo the assistant turn (with tool_calls) into the
                # message list so the next iteration sees the full
                # reasoning chain. Chat Completions requires the
                # assistant message to be present BEFORE the
                # corresponding tool messages.
                assistant_message: dict = {
                    "role": "assistant",
                    "content": getattr(message, "content", None) or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments or "{}",
                            },
                        }
                        for tc in tool_calls
                    ],
                }
                messages.append(assistant_message)

                for tc in tool_calls:
                    args_json = tc.function.arguments or "{}"
                    try:
                        output_text = tool_executor(tc.function.name, args_json)
                    except Exception as exc:  # pragma: no cover - defensive
                        LOGGER.exception(
                            "Tool executor raised inside OpenRouter loop for %s.",
                            tc.function.name,
                        )
                        output_text = json.dumps(
                            {
                                "ok": False,
                                "error": "executor_exception",
                                "message": f"{type(exc).__name__}: {exc}",
                            }
                        )
                    tool_trace.append(
                        {
                            "name": tc.function.name,
                            "arguments": args_json,
                            "output": output_text,
                        }
                    )
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": output_text,
                        }
                    )
                continue

            # No tool calls → final response. Parse JSON, tolerating
            # markdown fences (Anthropic models through OpenRouter
            # often wrap the JSON in ```json ... ``` despite the
            # response_format hint — see _parse_provider_json).
            content = getattr(message, "content", None) or ""
            try:
                payload = _parse_provider_json(content)
            except ValueError as exc:
                raise AgentExecutionError(
                    "OpenRouter adapter returned invalid JSON.",
                    details=content[:500],
                ) from exc
            missing = [k for k in (expected_keys or []) if k not in payload]
            if missing:
                raise AgentExecutionError(
                    "OpenRouter response missing required keys.",
                    details=", ".join(missing),
                )
            return payload, tool_trace

        raise AgentExecutionError(
            "OpenRouter tool-loop exceeded the iteration cap "
            f"({max_iterations}) without producing a final response."
        )

    # ------------------------------------------------------------------
    # Minimal supporting surface so any code path the resume-builder
    # service falls through to (e.g. the structuring LLM call) still
    # works against OpenRouter without crashing.
    # ------------------------------------------------------------------

    def run_json_prompt(
        self,
        system_prompt: str,
        user_prompt: str,
        expected_keys: Optional[Iterable[str]] = None,
        temperature: Any = None,
        max_completion_tokens: int = 1200,
        task_name: Optional[str] = None,
        model: Optional[str] = None,
        metadata: Any = None,
        allow_output_budget_retry: bool = True,
        previous_response_id: Any = None,
        reasoning_effort: Any = None,
    ) -> dict:
        if not self.is_available():
            raise AgentExecutionError(
                "OpenRouter adapter is not configured (OPENROUTER_API_KEY)."
            )
        resolved_model = (model or self.default_model).strip()
        # Slice 1J'': forward reasoning_effort only when set — see the
        # matching comment in run_tool_loop for why this is conditional.
        extra_kwargs: dict[str, Any] = {}
        if reasoning_effort:
            extra_kwargs["reasoning_effort"] = reasoning_effort
        response = self._get_client().chat.completions.create(
            model=resolved_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            max_tokens=max_completion_tokens,
            temperature=0,
            **extra_kwargs,
        )
        # Slice 1K bugfix: the smoke run showed $0.0000 cost on every
        # call because this path never accumulated usage. run_tool_loop
        # tracks it at the matching site — mirror that here so single-
        # shot prompts (which is what the assistant + parser suites use)
        # also surface accurate per-call cost.
        usage = getattr(response, "usage", None)
        self._usage["request_count"] += 1
        self._usage["prompt_tokens"] += getattr(usage, "prompt_tokens", 0) or 0
        self._usage["completion_tokens"] += (
            getattr(usage, "completion_tokens", 0) or 0
        )
        self._usage["total_tokens"] += getattr(usage, "total_tokens", 0) or 0
        content = response.choices[0].message.content or ""
        try:
            payload = _parse_provider_json(content)
        except ValueError as exc:
            raise AgentExecutionError(
                "OpenRouter run_json_prompt returned invalid JSON.",
                details=content[:500],
            ) from exc
        missing = [k for k in (expected_keys or []) if k not in payload]
        if missing:
            raise AgentExecutionError(
                "OpenRouter run_json_prompt missing keys.",
                details=", ".join(missing),
            )
        return payload

    def run_structured_prompt(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        response_model: Type[Any],
        task_name: Optional[str] = None,
        max_completion_tokens: int = 1200,
        model: Optional[str] = None,
        metadata: Any = None,
        allow_output_budget_retry: bool = True,
        previous_response_id: Any = None,
        reasoning_effort: Any = None,
    ):
        # Defer the heavy schema-validation logic by reusing the
        # JSON-mode path and then validating via Pydantic. The
        # structuring path isn't critical to the agentic eval —
        # the eval scores conversational behavior; the structuring
        # pass only fires when ``generate_resume_builder_resume`` is
        # explicitly invoked.
        from pydantic import ValidationError

        payload = self.run_json_prompt(
            system_prompt,
            user_prompt,
            max_completion_tokens=max_completion_tokens,
            task_name=task_name,
            model=model,
            reasoning_effort=reasoning_effort,
        )
        try:
            return response_model.model_validate(payload)
        except ValidationError as exc:
            raise AgentExecutionError(
                "OpenRouter run_structured_prompt failed schema validation.",
                details=str(exc)[:500],
            ) from exc

    def get_usage_snapshot(self) -> dict:
        return {**self._usage, "model": self.default_model}
