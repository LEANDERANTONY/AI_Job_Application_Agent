import json
import logging
import time
from typing import Callable, Iterable, Optional

from openai import OpenAI

from src.config import (
    OPENAI_MAX_CALLS_PER_SESSION,
    OPENAI_MAX_TOKENS_PER_SESSION,
    OPENAI_MODEL_DEFAULT,
    describe_openai_model_policy,
    get_openai_model_for_task,
    get_openai_reasoning_effort_for_task,
    load_openai_key,
)
from src.errors import AgentExecutionError
from src.logging_utils import get_logger, log_event


LOGGER = get_logger(__name__)


def _ensure_json_input_prompt(user_prompt):
    prompt_text = str(user_prompt or "")
    if "json" in prompt_text.lower():
        return prompt_text
    return "Respond in JSON only.\n\n{prompt}".format(prompt=prompt_text)


class OpenAIService:
    def __init__(
        self,
        api_key=None,
        model=None,
        client=None,
        usage_budget=None,
        starting_usage=None,
        usage_event_recorder: Optional[Callable[[dict], None]] = None,
        quota_checker: Optional[Callable[[], None]] = None,
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
        self._usage_event_recorder = usage_event_recorder
        self._quota_checker = quota_checker
        if self._client is None and self._api_key:
            self._client = OpenAI(api_key=self._api_key, timeout=120.0, max_retries=2)

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
        if self._quota_checker is not None:
            self._quota_checker()
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

    def _resolve_reasoning_effort(self, task_name=None):
        return get_openai_reasoning_effort_for_task(task_name)

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
        allow_output_budget_retry=True,
    ):
        if not self.is_available():
            raise AgentExecutionError(
                "OpenAI is not configured for AI-assisted orchestration."
            )

        self._enforce_budget()
        resolved_model = self._resolve_model(task_name=task_name, model=model)
        reasoning_effort = self._resolve_reasoning_effort(task_name=task_name)
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
            reasoning_effort=reasoning_effort,
            max_completion_tokens=max_completion_tokens,
            expected_keys=list(expected_keys or []),
            system_prompt_chars=len(system_prompt or ""),
            user_prompt_chars=len(user_prompt or ""),
            estimated_input_chars=request_metadata.get("estimated_input_chars"),
            compacted_sections=request_metadata.get("compacted_sections"),
            prompt_budget_mode=request_metadata.get("prompt_budget_mode"),
            compacted_labels=request_metadata.get("compacted_labels"),
        )

        request_payload = {
            "model": resolved_model,
            "instructions": system_prompt,
            "input": _ensure_json_input_prompt(user_prompt),
            "store": False,
            "max_output_tokens": max_completion_tokens,
            "metadata": request_metadata or None,
            "text": {"format": {"type": "json_object"}},
        }
        if self._supports_reasoning_effort(resolved_model) and reasoning_effort:
            request_payload["reasoning"] = {"effort": reasoning_effort}
        if temperature is not None:
            request_payload["temperature"] = temperature

        try:
            response = self._client.responses.create(**request_payload)
        except Exception as exc:
            if (
                temperature is not None
                and self._is_unsupported_temperature_error(exc)
            ):
                log_event(
                    LOGGER,
                    logging.INFO,
                    "openai_request_retry_without_temperature",
                    "Retrying OpenAI request without temperature because the model rejected it.",
                    model=resolved_model,
                    task_name=task_name,
                    reasoning_effort=reasoning_effort,
                )
                request_payload.pop("temperature", None)
                try:
                    response = self._client.responses.create(**request_payload)
                except Exception as retry_exc:
                    log_event(
                        LOGGER,
                        logging.ERROR,
                        "openai_request_failed",
                        "OpenAI JSON prompt request failed.",
                        model=resolved_model,
                        task_name=task_name,
                        duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
                        error_type=type(retry_exc).__name__,
                        details=str(retry_exc),
                    )
                    raise AgentExecutionError(
                        "The AI workflow request failed.",
                        details=str(retry_exc),
                    ) from retry_exc
            else:
                log_event(
                    LOGGER,
                    logging.ERROR,
                    "openai_request_failed",
                    "OpenAI JSON prompt request failed.",
                    model=resolved_model,
                    task_name=task_name,
                    duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
                    error_type=type(exc).__name__,
                    details=str(exc),
                )
                raise AgentExecutionError(
                    "The AI workflow request failed.",
                    details=str(exc),
                ) from exc

        if allow_output_budget_retry and self._is_incomplete_due_to_output_tokens(response):
            response, request_payload = self._retry_with_higher_output_budget(
                response=response,
                request_payload=request_payload,
                resolved_model=resolved_model,
                task_name=task_name,
                reasoning_effort=reasoning_effort,
                started_at=started_at,
                retry_reason="empty_incomplete_response",
            )

        content = self._extract_output_text(response)
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            if allow_output_budget_retry and self._should_retry_partial_json_response(response):
                response, request_payload = self._retry_with_higher_output_budget(
                    response=response,
                    request_payload=request_payload,
                    resolved_model=resolved_model,
                    task_name=task_name,
                    reasoning_effort=reasoning_effort,
                    started_at=started_at,
                    retry_reason="truncated_partial_json",
                )
                content = self._extract_output_text(response)
                try:
                    payload = json.loads(content)
                except json.JSONDecodeError as retry_exc:
                    raise AgentExecutionError(
                        "The AI workflow returned an invalid JSON response.",
                        details=content,
                    ) from retry_exc
            else:
                raise AgentExecutionError(
                    "The AI workflow returned an invalid JSON response.",
                    details=content,
                ) from exc

        missing_keys = [
            key for key in list(expected_keys or []) if key not in payload
        ]
        if (
            allow_output_budget_retry
            and missing_keys
            and self._should_retry_partial_json_response(response)
        ):
            response, request_payload = self._retry_with_higher_output_budget(
                response=response,
                request_payload=request_payload,
                resolved_model=resolved_model,
                task_name=task_name,
                reasoning_effort=reasoning_effort,
                started_at=started_at,
                retry_reason="partial_json_missing_fields",
            )
            content = self._extract_output_text(response)
            try:
                payload = json.loads(content)
            except json.JSONDecodeError as retry_exc:
                raise AgentExecutionError(
                    "The AI workflow returned an invalid JSON response.",
                    details=content,
                ) from retry_exc
            missing_keys = [
                key for key in list(expected_keys or []) if key not in payload
            ]

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
            "estimated_input_chars": request_metadata.get("estimated_input_chars"),
            "compacted_sections": request_metadata.get("compacted_sections"),
            "compacted_labels": request_metadata.get("compacted_labels"),
            "prompt_budget_mode": request_metadata.get("prompt_budget_mode"),
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
        self._record_usage_event(
            {
                "task_name": task_name or "",
                "model_name": resolved_model,
                "request_count": 1,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "response_id": getattr(response, "id", None) or "",
                "status": status or "",
            }
        )
        if missing_keys:
            raise AgentExecutionError(
                "The AI workflow response was missing required fields.",
                details=", ".join(missing_keys),
            )
        return payload

    def _retry_with_higher_output_budget(
        self,
        *,
        response,
        request_payload,
        resolved_model,
        task_name,
        reasoning_effort,
        started_at,
        retry_reason,
    ):
        current_max_output_tokens = int(request_payload.get("max_output_tokens", 0) or 0)
        retry_max_output_tokens = min(
            max(current_max_output_tokens * 2, current_max_output_tokens + 400),
            6000,
        )
        if retry_max_output_tokens <= current_max_output_tokens:
            return response, request_payload

        retry_payload = dict(request_payload)
        retry_payload["max_output_tokens"] = retry_max_output_tokens
        log_event(
            LOGGER,
            logging.INFO,
            "openai_request_retry_with_higher_output_budget",
            "Retrying OpenAI request with a higher output token budget after an incomplete response.",
            model=resolved_model,
            task_name=task_name,
            reasoning_effort=reasoning_effort,
            previous_max_output_tokens=current_max_output_tokens,
            retry_max_output_tokens=retry_max_output_tokens,
            retry_reason=retry_reason,
        )
        try:
            response = self._client.responses.create(**retry_payload)
        except Exception as retry_exc:
            log_event(
                LOGGER,
                logging.ERROR,
                "openai_request_failed",
                "OpenAI JSON prompt retry failed after incomplete response.",
                model=resolved_model,
                task_name=task_name,
                duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
                error_type=type(retry_exc).__name__,
                details=str(retry_exc),
                retry_reason=retry_reason,
            )
            raise AgentExecutionError(
                "The AI workflow request failed.",
                details=str(retry_exc),
            ) from retry_exc
        return response, retry_payload

    def _record_usage_event(self, payload: dict):
        if self._usage_event_recorder is None:
            return
        try:
            self._usage_event_recorder(dict(payload))
        except Exception as exc:
            log_event(
                LOGGER,
                logging.WARNING,
                "openai_usage_persist_failed",
                "OpenAI usage event could not be persisted.",
                error_type=type(exc).__name__,
                details=str(exc),
                task_name=payload.get("task_name"),
                model=payload.get("model_name"),
                response_id=payload.get("response_id"),
            )

    @staticmethod
    def _is_unsupported_temperature_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return "unsupported parameter" in message and "temperature" in message

    @classmethod
    def _is_incomplete_due_to_output_tokens(cls, response) -> bool:
        incomplete_details = getattr(response, "incomplete_details", None)
        incomplete_reason = getattr(incomplete_details, "reason", None) if incomplete_details else None
        return (
            getattr(response, "status", None) == "incomplete"
            and incomplete_reason == "max_output_tokens"
            and not cls._has_message_output(response)
        )

    @staticmethod
    def _should_retry_partial_json_response(response) -> bool:
        incomplete_details = getattr(response, "incomplete_details", None)
        incomplete_reason = getattr(incomplete_details, "reason", None) if incomplete_details else None
        return (
            getattr(response, "status", None) == "incomplete"
            and incomplete_reason == "max_output_tokens"
        )

    @classmethod
    def _has_message_output(cls, response) -> bool:
        if getattr(response, "output_text", None):
            return True
        for item in getattr(response, "output", None) or []:
            if cls._get_field(item, "type") != "message":
                continue
            for part in cls._get_field(item, "content", []) or []:
                if cls._get_field(part, "type") == "output_text" and cls._get_field(part, "text", ""):
                    return True
        return False

    @staticmethod
    def _supports_reasoning_effort(model_name: str) -> bool:
        normalized = str(model_name or "").lower()
        return normalized.startswith("gpt-5")

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
