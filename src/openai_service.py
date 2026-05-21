import json
import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Iterable, NoReturn, Optional, Type, TypeVar

from openai import OpenAI
from pydantic import BaseModel, ValidationError

from src.config import (
    OPENAI_EMBEDDING_MODEL,
    OPENAI_MAX_OUTPUT_TOKENS_CEILING,
    OPENAI_MODEL_DEFAULT,
    describe_openai_model_policy,
    get_openai_model_for_task,
    get_openai_reasoning_effort_for_task,
    load_openai_key,
)
from src.errors import AgentExecutionError, OpenAIUnavailableError
from src.logging_utils import get_logger, log_event


_TModel = TypeVar("_TModel", bound=BaseModel)


LOGGER = get_logger(__name__)


# ── Request-scoped token-meter user context ─────────────────────────
# The unified LLM token meter attributes every model call to a user.
# An OpenAIService built via `build_openai_service_for_context` carries
# an explicit `user_id`, but the deterministic `*_auto` parser path
# constructs BARE `OpenAIService()` instances deep inside itself —
# those have no user_id and would otherwise go un-metered.
# `meter_user_scope` binds the active user for the duration of an
# authenticated operation; a bare service falls back to it (see
# `OpenAIService._record_token_meter`), so the résumé / JD sub-parses
# are attributed without threading a user_id'd service through every
# `*_auto` call site.
_METER_USER_ID: ContextVar[Optional[str]] = ContextVar(
    "llm_meter_user_id", default=None
)


@contextmanager
def meter_user_scope(user_id: Optional[str]):
    """Bind ``user_id`` as the token-meter fallback for the ``with``
    block's dynamic extent — every bare ``OpenAIService`` call made
    inside it is attributed to this user.

    A blank / None user_id is a no-op scope (nothing bound). The reset
    token makes the scope safe to nest and exception-safe to exit.
    Set it INSIDE the synchronous operation so the value is visible to
    that operation's same-thread sub-calls; do not rely on it crossing
    a FastAPI dependency → threadpool-route boundary.
    """
    normalized = str(user_id or "").strip()
    if not normalized:
        yield
        return
    token = _METER_USER_ID.set(normalized)
    try:
        yield
    finally:
        _METER_USER_ID.reset(token)


# ── Application-level retry layer ───────────────────────────────────
# The OpenAI Python SDK already retries up to `max_retries` times (we
# pass 2 in the constructor) on its own list of transient HTTP errors.
# Once those exhaust, the SDK raises. Without an extra layer, our
# callers (workspace pipeline agents, assistant chat) immediately fall
# through to deterministic mode — a single bad packet ruins a whole
# analysis run.
#
# This retry adds one MORE attempt on top of the SDK's, but only for
# narrow transient causes (connection / timeout / 5xx server). It does
# NOT retry on:
#   - 4xx client errors (BadRequest, Auth, NotFound, UnprocessableEntity)
#     — these are deterministic, retrying won't help
#   - 429 RateLimit — the SDK already handled retry-after; if it gave
#     up, the user is consistently throttled and we shouldn't pile on
#   - Content-policy violations — same reasoning as 4xx
#
# Streaming has a wrinkle: we can only retry the INITIAL stream creation,
# not mid-stream failures (the consumer has already received partial
# deltas and there's no way to restart cleanly). Mid-stream failures
# still propagate as before.
_APP_RETRY_DELAY_SECONDS = 0.4


def _resolve_retryable_exception_types():
    """Resolve the OpenAI SDK exception classes we'll retry on.

    Imported lazily because exception class names have shifted across
    SDK versions; we tolerate missing classes by falling back to a
    minimal set rather than blowing up at import time.
    """
    types: list[type] = []
    try:
        from openai import APIConnectionError as _APIConn
        types.append(_APIConn)
    except Exception:
        pass
    try:
        from openai import APITimeoutError as _APITimeout
        types.append(_APITimeout)
    except Exception:
        pass
    try:
        from openai import InternalServerError as _InternalServerError
        types.append(_InternalServerError)
    except Exception:
        pass
    # If none resolved, return an empty tuple — `isinstance(exc, ())`
    # is always False, so no retries happen. Safer than `(Exception,)`
    # which would retry on EVERY error including 4xx client errors.
    return tuple(types)


_RETRYABLE_OPENAI_EXCEPTIONS = _resolve_retryable_exception_types()


# Technical user_message per category. The orchestrator rewrites these
# into friendly, audience-appropriate banner copy — these are the
# precise-cause strings that land in logs / fallback_details.
_PROVIDER_FAILURE_MESSAGE = {
    "rate_limited": "The AI provider rate-limited the request.",
    "misconfigured": "The AI provider rejected our credentials or model.",
    "outage": "The AI provider was temporarily unreachable.",
}


def _classify_openai_exception(exc) -> Optional[str]:
    """Classify an exception that already SURVIVED the SDK's 2 retries
    + our 1 app-level retry (several seconds of backoff). The transient
    window is therefore already past — we classify the *nature* of what
    persisted, not whether it might recover in 3 s (unknowable here;
    the user's re-run is the "is it back yet" path).

    Returns the ``OpenAIUnavailableError`` category, or ``None`` when
    the failure is a per-request CONTENT problem (400 / 422) that must
    stay isolated to the one agent (raised as plain
    ``AgentExecutionError`` by the caller) instead of tripping the
    pipeline-wide circuit breaker.
    """
    try:
        import openai
    except Exception:
        # SDK import somehow unavailable — treat any failure as a
        # generic outage (conservative; circuit-breaks safely).
        return "outage"

    rate_cls = getattr(openai, "RateLimitError", None)
    if rate_cls is not None and isinstance(exc, rate_cls):
        return "rate_limited"

    for name in ("AuthenticationError", "PermissionDeniedError", "NotFoundError"):
        cls = getattr(openai, name, None)
        if cls is not None and isinstance(exc, cls):
            return "misconfigured"

    for name in ("BadRequestError", "UnprocessableEntityError"):
        cls = getattr(openai, name, None)
        if cls is not None and isinstance(exc, cls):
            # 400 / 422 — bad or oversized request. NOT a provider
            # outage: it's specific to THIS call's payload, so let it
            # stay a per-agent content failure and keep the LLM for
            # the rest of the pipeline.
            return None

    # Connection / timeout / 5xx, or any unrecognised transport
    # failure → genuine provider unavailability.
    return "outage"


def _raise_classified_provider_failure(exc) -> NoReturn:
    """Re-raise a caught provider exception as the right typed error:
    a per-request 400/422 becomes a content ``AgentExecutionError``
    (isolated per-agent); everything else becomes a categorised
    ``OpenAIUnavailableError`` (trips the circuit breaker)."""
    category = _classify_openai_exception(exc)
    if category is None:
        raise AgentExecutionError(
            "The AI request was rejected as invalid.",
            details=str(exc),
        ) from exc
    raise OpenAIUnavailableError(
        _PROVIDER_FAILURE_MESSAGE.get(category, _PROVIDER_FAILURE_MESSAGE["outage"]),
        details=str(exc),
        category=category,
    ) from exc


# ── USD pricing map (per 1 million tokens) ──────────────────────────
# Source of truth for ``record_trace`` cost computation. Update this
# table when OpenAI changes a price; the nightly tier-margin analysis
# reads dollars-spent straight out of ``aijobagent_run_traces`` so
# stale prices would silently bias the COGS report.
#
# Costs are stored as (input_per_million, output_per_million). The
# computed cost for a single call is:
#
#     cost = (prompt_tokens * input_cost + completion_tokens * output_cost) / 1_000_000
#
# Costs for unknown models default to (0.0, 0.0) — the row is still
# recorded so we can backfill once we learn the price. The OpenAI
# bridge logs `unknown_model_pricing` once per cold-start so a model
# that lands without a corresponding pricing entry is visible in the
# operational log without spamming.
_MODEL_PRICING_USD_PER_MILLION: dict[str, tuple[float, float]] = {
    "gpt-5.4-nano": (0.10, 0.40),
    "gpt-5.4-mini": (0.75, 4.50),
    "gpt-5.4": (2.00, 10.00),
    "gpt-5.5": (5.00, 30.00),
}


def compute_call_cost_usd(model_name: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Return the USD cost for one LLM call.

    Public helper so callers outside the OpenAIService class (e.g.
    nightly_eval's cost rollup, future tier-margin dashboards) can
    compute the same number without duplicating the pricing map.
    """
    pricing = _MODEL_PRICING_USD_PER_MILLION.get(str(model_name or "").strip())
    if pricing is None:
        return 0.0
    input_per_million, output_per_million = pricing
    cost = (
        (max(int(prompt_tokens or 0), 0) * input_per_million)
        + (max(int(completion_tokens or 0), 0) * output_per_million)
    ) / 1_000_000.0
    # Round to 6 decimals — the SQL column is numeric(10,6); rounding here
    # avoids float-to-numeric drift on the wire and keeps the in-memory
    # backend's rows directly comparable to the persisted ones.
    return round(cost, 6)


def _ensure_json_input_prompt(user_prompt):
    prompt_text = str(user_prompt or "")
    if "json" in prompt_text.lower():
        return prompt_text
    return "Respond in JSON only.\n\n{prompt}".format(prompt=prompt_text)


# ── Pydantic → OpenAI structured-output schema helpers ───────────────
# OpenAI's structured-outputs path is stricter than a vanilla JSON
# Schema validator: every object must explicitly list its required
# fields, ``additionalProperties: false`` must be set, and unsupported
# constructs (anyOf with mismatched types, $defs at the root, etc.)
# get rejected at request time. The two helpers below rewrite the raw
# Pydantic-emitted schema into a shape the API accepts.


def _schema_name_for_model(model_cls: Type[BaseModel], *, task_name=None) -> str:
    """Build a deterministic name for the schema slot.

    OpenAI requires a ``name`` alongside the schema. Including the
    task name keeps logs / metrics correlatable across runs; we strip
    non-identifier characters to satisfy the API's regex on the name
    field.
    """
    base = model_cls.__name__
    if task_name:
        base = "{task}_{model}".format(task=task_name, model=base)
    cleaned = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in base)
    return cleaned or "structured_output"


def _build_response_format_schema(model_cls: Type[BaseModel]) -> dict:
    """Return a dict-form JSON Schema accepted by OpenAI structured outputs.

    Pydantic v2 emits a JSON schema via ``model_json_schema()`` that's
    almost valid for the API — we just need to:
      * inline ``$ref`` / ``$defs`` so the root schema is self-contained
        (OpenAI accepts $defs at the root but inlining keeps the
        structure simpler to debug from a log line);
      * set ``additionalProperties: false`` on every object node;
      * mark every property as required (OpenAI's strict mode treats
        omitted-without-required as a parse error rather than a
        missing-field signal — we use ``Optional[...]`` + a ``null``
        type to express truly-optional fields, expressed via the
        Pydantic schema's ``anyOf [type, "null"]`` automatically).
    """
    schema = model_cls.model_json_schema(ref_template="#/$defs/{model}")
    defs = schema.pop("$defs", {}) or {}
    inlined = _inline_refs(schema, defs)
    return _enforce_strict_object_constraints(inlined)


def _inline_refs(node: Any, defs: dict) -> Any:
    """Recursively replace ``$ref`` markers with their definition.

    Pydantic emits one ``$defs`` entry per nested model and uses
    ``$ref`` from the parent. The API supports $defs but inlining
    keeps logs readable + lets us walk + tighten every object node in
    one pass below.
    """
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            # Refs look like "#/$defs/ModelName"
            name = ref.split("/")[-1]
            target = defs.get(name)
            if target is None:
                return {k: _inline_refs(v, defs) for k, v in node.items() if k != "$ref"}
            return _inline_refs(target, defs)
        return {k: _inline_refs(v, defs) for k, v in node.items()}
    if isinstance(node, list):
        return [_inline_refs(item, defs) for item in node]
    return node


def _enforce_strict_object_constraints(node: Any) -> Any:
    """Recursively set ``additionalProperties: false`` and complete
    the ``required`` list for every object node.

    OpenAI structured outputs treats omission of either signal as a
    schema rejection. Adding both unconditionally is safe — Pydantic
    already enforces them on its side, so we're just teaching the
    server what the client already enforced.
    """
    if isinstance(node, dict):
        result = {key: _enforce_strict_object_constraints(value) for key, value in node.items()}
        if result.get("type") == "object" or "properties" in result:
            result.setdefault("additionalProperties", False)
            properties = result.get("properties")
            if isinstance(properties, dict):
                # API requires every property in the required list. Optional
                # fields are expressed via ``anyOf [type, "null"]`` in the
                # Pydantic-emitted schema, so they still "exist" — they're
                # just allowed to be null.
                result["required"] = list(properties.keys())
        return result
    if isinstance(node, list):
        return [_enforce_strict_object_constraints(item) for item in node]
    return node


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
        user_id: Optional[str] = None,
        cost_trace_recorder: Optional[Callable[[dict], None]] = None,
        usage_meter_recorder: Optional[Callable[[int], None]] = None,
    ):
        self._api_key = api_key if api_key is not None else load_openai_key(required=False)
        self.default_model = model or OPENAI_MODEL_DEFAULT
        self.model = self.default_model
        self._client = client if client is not None else None
        self._usage_budget = dict(usage_budget or {})
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
        # Cost tracking (step 3 of the production-safety pack). When
        # ``user_id`` is set, every successful LLM call writes a row to
        # ``aijobagent_run_traces`` carrying the per-call USD cost so the
        # nightly tier-margin report can validate COGS without re-
        # deriving prices. The ``cost_trace_recorder`` callable lets
        # tests inject a list-append instead of going through the real
        # ``backend.run_traces.record_trace`` (which talks to Supabase).
        self._user_id = user_id
        self._cost_trace_recorder = cost_trace_recorder
        # Unified LLM token meter (report.md "Unified LLM token meter").
        # Every LLM call funnels through ``_record_usage``, which adds
        # this call's tokens to the user's weekly meter. Like the cost
        # trace this needs no per-feature wiring — when ``user_id`` is
        # set the accounting just happens. ``usage_meter_recorder`` is a
        # test seam (mirrors ``cost_trace_recorder``); production leaves
        # it None and the ``user_id`` path records via backend.quota.
        self._usage_meter_recorder = usage_meter_recorder
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

    def _resolve_reasoning_effort(self, task_name=None, reasoning_override=None):
        # An explicit per-call override (e.g. premium routing wanting
        # `review` at "high" — see ADR-028 Decision 2) wins over the
        # task-name-routed default. None / "" falls back to routing so
        # standard/free callers are unaffected.
        override = str(reasoning_override or "").strip().lower()
        if override:
            return override
        return get_openai_reasoning_effort_for_task(task_name)

    def _create_response_with_app_retry(
        self,
        request_payload,
        *,
        task_name,
        resolved_model,
        started_at,
    ):
        """Run ``self._client.responses.create(**request_payload)`` with
        ONE application-level retry on top of the SDK's own retries.

        Only retries on the narrow transient set defined in
        ``_RETRYABLE_OPENAI_EXCEPTIONS`` (connection / timeout / 5xx).
        Everything else (4xx, content policy, persistent rate limits,
        etc.) propagates immediately to the caller.

        On retry, sleeps ~``_APP_RETRY_DELAY_SECONDS`` and emits an
        ``openai_request_app_retry`` log event so we can see how often
        the second attempt is actually saving runs.
        """
        last_exc = None
        for attempt_index in range(2):  # 1 retry on top of SDK's max_retries=2
            try:
                return self._client.responses.create(**request_payload)
            except Exception as exc:
                last_exc = exc
                # Only retry the narrow transient set. Everything else
                # (4xx, content-policy, auth, etc.) is deterministic —
                # retrying won't help and would only add latency.
                is_retryable = (
                    bool(_RETRYABLE_OPENAI_EXCEPTIONS)
                    and isinstance(exc, _RETRYABLE_OPENAI_EXCEPTIONS)
                )
                # First attempt and exception is retryable → retry once.
                if attempt_index == 0 and is_retryable:
                    log_event(
                        LOGGER,
                        logging.WARNING,
                        "openai_request_app_retry",
                        "OpenAI responses.create raised after SDK retries; trying once more at the application layer.",
                        model=resolved_model,
                        task_name=task_name,
                        duration_ms=round(
                            (time.perf_counter() - started_at) * 1000, 2
                        ),
                        error_type=type(exc).__name__,
                        details=str(exc),
                        retry_delay_seconds=_APP_RETRY_DELAY_SECONDS,
                    )
                    time.sleep(_APP_RETRY_DELAY_SECONDS)
                    continue
                # Either non-retryable, or this was the second
                # attempt. Break and let the caller's existing error-
                # handling path kick in.
                break
        # If we got here, both attempts failed (or first was non-
        # retryable). Re-raise the last exception so the caller's
        # try/except can log + wrap it as before.
        raise last_exc  # noqa: TRY200 — explicit re-raise of captured exc

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
        # Unified LLM token meter: ``_record_usage`` is the one method
        # every responses.create round-trip funnels through (incl. each
        # iteration of a tool loop), so metering here counts ALL real
        # token spend with a single hook and nothing to forget.
        self._record_token_meter(total_tokens)

    def create_embeddings(
        self,
        inputs: "list[str]",
        *,
        model: Optional[str] = None,
        task_name: Optional[str] = None,
    ) -> "list[list[float]]":
        """Embed a batch of texts with an OpenAI embedding model.

        Tier 2 hybrid job search (semantic retrieval) routes ALL its
        embedding calls — both the one-time corpus backfill and the
        per-query / embed-on-write paths — through here so token usage
        is metered the same way `responses.create` calls are (the
        unified LLM token meter, ``_record_usage`` → ``_record_token_
        meter``).

        Args:
          inputs: the texts to embed. The embeddings endpoint accepts
            an array, so a caller batches (~100 inputs/call) to respect
            rate limits — one HTTP round-trip per batch.
          model: embedding model override; defaults to
            ``OPENAI_EMBEDDING_MODEL`` (``text-embedding-3-small``).
          task_name: optional label for logging / usage attribution.

        Returns one vector (list[float]) per input, in input order.

        Raises ``AgentExecutionError`` if the service has no client
        configured. Provider/transport errors propagate as the raw
        OpenAI SDK exception — the embedding callers (backfill,
        embed-on-write, query-embed) each decide how to degrade (the
        backfill skips the batch and continues; the search path falls
        back to lexical; embed-on-write stays non-fatal). The SDK's own
        ``max_retries`` still applies to each call.
        """
        if not self.is_available():
            raise AgentExecutionError(
                "OpenAI is not configured for embedding generation."
            )

        # Empty batch → nothing to do. Skip the round-trip entirely so
        # a resumable backfill that hits an all-skipped page is free.
        normalized_inputs = [str(text or "") for text in (inputs or [])]
        if not normalized_inputs:
            return []

        resolved_model = model or OPENAI_EMBEDDING_MODEL
        started_at = time.perf_counter()
        log_event(
            LOGGER,
            logging.INFO,
            "openai_embeddings_started",
            "Starting OpenAI embeddings request.",
            model=resolved_model,
            task_name=task_name,
            input_count=len(normalized_inputs),
        )

        try:
            response = self._client.embeddings.create(
                model=resolved_model,
                input=normalized_inputs,
            )
        except Exception as exc:
            log_event(
                LOGGER,
                logging.ERROR,
                "openai_embeddings_failed",
                "OpenAI embeddings request failed.",
                model=resolved_model,
                task_name=task_name,
                duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
                error_type=type(exc).__name__,
                details=str(exc),
            )
            # Re-raise as-is: each embedding caller has its own
            # degradation strategy and inspects the SDK exception type.
            raise

        # The embeddings endpoint returns `data` ordered by an `index`
        # field; sort by it defensively so the i-th returned vector
        # really corresponds to the i-th input even if the API ever
        # reorders. Each item exposes `.embedding`.
        data = list(getattr(response, "data", None) or [])
        data.sort(key=lambda item: getattr(item, "index", 0))
        vectors: list[list[float]] = [
            [float(component) for component in (getattr(item, "embedding", None) or [])]
            for item in data
        ]

        # Meter token usage. The embeddings usage object only reports
        # `prompt_tokens` / `total_tokens` (no completion side) — feed
        # them through the same `_record_usage` hook so embedding spend
        # lands in the unified token meter alongside everything else.
        usage = getattr(response, "usage", None)
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        total_tokens = getattr(usage, "total_tokens", 0) or prompt_tokens
        self._record_usage(resolved_model, prompt_tokens, 0, total_tokens)

        log_event(
            LOGGER,
            logging.INFO,
            "openai_embeddings_completed",
            "OpenAI embeddings request completed.",
            model=resolved_model,
            task_name=task_name,
            duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
            input_count=len(normalized_inputs),
            vector_count=len(vectors),
            prompt_tokens=prompt_tokens,
            total_tokens=total_tokens,
        )
        return vectors

    def run_json_prompt(
        self,
        system_prompt,
        user_prompt,
        expected_keys: Optional[Iterable[str]] = None,
        temperature=None,
        max_completion_tokens=1200,
        task_name=None,
        model=None,
        metadata=None,
        allow_output_budget_retry=True,
        previous_response_id=None,
        reasoning_effort=None,
    ):
        if not self.is_available():
            raise AgentExecutionError(
                "OpenAI is not configured for AI-assisted orchestration."
            )

        self._enforce_budget()
        resolved_model = self._resolve_model(task_name=task_name, model=model)
        reasoning_effort = self._resolve_reasoning_effort(
            task_name=task_name, reasoning_override=reasoning_effort
        )
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
        if previous_response_id:
            request_payload["previous_response_id"] = previous_response_id
        if self._supports_reasoning_effort(resolved_model) and reasoning_effort:
            request_payload["reasoning"] = {"effort": reasoning_effort}

        try:
            response = self._create_response_with_app_retry(
                request_payload,
                task_name=task_name,
                resolved_model=resolved_model,
                started_at=started_at,
            )
        except Exception as exc:
            log_event(
                LOGGER,
                logging.ERROR,
                "openai_request_failed",
                "OpenAI JSON prompt request failed (after SDK + app retries).",
                model=resolved_model,
                task_name=task_name,
                duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
                error_type=type(exc).__name__,
                details=str(exc),
            )
            # Couldn't get a usable response at all → provider
            # availability problem, not a content problem. Distinct
            # error type so the orchestrator surfaces an honest outage
            # notice instead of silently shipping degraded output.
            _raise_classified_provider_failure(exc)

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
        self._record_cost_trace(
            task_name=task_name,
            model_name=resolved_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            success=not bool(missing_keys),
        )
        if missing_keys:
            raise AgentExecutionError(
                "The AI workflow response was missing required fields.",
                details=", ".join(missing_keys),
            )
        return payload

    def run_tool_loop(
        self,
        system_prompt,
        user_prompt,
        *,
        tools,
        tool_executor,
        expected_keys: Optional[Iterable[str]] = None,
        max_iterations: int = 5,
        temperature=None,
        max_completion_tokens=1200,
        task_name=None,
        model=None,
        metadata=None,
        reasoning_effort=None,
    ):
        """Run a tool-using agentic loop and return the final JSON payload.

        Mirrors :meth:`run_json_prompt` but lets the model call
        registered tools before producing its final JSON answer. Each
        loop iteration is one ``responses.create`` call; when the
        model emits ``function_call`` items in the response output, we
        execute them via ``tool_executor(name, arguments_json) -> str``
        and feed the result back as ``function_call_output`` items on
        the next iteration's input list. The loop terminates when the
        model returns a text response (no more function calls) or when
        the iteration cap is hit.

        The return value is a tuple ``(payload, trace)`` where
        ``payload`` is the parsed JSON (same shape as
        ``run_json_prompt``) and ``trace`` is a list of
        ``{"name": str, "arguments": str, "output": str}`` dicts the
        caller can persist into conversation history so subsequent
        turns see what the agent fetched.

        Tools are passed straight through to ``responses.create``;
        they should already be in the Responses-API function-tool
        shape. The agentic-loop driver does NOT validate the tool spec
        — that's the registry module's job (e.g.
        ``backend.services.resume_builder_tools.RESUME_BUILDER_TOOL_SPECS``).

        Safety: this method never crosses budget enforcement. Each
        iteration calls ``_enforce_budget`` and counts usage, just
        like ``run_json_prompt`` — so a runaway loop will hit the
        configured guard rather than silently burning credits.
        """
        if not self.is_available():
            raise AgentExecutionError(
                "OpenAI is not configured for AI-assisted orchestration."
            )

        resolved_model = self._resolve_model(task_name=task_name, model=model)
        reasoning_effort = self._resolve_reasoning_effort(
            task_name=task_name, reasoning_override=reasoning_effort
        )
        request_metadata = {
            key: str(value)
            for key, value in dict(metadata or {}).items()
            if value is not None
        }
        if task_name:
            request_metadata.setdefault("task_name", task_name)

        # The initial input is just the user prompt as a message item;
        # the system prompt rides on the ``instructions`` field. Each
        # iteration may append function_call + function_call_output
        # items so the next call sees the full reasoning chain.
        input_items: list[dict] = [
            {"role": "user", "content": _ensure_json_input_prompt(user_prompt)}
        ]
        tool_trace: list[dict] = []

        last_response = None
        for iteration_index in range(max_iterations):
            self._enforce_budget()
            started_at = time.perf_counter()
            log_event(
                LOGGER,
                logging.INFO,
                "openai_tool_loop_iteration_started",
                "Starting OpenAI tool-loop iteration.",
                model=resolved_model,
                task_name=task_name,
                iteration_index=iteration_index,
                input_item_count=len(input_items),
                tools_count=len(tools or []),
            )

            request_payload = {
                "model": resolved_model,
                "instructions": system_prompt,
                "input": input_items,
                "store": False,
                "max_output_tokens": max_completion_tokens,
                "metadata": request_metadata or None,
                "text": {"format": {"type": "json_object"}},
                "tools": list(tools or []),
                # Let the model decide whether a tool call helps; for
                # most turns it'll just return the JSON directly.
                "tool_choice": "auto",
            }
            if (
                self._supports_reasoning_effort(resolved_model)
                and reasoning_effort
            ):
                request_payload["reasoning"] = {"effort": reasoning_effort}

            try:
                response = self._create_response_with_app_retry(
                    request_payload,
                    task_name=task_name,
                    resolved_model=resolved_model,
                    started_at=started_at,
                )
            except Exception as exc:
                log_event(
                    LOGGER,
                    logging.ERROR,
                    "openai_tool_loop_iteration_failed",
                    "OpenAI tool-loop iteration failed (after SDK + app retries).",
                    model=resolved_model,
                    task_name=task_name,
                    iteration_index=iteration_index,
                    duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
                    error_type=type(exc).__name__,
                    details=str(exc),
                )
                _raise_classified_provider_failure(exc)

            last_response = response
            self._track_usage_from_response(
                response,
                resolved_model=resolved_model,
                task_name=task_name,
                started_at=started_at,
                request_metadata=request_metadata,
                success=True,
            )

            output_items = list(getattr(response, "output", None) or [])
            function_calls = [
                item
                for item in output_items
                if self._get_field(item, "type") == "function_call"
            ]
            if not function_calls:
                # Model produced a final text response — extract +
                # parse the JSON and return.
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
                return payload, tool_trace

            # Echo each function_call back into the next iteration's
            # input, then execute it and append the output item.
            for call in function_calls:
                call_id = self._get_field(call, "call_id") or self._get_field(call, "id")
                call_name = self._get_field(call, "name") or ""
                call_arguments = self._get_field(call, "arguments") or ""
                # Re-emit the exact function_call item the model
                # produced. Doing this from the structured fields
                # (rather than passing the SDK object through) keeps
                # the input list a plain list of dicts, which serializes
                # cleanly and survives across SDK versions.
                input_items.append(
                    {
                        "type": "function_call",
                        "call_id": call_id,
                        "name": call_name,
                        "arguments": call_arguments,
                    }
                )
                try:
                    output_text = tool_executor(call_name, call_arguments)
                except Exception as exc:  # pragma: no cover - defensive
                    LOGGER.exception(
                        "Tool executor raised for %s.", call_name
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
                        "name": call_name,
                        "arguments": call_arguments,
                        "output": output_text,
                    }
                )
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": output_text,
                    }
                )
                log_event(
                    LOGGER,
                    logging.INFO,
                    "openai_tool_loop_tool_executed",
                    "Tool executed during agentic loop.",
                    model=resolved_model,
                    task_name=task_name,
                    iteration_index=iteration_index,
                    tool_name=call_name,
                    arguments_chars=len(call_arguments),
                    output_chars=len(output_text),
                )
            # Loop continues — next iteration sends the updated input.

        # Loop exhausted without a final text response — model kept
        # asking for tools. Surface this as an execution error so the
        # caller can fall back (resume_builder catches AgentExecutionError
        # and drops to the regex/step-machine path).
        log_event(
            LOGGER,
            logging.WARNING,
            "openai_tool_loop_iteration_cap_hit",
            "Tool-loop hit iteration cap without a final response.",
            model=resolved_model,
            task_name=task_name,
            max_iterations=max_iterations,
            tool_calls_made=len(tool_trace),
        )
        raise AgentExecutionError(
            "The AI workflow exceeded the tool-call iteration cap "
            f"({max_iterations}) without producing a final response."
        )

    def _track_usage_from_response(
        self,
        response,
        *,
        resolved_model,
        task_name,
        started_at,
        request_metadata,
        success: bool,
    ):
        """Record token usage / cost trace for a single response.

        Pulled out of ``run_json_prompt`` so ``run_tool_loop`` can call
        it on every iteration (each iteration is a separate billable
        responses.create call). The metadata + log shape mirror
        ``run_json_prompt`` so the existing dashboards keep working.
        """
        usage = getattr(response, "usage", None)
        status = getattr(response, "status", None)
        incomplete_details = getattr(response, "incomplete_details", None)
        incomplete_reason = (
            getattr(incomplete_details, "reason", None)
            if incomplete_details
            else None
        )
        output_token_details = getattr(usage, "output_tokens_details", None)
        reasoning_tokens = (
            getattr(output_token_details, "reasoning_tokens", 0) or 0
        )
        prompt_tokens = getattr(usage, "input_tokens", 0) or 0
        completion_tokens = getattr(usage, "output_tokens", 0) or 0
        total_tokens = getattr(usage, "total_tokens", 0) or 0
        self._record_usage(
            resolved_model, prompt_tokens, completion_tokens, total_tokens
        )
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
            "OpenAI request completed.",
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
        self._record_cost_trace(
            task_name=task_name,
            model_name=resolved_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            success=success,
        )

    def run_structured_prompt(
        self,
        system_prompt,
        user_prompt,
        *,
        response_model: Type[_TModel],
        task_name=None,
        max_completion_tokens=1200,
        model=None,
        metadata=None,
        allow_output_budget_retry=True,
        previous_response_id=None,
        reasoning_effort=None,
    ) -> _TModel:
        """Run a structured-output prompt bound to a Pydantic model.

        Equivalent to ``run_json_prompt`` but uses OpenAI's
        ``response_format={"type": "json_schema", ...}`` so the model is
        CONSTRAINED at generation time to emit JSON that matches the
        provided Pydantic schema. The returned value is the validated
        instance, not a raw dict — callers don't need to call
        ``model_validate`` themselves and don't need ``expected_keys``
        because the schema already covers field presence.

        Why this exists alongside ``run_json_prompt``:
            * ``json_object`` (the run_json_prompt path) only guarantees
              syntactic JSON; the model can still skip required fields
              or emit weird types, which is exactly the failure class
              the Prisha Singla "model drift" incident surfaced.
            * ``json_schema`` is constrained at generation time — a
              missing or mis-typed field can't make it through the
              token stream, so we save the "retry on missing keys" path
              that ``run_json_prompt`` carries.

        Retry / metadata / budget enforcement match ``run_json_prompt``
        so the cron-side cost-tracking story stays consistent across
        both methods.
        """
        if not self.is_available():
            raise AgentExecutionError(
                "OpenAI is not configured for AI-assisted orchestration."
            )

        self._enforce_budget()
        resolved_model = self._resolve_model(task_name=task_name, model=model)
        reasoning_effort = self._resolve_reasoning_effort(
            task_name=task_name, reasoning_override=reasoning_effort
        )
        request_metadata = {
            key: str(value)
            for key, value in dict(metadata or {}).items()
            if value is not None
        }
        if task_name:
            request_metadata.setdefault("task_name", task_name)

        schema_name = _schema_name_for_model(response_model, task_name=task_name)
        json_schema = _build_response_format_schema(response_model)

        started_at = time.perf_counter()
        log_event(
            LOGGER,
            logging.INFO,
            "openai_request_started",
            "Starting OpenAI structured prompt request.",
            model=resolved_model,
            task_name=task_name,
            reasoning_effort=reasoning_effort,
            max_completion_tokens=max_completion_tokens,
            response_model=response_model.__name__,
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
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": json_schema,
                    "strict": True,
                }
            },
        }
        if previous_response_id:
            request_payload["previous_response_id"] = previous_response_id
        if self._supports_reasoning_effort(resolved_model) and reasoning_effort:
            request_payload["reasoning"] = {"effort": reasoning_effort}

        try:
            response = self._create_response_with_app_retry(
                request_payload,
                task_name=task_name,
                resolved_model=resolved_model,
                started_at=started_at,
            )
        except Exception as exc:
            log_event(
                LOGGER,
                logging.ERROR,
                "openai_request_failed",
                "OpenAI structured prompt request failed (after SDK + app retries).",
                model=resolved_model,
                task_name=task_name,
                duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
                error_type=type(exc).__name__,
                details=str(exc),
            )
            _raise_classified_provider_failure(exc)

        if allow_output_budget_retry and self._is_incomplete_due_to_output_tokens(response):
            response, request_payload = self._retry_with_higher_output_budget(
                response=response,
                request_payload=request_payload,
                resolved_model=resolved_model,
                task_name=task_name,
                reasoning_effort=reasoning_effort,
                started_at=started_at,
                retry_reason="structured_empty_incomplete_response",
            )

        content = self._extract_output_text(response)
        try:
            raw_payload = json.loads(content)
        except json.JSONDecodeError as exc:
            # Structured outputs is supposed to guarantee parseable JSON,
            # but a truncation can still split a partial token. This
            # used to hard-fail straight to AgentExecutionError —
            # meaning the two MOST important agents (tailoring, review,
            # which use this structured path) were the LEAST resilient
            # to truncation. Bring them to parity with run_json_prompt:
            # if the response was truncated by the output budget,
            # escalate the budget (loops to the ceiling) and re-parse.
            if allow_output_budget_retry and self._should_retry_partial_json_response(response):
                response, request_payload = self._retry_with_higher_output_budget(
                    response=response,
                    request_payload=request_payload,
                    resolved_model=resolved_model,
                    task_name=task_name,
                    reasoning_effort=reasoning_effort,
                    started_at=started_at,
                    retry_reason="structured_truncated_partial_json",
                )
                content = self._extract_output_text(response)
                try:
                    raw_payload = json.loads(content)
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

        try:
            validated = response_model.model_validate(raw_payload)
        except ValidationError as exc:
            log_event(
                LOGGER,
                logging.ERROR,
                "openai_structured_validation_failed",
                "Schema-strict response failed Pydantic validation.",
                model=resolved_model,
                task_name=task_name,
                response_model=response_model.__name__,
                error_count=len(exc.errors()),
            )
            raise AgentExecutionError(
                "The AI workflow response did not match the expected schema.",
                details=str(exc),
            ) from exc

        usage = getattr(response, "usage", None)
        status = getattr(response, "status", None)
        incomplete_details = getattr(response, "incomplete_details", None)
        incomplete_reason = (
            getattr(incomplete_details, "reason", None)
            if incomplete_details
            else None
        )
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
            "response_model": response_model.__name__,
        }
        log_event(
            LOGGER,
            logging.INFO,
            "openai_request_completed",
            "OpenAI structured prompt request completed.",
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
            response_model=response_model.__name__,
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
        self._record_cost_trace(
            task_name=task_name,
            model_name=resolved_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            success=True,
        )
        return validated

    def run_text_stream(
        self,
        system_prompt,
        user_prompt,
        *,
        temperature=None,
        max_completion_tokens=1200,
        task_name=None,
        model=None,
        metadata=None,
    ):
        """Stream a plain-text response from the Responses API.

        Yields text deltas as strings as they arrive. Records usage and
        last-response metadata once the stream completes — the same way
        ``run_json_prompt`` does — so per-session budgets stay enforced.

        Intentionally separate from ``run_json_prompt``: the assistant
        streaming surface (``stream_workspace_question``) uses a plain-
        text prompt because incremental JSON parsing is fragile. Other
        agents continue to use the JSON path unchanged.
        """
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
            "Starting OpenAI text-stream request.",
            model=resolved_model,
            task_name=task_name,
            temperature=temperature,
            reasoning_effort=reasoning_effort,
            max_completion_tokens=max_completion_tokens,
            stream=True,
            system_prompt_chars=len(system_prompt or ""),
            user_prompt_chars=len(user_prompt or ""),
        )

        request_payload = {
            "model": resolved_model,
            "instructions": system_prompt,
            "input": str(user_prompt or ""),
            "store": False,
            "max_output_tokens": max_completion_tokens,
            "metadata": request_metadata or None,
            "stream": True,
        }
        if self._supports_reasoning_effort(resolved_model) and reasoning_effort:
            request_payload["reasoning"] = {"effort": reasoning_effort}

        final_response = None
        # Stream creation gets the same one-extra-app-retry treatment as
        # the JSON path. The retry only covers the initial connection;
        # once we're iterating events, mid-stream failures propagate
        # because the consumer has already received partial deltas and
        # we can't replay them cleanly.
        try:
            stream = self._create_response_with_app_retry(
                request_payload,
                task_name=task_name,
                resolved_model=resolved_model,
                started_at=started_at,
            )
        except Exception as exc:
            log_event(
                LOGGER,
                logging.ERROR,
                "openai_request_failed",
                "OpenAI text-stream creation failed (after SDK + app retries).",
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

        try:
            for event in stream:
                event_type = self._get_field(event, "type", "")
                if event_type == "response.output_text.delta":
                    delta = self._get_field(event, "delta", "")
                    if delta:
                        yield str(delta)
                elif event_type == "response.completed":
                    final_response = self._get_field(event, "response")
                elif event_type == "response.failed":
                    detail = self._get_field(event, "response")
                    raise AgentExecutionError(
                        "The AI workflow request failed mid-stream.",
                        details=str(detail) if detail is not None else None,
                    )
                elif event_type == "response.error":
                    detail = self._get_field(event, "error")
                    raise AgentExecutionError(
                        "The AI workflow returned an error event.",
                        details=str(detail) if detail is not None else None,
                    )
        except AgentExecutionError:
            raise
        except Exception as exc:
            # Mid-stream failure (network drop after first delta, etc.).
            # We do NOT retry here — partial deltas already left the
            # building. Surface the error to the caller, which will
            # fall back to deterministic per its own logic.
            log_event(
                LOGGER,
                logging.ERROR,
                "openai_request_failed",
                "OpenAI text-stream request failed mid-stream (no retry possible after partial output).",
                model=resolved_model,
                task_name=task_name,
                duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
                error_type=type(exc).__name__,
                details=str(exc),
            )
            _raise_classified_provider_failure(exc)

        usage = getattr(final_response, "usage", None) if final_response else None
        status = getattr(final_response, "status", None) if final_response else None
        incomplete_details = getattr(final_response, "incomplete_details", None) if final_response else None
        incomplete_reason = getattr(incomplete_details, "reason", None) if incomplete_details else None
        output_token_details = getattr(usage, "output_tokens_details", None) if usage else None
        reasoning_tokens = getattr(output_token_details, "reasoning_tokens", 0) or 0 if output_token_details else 0
        prompt_tokens = (getattr(usage, "input_tokens", 0) or 0) if usage else 0
        completion_tokens = (getattr(usage, "output_tokens", 0) or 0) if usage else 0
        total_tokens = (getattr(usage, "total_tokens", 0) or 0) if usage else 0
        self._record_usage(resolved_model, prompt_tokens, completion_tokens, total_tokens)
        self._last_response_metadata = {
            "response_id": getattr(final_response, "id", None) if final_response else None,
            "status": status,
            "incomplete_reason": incomplete_reason,
            "model": resolved_model,
            "task_name": task_name,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "reasoning_tokens": reasoning_tokens,
            "stream": True,
        }
        log_event(
            LOGGER,
            logging.INFO,
            "openai_request_completed",
            "OpenAI text-stream request completed.",
            model=resolved_model,
            task_name=task_name,
            duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
            response_id=getattr(final_response, "id", None) if final_response else None,
            status=status,
            incomplete_reason=incomplete_reason,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            reasoning_tokens=reasoning_tokens,
            stream=True,
        )
        self._record_usage_event(
            {
                "task_name": task_name or "",
                "model_name": resolved_model,
                "request_count": 1,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "response_id": (getattr(final_response, "id", None) if final_response else "") or "",
                "status": status or "",
            }
        )
        self._record_cost_trace(
            task_name=task_name,
            model_name=resolved_model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            success=True,
        )

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
        # Escalate the output budget across MULTIPLE steps (doubling
        # each time) until the response is no longer truncated by
        # max_output_tokens OR we hit the configured ceiling. The old
        # behaviour was a SINGLE bump capped at 6000, which meant a
        # content-rich résumé / JD / tailored analysis whose JSON
        # exceeded ~6000 tokens still truncated → silent deterministic
        # fallback. Looping to OPENAI_MAX_OUTPUT_TOKENS_CEILING removes
        # truncation as a fallback cause: only a genuine provider
        # outage (raised below as OpenAIUnavailableError) should ever
        # downgrade a run now.
        current_max_output_tokens = int(request_payload.get("max_output_tokens", 0) or 0)
        # Never shrink: if a task's base budget already exceeds the
        # ceiling, the loop simply no-ops (next <= current → break).
        ceiling = max(int(OPENAI_MAX_OUTPUT_TOKENS_CEILING or 0), current_max_output_tokens)
        # Safety stop independent of the ceiling: doubling reaches 16000
        # from any realistic base (≥100) inside ~8 steps; 8 bounds the
        # pathological "model keeps returning incomplete" case.
        max_escalations = 8

        working_response = response
        working_payload = request_payload
        escalations = 0
        while escalations < max_escalations:
            previous_budget = int(working_payload.get("max_output_tokens", 0) or 0)
            next_budget = min(
                max(previous_budget * 2, previous_budget + 400),
                ceiling,
            )
            if next_budget <= previous_budget:
                # Already at the ceiling and STILL truncated. Return the
                # last response; the caller's parse/missing-key check
                # raises AgentExecutionError (a content failure — the
                # payload genuinely doesn't fit even at the ceiling,
                # which for our payloads should be effectively
                # impossible).
                break

            escalations += 1
            retry_payload = dict(working_payload)
            retry_payload["max_output_tokens"] = next_budget
            log_event(
                LOGGER,
                logging.INFO,
                "openai_request_retry_with_higher_output_budget",
                "Re-issuing OpenAI request with a higher output token budget after a truncated response.",
                model=resolved_model,
                task_name=task_name,
                reasoning_effort=reasoning_effort,
                previous_max_output_tokens=previous_budget,
                retry_max_output_tokens=next_budget,
                ceiling=ceiling,
                escalation_attempt=escalations,
                retry_reason=retry_reason,
            )
            # Route each escalation through the same app-retry helper as
            # the initial call so a transient blip during escalation
            # still gets the SDK + app retry. A hard failure here is a
            # provider-availability problem, NOT a content problem —
            # raise the outage-specific error so the orchestrator can
            # surface it honestly instead of silently degrading.
            try:
                working_response = self._create_response_with_app_retry(
                    retry_payload,
                    task_name=task_name,
                    resolved_model=resolved_model,
                    started_at=started_at,
                )
            except Exception as retry_exc:
                log_event(
                    LOGGER,
                    logging.ERROR,
                    "openai_request_failed",
                    "OpenAI request failed during output-budget escalation (after SDK + app retries).",
                    model=resolved_model,
                    task_name=task_name,
                    duration_ms=round((time.perf_counter() - started_at) * 1000, 2),
                    error_type=type(retry_exc).__name__,
                    details=str(retry_exc),
                    retry_reason=retry_reason,
                    escalation_attempt=escalations,
                )
                _raise_classified_provider_failure(retry_exc)

            working_payload = retry_payload
            # Stop as soon as the response is no longer truncated by the
            # output budget (status != incomplete/max_output_tokens).
            if not self._should_retry_partial_json_response(working_response):
                break

        return working_response, working_payload

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

    def _record_cost_trace(
        self,
        *,
        task_name: Optional[str],
        model_name: str,
        prompt_tokens: int,
        completion_tokens: int,
        success: bool = True,
    ) -> None:
        """Persist one cost-trace row.

        Best-effort: any failure is logged and swallowed. The runtime
        hot path stays clean even when Supabase blips, mirroring the
        ``_record_usage_event`` semantics.

        When ``cost_trace_recorder`` is set (test injection), we hand
        the payload to that callable instead of calling
        ``backend.run_traces.record_trace`` directly. Production runs
        with both unset (no usage recorder, no test recorder) → no-op,
        and with ``user_id`` set + the default recorder → Supabase row.
        """
        cost_usd = compute_call_cost_usd(model_name, prompt_tokens, completion_tokens)
        payload = {
            "task_name": task_name or "",
            "model_name": model_name,
            "prompt_tokens": int(prompt_tokens or 0),
            "completion_tokens": int(completion_tokens or 0),
            "cost_usd": cost_usd,
            "user_id": self._user_id,
            "success": bool(success),
        }
        if self._cost_trace_recorder is not None:
            try:
                self._cost_trace_recorder(dict(payload))
            except Exception as exc:  # noqa: BLE001 - best-effort
                log_event(
                    LOGGER,
                    logging.WARNING,
                    "openai_cost_trace_persist_failed",
                    "OpenAI cost trace recorder raised.",
                    error_type=type(exc).__name__,
                    details=str(exc),
                    task_name=task_name,
                    model=model_name,
                )
            return

        # No injected recorder: only persist when we have a user_id.
        # Recording trace rows without a user attribution would clutter
        # the table with no tier-margin signal; the dev / fixture path
        # often runs without auth, so the silent no-op is the right
        # default. The `aijobagent_run_traces` schema permits NULL on
        # user_id for completeness, but the application opts not to
        # write that shape.
        if not self._user_id:
            return
        try:
            from backend.run_traces import record_trace  # local import to avoid circular
            record_trace(
                task_name=task_name or "",
                model_name=model_name,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=cost_usd,
                user_id=self._user_id,
                success=success,
            )
        except Exception as exc:  # noqa: BLE001 - best-effort
            log_event(
                LOGGER,
                logging.WARNING,
                "openai_cost_trace_persist_failed",
                "OpenAI cost trace persistence failed.",
                error_type=type(exc).__name__,
                details=str(exc),
                task_name=task_name,
                model=model_name,
            )

    def _record_token_meter(self, total_tokens: int) -> None:
        """Add this call's tokens to the user's weekly LLM usage meter.

        The accounting half of the unified token meter (report.md
        "Unified LLM token meter"). Called from ``_record_usage`` — the
        one method every ``responses.create`` round-trip funnels
        through, incl. each iteration of a tool loop — so every token
        actually spent is metered with no per-feature wiring.

        Best-effort and a deliberate no-op unless the service was built
        for a real user: eval / nightly / fixture runs construct
        ``OpenAIService`` without a ``user_id`` and are never metered.
        Dispatch mirrors ``_record_cost_trace``: an injected
        ``usage_meter_recorder`` (test seam) wins; otherwise, with a
        ``user_id`` set, call ``backend.quota.record_llm_token_usage``
        directly. ``record_llm_token_usage`` is itself best-effort, so
        a metering hiccup never breaks the user's actual operation.
        """
        try:
            amount = int(total_tokens or 0)
        except (TypeError, ValueError):
            return
        if amount <= 0:
            return

        if self._usage_meter_recorder is not None:
            try:
                self._usage_meter_recorder(amount)
            except Exception as exc:  # noqa: BLE001 - best-effort
                log_event(
                    LOGGER,
                    logging.WARNING,
                    "openai_token_meter_recorder_failed",
                    "OpenAI token-meter recorder raised.",
                    error_type=type(exc).__name__,
                    details=str(exc),
                )
            return

        # No injected recorder: attribute to the service's own user_id
        # when it has one, else fall back to the request-scoped meter
        # context (`meter_user_scope`) — so a bare OpenAIService built
        # inside a *_auto parser path is still metered to the
        # authenticated user. Anonymous / eval runs have neither and
        # no-op here.
        effective_user_id = self._user_id or _METER_USER_ID.get()
        if not effective_user_id:
            return
        try:
            # Local import — same circular-avoidance pattern as the
            # ``backend.run_traces`` import in ``_record_cost_trace``.
            from backend.quota import record_llm_token_usage

            record_llm_token_usage(effective_user_id, amount)
        except Exception as exc:  # noqa: BLE001 - best-effort
            log_event(
                LOGGER,
                logging.WARNING,
                "openai_token_meter_persist_failed",
                "OpenAI token-meter persistence failed.",
                error_type=type(exc).__name__,
                details=str(exc),
            )

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
