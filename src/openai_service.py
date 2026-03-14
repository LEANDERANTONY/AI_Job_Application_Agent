import json
import logging
import time
from typing import Iterable, Optional

from openai import OpenAI

from src.config import (
    OPENAI_MAX_CALLS_PER_SESSION,
    OPENAI_MAX_TOKENS_PER_SESSION,
    OPENAI_MODEL,
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
        self.model = model or OPENAI_MODEL
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
        for key in self._usage_totals:
            if starting_usage and key in starting_usage:
                self._usage_totals[key] = starting_usage[key]
        self._last_response_metadata = {}
        if self._client is None and self._api_key:
            self._client = OpenAI(api_key=self._api_key)

    def is_available(self):
        return self._client is not None

    def get_usage_snapshot(self):
        max_calls = self._usage_budget.get("max_calls")
        max_total_tokens = self._usage_budget.get("max_total_tokens")
        return {
            **self._usage_totals,
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

    def run_json_prompt(
        self,
        system_prompt,
        user_prompt,
        expected_keys: Optional[Iterable[str]] = None,
        temperature=0.2,
        max_completion_tokens=1200,
    ):
        if not self.is_available():
            raise AgentExecutionError(
                "OpenAI is not configured for AI-assisted orchestration."
            )

        self._enforce_budget()

        started_at = time.perf_counter()
        log_event(
            LOGGER,
            logging.INFO,
            "openai_request_started",
            "Starting OpenAI JSON prompt request.",
            model=self.model,
            temperature=temperature,
            max_completion_tokens=max_completion_tokens,
            expected_keys=list(expected_keys or []),
            system_prompt_chars=len(system_prompt or ""),
            user_prompt_chars=len(user_prompt or ""),
        )

        try:
            response = self._client.chat.completions.create(
                model=self.model,
                temperature=temperature,
                max_completion_tokens=max_completion_tokens,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except Exception as exc:
            log_event(
                LOGGER,
                logging.ERROR,
                "openai_request_failed",
                "OpenAI JSON prompt request failed.",
                model=self.model,
                duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
                error_type=type(exc).__name__,
            )
            raise AgentExecutionError(
                "The AI workflow request failed.",
                details=str(exc),
            ) from exc

        usage = getattr(response, "usage", None)
        choices = getattr(response, "choices", None) or []
        finish_reason = getattr(choices[0], "finish_reason", None) if choices else None
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        total_tokens = getattr(usage, "total_tokens", 0) or 0
        self._usage_totals["request_count"] += 1
        self._usage_totals["prompt_tokens"] += prompt_tokens
        self._usage_totals["completion_tokens"] += completion_tokens
        self._usage_totals["total_tokens"] += total_tokens
        self._last_response_metadata = {
            "response_id": getattr(response, "id", None),
            "finish_reason": finish_reason,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        }
        log_event(
            LOGGER,
            logging.INFO,
            "openai_request_completed",
            "OpenAI JSON prompt request completed.",
            model=self.model,
            duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
            response_id=getattr(response, "id", None),
            finish_reason=finish_reason,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            session_request_count=self._usage_totals["request_count"],
            session_total_tokens=self._usage_totals["total_tokens"],
        )

        content = self._extract_message_content(response)
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
    def _extract_message_content(response):
        choices = getattr(response, "choices", None) or []
        if not choices:
            raise AgentExecutionError("The AI workflow returned no choices.")
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None) if message else None
        if not content:
            raise AgentExecutionError("The AI workflow returned an empty message.")
        return content
