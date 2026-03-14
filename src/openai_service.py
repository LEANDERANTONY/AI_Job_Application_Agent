import json
import logging
import time
from typing import Iterable, Optional

from openai import OpenAI

from src.config import (
    OPENAI_MAX_CALLS_PER_SESSION,
    OPENAI_MAX_TOKENS_PER_SESSION,
    OPENAI_MODEL_DEFAULT,
    describe_openai_model_policy,
    get_openai_model_for_task,
    load_openai_key,
)
from src.errors import AgentExecutionError
from src.logging_utils import get_logger, log_event


LOGGER = get_logger(__name__)


class OpenAIService:
    def __init__(
        self,
        api_key=None,
        model=None,
        client=None,
        usage_budget=None,
        starting_usage=None,
    ):
        self._api_key = api_key if api_key is not None else load_openai_key(required=False)
        self.default_model = model or OPENAI_MODEL_DEFAULT
        self.model = self.default_model
        self._client = client if client is not None else None
        self._usage_budget = {
            "max_calls": OPENAI_MAX_CALLS_PER_SESSION,
            "max_total_tokens": OPENAI_MAX_TOKENS_PER_SESSION,
        }
        self._usage_budget.update(usage_budget or {})
        self._usage_totals = {
            "request_count": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        self._usage_by_model = {}
        for key in self._usage_totals:
            if starting_usage and key in starting_usage:
                self._usage_totals[key] = starting_usage[key]
        if starting_usage and starting_usage.get("model_usage"):
            self._usage_by_model = {
                name: dict(values)
                for name, values in starting_usage["model_usage"].items()
            }
        self._last_response_metadata = {}
        if self._client is None and self._api_key:
            self._client = OpenAI(api_key=self._api_key)

    def is_available(self):
        return self._client is not None

    def describe_model_policy(self):
        return describe_openai_model_policy(self.default_model)

    def get_usage_snapshot(self):
        max_calls = self._usage_budget.get("max_calls")
        max_total_tokens = self._usage_budget.get("max_total_tokens")
        return {
            **self._usage_totals,
            "model_usage": {
                model_name: dict(metrics)
                for model_name, metrics in self._usage_by_model.items()
            },
            "max_calls": max_calls,
            "max_total_tokens": max_total_tokens,
            "remaining_calls": None
            if max_calls is None
            else max(max_calls - self._usage_totals["request_count"], 0),
            "remaining_total_tokens": None
            if max_total_tokens is None
            else max(max_total_tokens - self._usage_totals["total_tokens"], 0),
            "last_response_metadata": dict(self._last_response_metadata),
        }

    def _enforce_budget(self):
        max_calls = self._usage_budget.get("max_calls")
        max_total_tokens = self._usage_budget.get("max_total_tokens")
        if max_calls is not None and self._usage_totals["request_count"] >= max_calls:
            log_event(
                LOGGER,
                logging.WARNING,
                "openai_budget_exceeded",
                "OpenAI session call budget exceeded.",
                model=self.model,
                request_count=self._usage_totals["request_count"],
                max_calls=max_calls,
            )
            raise AgentExecutionError(
                "The AI-assisted workflow has reached the session call limit. Start a new session or raise the budget to continue."
            )
        if (
            max_total_tokens is not None
            and self._usage_totals["total_tokens"] >= max_total_tokens
        ):
            log_event(
                LOGGER,
                logging.WARNING,
                "openai_budget_exceeded",
                "OpenAI session token budget exceeded.",
                model=self.model,
                total_tokens=self._usage_totals["total_tokens"],
                max_total_tokens=max_total_tokens,
            )
            raise AgentExecutionError(
                "The AI-assisted workflow has reached the session token budget. Start a new session or raise the budget to continue."
            )

    def _resolve_model(self, task_name=None, model=None):
        if model:
            return model
        return get_openai_model_for_task(task_name, fallback=self.default_model)

    def _record_usage(self, model_name, prompt_tokens, completion_tokens, total_tokens):
        self._usage_totals["request_count"] += 1
        self._usage_totals["prompt_tokens"] += prompt_tokens
        self._usage_totals["completion_tokens"] += completion_tokens
        self._usage_totals["total_tokens"] += total_tokens
        if model_name not in self._usage_by_model:
            self._usage_by_model[model_name] = {
                "request_count": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
            }
        self._usage_by_model[model_name]["request_count"] += 1
        self._usage_by_model[model_name]["prompt_tokens"] += prompt_tokens
        self._usage_by_model[model_name]["completion_tokens"] += completion_tokens
        self._usage_by_model[model_name]["total_tokens"] += total_tokens

    def run_json_prompt(
        self,
        system_prompt,
        user_prompt,
        expected_keys: Optional[Iterable[str]] = None,
        temperature=0.2,
        max_completion_tokens=1200,
        task_name=None,
        model=None,
        metadata=None,
    ):
        if not self.is_available():
            raise AgentExecutionError(
                "OpenAI is not configured for AI-assisted orchestration."
            )

        self._enforce_budget()
        resolved_model = self._resolve_model(task_name=task_name, model=model)
        request_metadata = {
            key: str(value)
            for key, value in dict(metadata or {}).items()
            if value is not None
        }
        if task_name:
            request_metadata.setdefault("task_name", task_name)

        started_at = time.perf_counter()
        log_event(
            LOGGER,
            logging.INFO,
            "openai_request_started",
            "Starting OpenAI JSON prompt request.",
            model=resolved_model,
            task_name=task_name,
            temperature=temperature,
            max_completion_tokens=max_completion_tokens,
            expected_keys=list(expected_keys or []),
            system_prompt_chars=len(system_prompt or ""),
            user_prompt_chars=len(user_prompt or ""),
        )

        try:
            response = self._client.responses.create(
                model=resolved_model,
                instructions=system_prompt,
                input=user_prompt,
                store=False,
                temperature=temperature,
                max_output_tokens=max_completion_tokens,
                metadata=request_metadata or None,
                text={"format": {"type": "json_object"}},
            )
        except Exception as exc:
            log_event(
                LOGGER,
                logging.ERROR,
                "openai_request_failed",
                "OpenAI JSON prompt request failed.",
                model=resolved_model,
                task_name=task_name,
                duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
                error_type=type(exc).__name__,
            )
            raise AgentExecutionError(
                "The AI workflow request failed.",
                details=str(exc),
            ) from exc

        usage = getattr(response, "usage", None)
        status = getattr(response, "status", None)
        incomplete_details = getattr(response, "incomplete_details", None)
        incomplete_reason = getattr(incomplete_details, "reason", None) if incomplete_details else None
        output_token_details = getattr(usage, "output_tokens_details", None)
        reasoning_tokens = getattr(output_token_details, "reasoning_tokens", 0) or 0
        prompt_tokens = getattr(usage, "input_tokens", 0) or 0
        completion_tokens = getattr(usage, "output_tokens", 0) or 0
        total_tokens = getattr(usage, "total_tokens", 0) or 0
        self._record_usage(resolved_model, prompt_tokens, completion_tokens, total_tokens)
        self._last_response_metadata = {
            "response_id": getattr(response, "id", None),
            "status": status,
            "incomplete_reason": incomplete_reason,
            "model": resolved_model,
            "task_name": task_name,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "reasoning_tokens": reasoning_tokens,
        }
        log_event(
            LOGGER,
            logging.INFO,
            "openai_request_completed",
            "OpenAI JSON prompt request completed.",
            model=resolved_model,
            task_name=task_name,
            duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
            response_id=getattr(response, "id", None),
            status=status,
            incomplete_reason=incomplete_reason,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            reasoning_tokens=reasoning_tokens,
            session_request_count=self._usage_totals["request_count"],
            session_total_tokens=self._usage_totals["total_tokens"],
        )

        content = self._extract_output_text(response)
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise AgentExecutionError(
                "The AI workflow returned an invalid JSON response.",
                details=content,
            ) from exc

        missing_keys = [
            key for key in list(expected_keys or []) if key not in payload
        ]
        if missing_keys:
            raise AgentExecutionError(
                "The AI workflow response was missing required fields.",
                details=", ".join(missing_keys),
            )
        return payload

    @staticmethod
    def _get_field(value, field_name, default=None):
        if value is None:
            return default
        if isinstance(value, dict):
            return value.get(field_name, default)
        return getattr(value, field_name, default)

    @classmethod
    def _extract_output_text(cls, response):
        output_text = getattr(response, "output_text", None)
        if output_text:
            return output_text

        collected = []
        for item in getattr(response, "output", None) or []:
            if cls._get_field(item, "type") != "message":
                continue
            for part in cls._get_field(item, "content", []) or []:
                part_type = cls._get_field(part, "type")
                if part_type == "output_text":
                    text = cls._get_field(part, "text", "")
                    if text:
                        collected.append(text)
                elif part_type == "refusal":
                    raise AgentExecutionError(
                        "The AI workflow refused to answer the request.",
                        details=cls._get_field(part, "refusal"),
                    )

        if collected:
            return "\n".join(collected)

        raise AgentExecutionError("The AI workflow returned an empty message.")
