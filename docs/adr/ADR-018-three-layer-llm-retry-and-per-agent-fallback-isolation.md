# ADR-018: Three-Layer LLM Retry and Per-Agent Fallback Isolation

- Status: Accepted
- Date: 2026-05-08

## Context

LLM-driven flows in the workspace (the supervised analysis pipeline, the assistant chat, the resume parser, the JD parser, the JD summary, every workflow agent) all eventually call `OpenAIService.run_json_prompt` or `run_text_stream`, which call `self._client.responses.create(...)`. The OpenAI Python SDK is configured with `max_retries=2`, so the SDK transparently retries on its own list of transient failures (connection drops, timeouts, 5xx, 429-with-Retry-After).

After those 2 retries exhaust, the SDK raises and our application code's behavior was:

- For LLM calls inside the **assistant chat:** caught and turned into a `delta` of "(deterministic answer)", which felt fine because the user could just re-ask.
- For LLM calls inside the **supervised analysis pipeline:** caught at the orchestrator level and the WHOLE PIPELINE was re-run with `openai_service=None`. The user got every artifact (Tailoring, Review, Resume Generation, Cover Letter) in deterministic mode — even the agents that would have succeeded on the LLM path. A single bad packet during one agent's call meant losing LLM-quality output across all four artifacts.

This was strictly worse than necessary because:

- Most "bad packets" are transient — one more SDK call probably succeeds. The SDK already does this twice, but its own list is conservative; some failures slip through.
- Even when a particular agent really can't get LLM output, the OTHER agents in the pipeline aren't affected. There's no reason for the Forge agent's bad day to compromise the Cover Letter agent.
- The whole-pipeline downgrade meant deterministic Tailoring → deterministic Review → deterministic Resume Generation → deterministic Cover Letter. That's four artifacts of degraded output instead of one.

We wanted the orchestrator's resilience to be **layered** — give the LLM call multiple shots before the agent gives up, AND keep one agent's failure from affecting the others.

## Decision

A three-layer retry stack on top of per-agent fallback isolation.

### Layer 1 — SDK retries (existing)

`self._client = OpenAI(api_key=..., timeout=120.0, max_retries=2)`. Unchanged. Catches the obvious transient cases — connection refused, DNS failure, request timeout, 5xx server errors, 429 rate limits with `Retry-After` honored. Burned twice silently.

### Layer 2 — App-level retry on `responses.create`

A new `OpenAIService._create_response_with_app_retry` helper wraps the single `self._client.responses.create(**payload)` call. After the SDK's 2 retries exhaust and the SDK finally raises, we try ONE more time on a **tight allow-list**:

```python
_RETRYABLE_OPENAI_EXCEPTIONS = (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
)
```

NOT retried at this layer:
- 4xx client errors (`BadRequestError`, `AuthenticationError`, `NotFoundError`, `UnprocessableEntityError`) — our payload is wrong; retry won't help, just adds latency.
- `RateLimitError` — the SDK already handled retry-after; if it gave up, the user is consistently throttled and we shouldn't pile on.
- Content-policy violations — same reasoning as 4xx.

400 ms delay between attempts. New `openai_request_app_retry` log event with `error_type`, `details`, and `retry_delay_seconds` for production observability.

For streaming (`run_text_stream`), retry covers only the **initial stream creation**. Once we've started yielding deltas, we can't retry without confusing the consumer (partial deltas already left the building); mid-stream failures propagate as before.

For the existing output-budget retry helper (`_retry_with_higher_output_budget`, fires when a response was truncated due to insufficient `max_output_tokens`), the budget-retry call now also routes through `_create_response_with_app_retry`, so a token-grow retry that hits a transient failure also gets one extra shot.

### Layer 3 — Per-agent retry inside the orchestrator

The `run_agent_step` helper in `ApplicationOrchestrator._run_pipeline` now wraps each agent's `.run(...)` call in its own retry. If the agent raises `AgentExecutionError` (which is what `OpenAIService` re-raises after its layers exhaust, AND what some agents raise for semantic failures like missing required fields after the budget retry), we wait 400 ms and retry the agent's full run once.

Only fires in `mode="openai"`. In deterministic mode, the agents short-circuit to their internal `_fallback()` paths and never raise, so the retry is a no-op.

Only `AgentExecutionError` is retried. Other exceptions (bugs in our own code, contract violations) propagate immediately because they wouldn't change on retry.

### Per-agent fallback isolation

When an agent's two LLM attempts both fail, instead of cascading the exception up to the orchestrator's whole-pipeline `try/except` (the old behavior), `run_agent_step` now runs that agent's deterministic fallback for THAT agent only.

Each call site supplies a `deterministic_fallback_runner` lambda alongside the assisted runner:

```python
tailoring_output = run_agent_step(
    "tailoring",
    lambda: tailoring_agent.run(candidate_profile, job_description, fit_analysis, tailored_draft),
    deterministic_fallback_runner=lambda: TailoringAgent(None).run(
        candidate_profile, job_description, fit_analysis, tailored_draft,
    ),
)
```

The deterministic fallback runner constructs a fresh agent instance with `openai_service=None`. The agent classes already short-circuit to their internal `_fallback()` path when no service is configured, so this gives us the deterministic output for the failing agent without any agent-level refactor. Downstream agents receive the deterministic output as input and continue trying the LLM path themselves.

The whole-pipeline fallback is now a **safety net** that fires only if a per-agent deterministic fallback ITSELF errors out — very unusual, since that would mean our own deterministic code is broken, not the LLM.

### Mode reconciliation

The `result.mode` field on `AgentWorkflowResult` historically meant "the LLM was used." With per-agent fallback isolation, partial use is now possible — three of four agents may run with the LLM and one may fall back. To keep the mode field honest:

- Pipeline tracks `llm_success_count` and `per_agent_fallback_count` across all agent steps.
- After all agents finish, if a pipeline started in `mode="openai"` but `llm_success_count == 0` (every agent fell back per-agent), the result's `mode` is downgraded to `"deterministic_fallback"` and `model` flips to `"fallback"`. The first LLM error's `user_message` becomes the `fallback_reason`. This preserves the historical contract for consumers reading `mode` to detect a fully-deterministic run.
- A partial run (e.g. only Forge fell back) correctly keeps `mode="openai"` because the LLM did do useful work in 3 of 4 stages.

### Coverage check

Every `responses.create` call in the codebase now routes through `_create_response_with_app_retry`. By extension, all of the following inherit Layer 2 for free:

- Resume parser (`resume_llm_parser_service.py`)
- JD parser (`jd_llm_parser_service.py`)
- JD summary (`jd_summary_service.py`)
- All four supervised-workflow agents (Tailoring, Review, Resume Generation, Cover Letter)
- The assistant chat (streaming and non-streaming paths)
- The output-budget retry helper

## Alternatives Considered

### 1. Add an unbounded retry loop with exponential backoff
Rejected. Compounding the SDK's 2 + an app retry × N = 4+ attempts means latency explodes during real outages, and retrying past the third attempt rarely changes the outcome for transient failures. The 400 ms fixed delay + single app retry is the right balance.

### 2. Retry on every `Exception`, not the allow-list
Rejected. Retrying on `BadRequestError` (our payload is wrong) just adds latency without changing the outcome. The narrow allow-list of three transient SDK exception types matches how the SDK itself classifies retryable errors.

### 3. Retry mid-stream by reconnecting and replaying deltas
Rejected. The consumer has already received and rendered partial deltas — there's no clean way to "rewind" and try again without confusing the UI. Mid-stream failures propagate; the SDK + app retries cover the initial-connection case which is the much more common transient.

### 4. Whole-pipeline retry instead of per-agent retry
Rejected. Re-running every agent because one had a bad packet wastes 4×N tokens and 4×N seconds. Per-agent retry costs at most 1×N tokens and stays scoped to the failure.

### 5. Per-agent retry with N>1 attempts
Considered. Up to 4 effective LLM calls per agent (SDK 2 + app 1 + per-agent 1) is already generous. Adding more would compound latency without clear evidence of additional recovery. Revisit if production telemetry shows we're losing recoverable failures at the per-agent layer specifically.

### 6. Unified failure mode — drop deterministic fallbacks entirely and let agents fail loudly
Rejected. Deterministic fallbacks are the ground-truth-aware floor of what we can produce when AI is unavailable for any reason (auth issues, account quota, content policy, regional outage). Per-agent fallback isolation actually makes the deterministic path more useful, not less — it can now serve a single missing artifact instead of replacing four good ones.

## Consequences

### Positive

- A single transient failure during the supervised pipeline now has up to 4 LLM call attempts before the agent gives up. Most "bad packets" recover invisibly.
- One agent failing no longer cascades to four deterministic outputs. The user keeps their LLM-quality Cover Letter even if Forge had a bad day.
- All LLM call sites in the codebase share the same retry contract — easier to reason about, easier to tune (the delay constant and exception allow-list live in one place).
- New `openai_request_app_retry` and `agent_run_retry` log events give us production visibility into how often the second attempt actually saves a run. We can tune the layers based on real telemetry.
- 17 new tests pin the contract — Layer 2 retries on the 3 allow-listed types and not on 4xx/auth; per-agent retry recovers a flaky agent; per-agent fallback isolates a failing agent; mode reconciles to deterministic when no LLM call succeeded.

### Negative

- More wall-clock time on a real outage. SDK 2 + app 1 + per-agent 1 = up to 4 round-trips × ~120 s timeout = a worst-case ~8 minutes if every layer hits timeout. Mitigated by the timeout itself (120 s is hard, no extra wait), the 400 ms inter-retry delays (small relative to the LLM call), and the fact that during an outage most failures fail fast (connection refused) rather than timing out.
- Slightly more code complexity in `OpenAIService` and `_run_pipeline`. Mitigated by the helper pattern (`_create_response_with_app_retry`, `run_agent_step`) that keeps the retry logic in one place per layer.
- Deterministic fallback paths in each agent (`_fallback()`) are now load-bearing in a different way — they're called per-agent during a partial outage, not just during a full no-service run. We already had Tier-2 quality runners pinning the deterministic outputs against fixtures; those continue to enforce that the deterministic floor stays reasonable.

## Follow-Up

- Track the new log events in production:
  - `openai_request_app_retry` count vs `openai_request_completed` count → SDK exhaustion rate.
  - `agent_run_retry` count vs `agent_run_completed` count → per-agent retry trigger rate.
  - `agent_run_per_agent_fallback` count → how often we're falling back per-agent.
  - `orchestrator_completed` events with `llm_success_count == 0` → fully-deterministic runs.
- If `agent_run_retry` shows a high recovery rate (>50%), consider raising the per-agent retry budget to 2.
- If `agent_run_per_agent_fallback` is dominated by one specific agent, investigate whether that agent's prompt or schema needs tightening.
