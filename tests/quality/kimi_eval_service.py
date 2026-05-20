"""Eval-scoped Kimi (Chat-Completions) adapter — ADR-028 D1 validation.

NOT production-wired. ADR-028 Decision 1 is Proposed/gated; this is
the tool to *validate* it: a drop-in `OpenAIService` duck-type that
talks to a Kimi K2 OpenAI-**Chat-Completions**-compatible endpoint, so
the existing quality suites (resume parser / JD parser / analysis) can
run against Kimi by injecting this as the `openai_service` exactly
where the model seam already is.

Why a whole module (not a `base_url` swap): `src/openai_service.py`
is built on OpenAI's proprietary **Responses API** (62 refs, zero
`chat.completions`); Kimi providers serve Chat Completions only. See
the corrected seam note in ADR-028. This adapter is that bridge — and
the realistic shape of D1's eventual implementation.

Faithfulness vs. the production path (so the comparison is fair):
- Same prompt in; JSON out; raises the SAME `AgentExecutionError`
  on bad/again-truncated JSON / missing keys / schema drift, so the
  agents' own deterministic fallback triggers identically.
- BUT it instruments those failures (the production fallback would
  otherwise *mask* a weaker provider): a per-task fidelity counter
  records valid-JSON / schema-OK / truncated / fell-back. That rate
  is the decisive chat-completions-vs-Responses metric the existing
  suites don't measure.

Known v1 simplifications (documented, controlled-for in the eval):
- Uses `response_format={"type":"json_object"}` + client-side
  `model_validate` (production uses Responses `json_schema`
  constrained decoding — the laxness IS part of what we measure).
- No output-budget escalation loop; instead we set a generous
  `max_tokens` so truncation isn't a confound, and *count*
  `finish_reason == "length"` as a fidelity miss.
- Kimi runs in non-thinking mode (reasoning_effort ignored) — that
  is the ≤ gpt-5.4@medium cost+latency constraint; Kimi-advanced /
  thinking-mode vs gpt-5.5@high is the explicit later follow-up.

Config (provider-agnostic, env):
    KIMI_API_KEY   — required to run (no key → is_available() False)
    KIMI_BASE_URL  — default OpenRouter (easiest K2.6 access)
    KIMI_MODEL     — default a K2.6 id; override per provider
"""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from typing import Any, Optional, Type

from pydantic import BaseModel, ValidationError

from src.errors import AgentExecutionError
# Slice 1I: import the fence-tolerant JSON parser the OpenRouter
# adapter uses. Slice 1G found that Anthropic models through
# OpenRouter wrap their JSON output in ```json...``` markdown
# fences regardless of response_format=json_object, because Claude
# has no native JSON-mode constraint. The Phase A run had to fix
# this to get truthful Sonnet numbers. Phase B (this file) needs
# the same fix or Sonnet's parser/JD/analysis fidelity scores will
# be artificially depressed (every fenced response → JSONDecodeError
# → content_failures++ → looks like a Sonnet quality issue when it's
# actually a parser issue on our side).
from tests.quality.openrouter_eval_service import _parse_provider_json

_DEFAULT_BASE_URL = os.getenv("KIMI_BASE_URL", "https://openrouter.ai/api/v1").strip()
_DEFAULT_MODEL = os.getenv("KIMI_MODEL", "moonshotai/kimi-k2.6").strip()
# Safety CEILING (not a floor): callers pass real per-task budgets
# (parsers/agents from config; preflight passes ~20). We clamp to
# this ceiling so a runaway never over-spends, but never inflate a
# small request up to it — OpenRouter reserves max_tokens*price of
# credit upfront, so flooring tiny calls at 8000 caused spurious 402s
# on pricier models / low balances. Truncation is still COUNTED via
# finish_reason=="length"; the eval controls truncation by the
# callers' already-generous per-task budgets.
_EVAL_MAX_TOKENS = int(os.getenv("KIMI_EVAL_MAX_TOKENS", "8000"))


class KimiEvalService:
    """OpenAIService-duck-typed Kimi Chat-Completions adapter."""

    def __init__(self, api_key: Optional[str] = None, *, model: Optional[str] = None,
                 base_url: Optional[str] = None, client: Any = None):
        self._api_key = (api_key if api_key is not None
                         else os.getenv("KIMI_API_KEY", "")).strip()
        self._base_url = (base_url or _DEFAULT_BASE_URL).strip()
        self.default_model = (model or _DEFAULT_MODEL).strip()
        self.model = self.default_model
        self._client = client
        # Fidelity: per-task {calls, valid_json, schema_ok, truncated,
        # content_failures}. content_failures == an AgentExecutionError
        # we raised → the agent's deterministic fallback fires.
        self._fidelity: dict[str, dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        self._usage = {"request_count": 0, "prompt_tokens": 0,
                       "completion_tokens": 0, "total_tokens": 0}
        self._usage_by_model: dict[str, dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        self._last_response_metadata: dict[str, Any] = {}

    # ── OpenAIService surface ──────────────────────────────────────
    def is_available(self) -> bool:
        return bool(self._api_key) or self._client is not None

    def describe_model_policy(self) -> str:
        return f"kimi:{self.default_model}@non-thinking"

    def get_usage_snapshot(self) -> dict:
        return {
            **self._usage,
            "model_usage": {m: dict(v) for m, v in self._usage_by_model.items()},
            "last_response_metadata": dict(self._last_response_metadata),
            "fidelity": self.get_fidelity_report(),
        }

    def get_fidelity_report(self) -> dict[str, dict[str, Any]]:
        """Per-task provider fidelity — THE decisive provider metric.
        `usable_rate` = fraction of calls that returned valid,
        schema-conformant JSON without us raising (i.e. that did NOT
        silently degrade the agent to deterministic)."""
        out: dict[str, dict[str, Any]] = {}
        for task, c in self._fidelity.items():
            calls = c.get("calls", 0) or 0
            ok = c.get("schema_ok", 0) or 0
            out[task] = {
                **{k: c.get(k, 0) for k in
                   ("calls", "valid_json", "schema_ok", "truncated",
                    "content_failures")},
                "usable_rate": round(ok / calls, 3) if calls else None,
            }
        return out

    # ── lazy client ────────────────────────────────────────────────
    def _get_client(self):
        if self._client is None:
            from openai import OpenAI  # OpenAI SDK speaks any OpenAI-compatible base_url
            self._client = OpenAI(api_key=self._api_key,
                                   base_url=self._base_url,
                                   timeout=120.0, max_retries=2)
        return self._client

    def _chat(self, system_prompt: str, user_prompt: str, *, task_name: str,
              max_tokens: int) -> str:
        if not self.is_available():
            raise AgentExecutionError("Kimi eval adapter not configured (KIMI_API_KEY).")
        started = time.perf_counter()
        resp = self._get_client().chat.completions.create(
            model=self.default_model,
            messages=[{"role": "system", "content": system_prompt},
                      {"role": "user", "content": user_prompt}],
            response_format={"type": "json_object"},
            max_tokens=max_tokens,
            temperature=0,
        )
        usage = getattr(resp, "usage", None)
        pt = getattr(usage, "prompt_tokens", 0) or 0
        ct = getattr(usage, "completion_tokens", 0) or 0
        self._usage["request_count"] += 1
        self._usage["prompt_tokens"] += pt
        self._usage["completion_tokens"] += ct
        self._usage["total_tokens"] += pt + ct
        bm = self._usage_by_model[self.default_model]
        bm["request_count"] += 1
        bm["total_tokens"] += pt + ct
        choice = resp.choices[0]
        finish = getattr(choice, "finish_reason", None)
        self._last_response_metadata = {
            "model": self.default_model, "task_name": task_name,
            "finish_reason": finish,
            "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        }
        self._fidelity[task_name]["calls"] += 1
        if finish == "length":
            self._fidelity[task_name]["truncated"] += 1
        return choice.message.content or ""

    # ── prompt entrypoints (signatures mirror OpenAIService) ───────
    def run_json_prompt(self, system_prompt, user_prompt, expected_keys=None,
                        temperature=None, max_completion_tokens=1200,
                        task_name=None, model=None, metadata=None,
                        allow_output_budget_retry=True, previous_response_id=None,
                        reasoning_effort=None) -> dict:
        task = task_name or "unknown"
        content = self._chat(system_prompt, user_prompt, task_name=task,
                             max_tokens=min(max_completion_tokens or _EVAL_MAX_TOKENS,
                                             _EVAL_MAX_TOKENS))
        try:
            payload = _parse_provider_json(content)
        except ValueError as exc:
            self._fidelity[task]["content_failures"] += 1
            raise AgentExecutionError(
                "The AI workflow returned an invalid JSON response.",
                details=content[:500],
            ) from exc
        self._fidelity[task]["valid_json"] += 1
        missing = [k for k in (expected_keys or []) if k not in payload]
        if missing:
            self._fidelity[task]["content_failures"] += 1
            raise AgentExecutionError(
                "The AI workflow response was missing required fields.",
                details=", ".join(missing),
            )
        self._fidelity[task]["schema_ok"] += 1
        return payload

    def run_structured_prompt(self, system_prompt, user_prompt, *,
                              response_model: Type[BaseModel], task_name=None,
                              max_completion_tokens=1200, model=None,
                              metadata=None, allow_output_budget_retry=True,
                              previous_response_id=None, reasoning_effort=None):
        task = task_name or "unknown"
        content = self._chat(system_prompt, user_prompt, task_name=task,
                             max_tokens=min(max_completion_tokens or _EVAL_MAX_TOKENS,
                                             _EVAL_MAX_TOKENS))
        try:
            raw = _parse_provider_json(content)
        except ValueError as exc:
            self._fidelity[task]["content_failures"] += 1
            raise AgentExecutionError(
                "The AI workflow returned an invalid JSON response.",
                details=content[:500],
            ) from exc
        self._fidelity[task]["valid_json"] += 1
        try:
            validated = response_model.model_validate(raw)
        except ValidationError as exc:
            self._fidelity[task]["content_failures"] += 1
            raise AgentExecutionError(
                "The AI workflow response did not match the expected schema.",
                details=str(exc)[:500],
            ) from exc
        self._fidelity[task]["schema_ok"] += 1
        return validated
