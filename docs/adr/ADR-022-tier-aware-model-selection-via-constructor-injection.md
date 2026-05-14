# ADR-022: Tier-Aware Model Selection via Constructor Injection

- Status: Accepted
- Date: 2026-05-15

## Context

Step 6 of the Day 42 tier-enforcement series (commit `68be1d5`) introduced premium model routing: when a Pro / Business user opts into a premium application by setting `premium=True` on `/workspace/analyze`, the three "high-trust" supervised-pipeline agents (`review`, `resume_generation`, `cover_letter`) should run on `gpt-5.5` instead of the standard `gpt-5.4`. The fourth agent (`tailoring`) stays on `gpt-5.4-mini` regardless of plan — the COGS analysis pinned it there because tailoring carries the heaviest grounded payload and an upgrade would push the per-application cost past the Pro plan's revenue.

The existing model selection lived in `src/config.py::get_openai_model_for_task(task_name)`, which reads `OPENAI_MODEL_ROUTING[task]` from env. This works fine for tier-independent routing, but the premium decision depends on three runtime facts that aren't visible to `src/config.py`:

1. The user's tier (`backend.tiers.resolve_user_tier(app_user)`).
2. The premium flag on the current `/workspace/analyze` request.
3. Whether the current agent task is on the upgrade list.

We needed somewhere to combine those three signals into a per-task model override, AND we needed every code path that ends up calling `responses.create(...)` for one of those agents — the primary path, the output-budget retry path (`_retry_with_higher_output_budget`), the app-level retry path (`_create_response_with_app_retry`), and the per-agent retry in the orchestrator (see ADR-018) — to honour the same override consistently.

## Decision

Compute the override once per workflow construction, pass it to the agents at instantiation, and let each agent inject the override into its `run_json_prompt(...)` calls.

### `select_workflow_model` and `build_workflow_model_overrides`

`backend/model_routing.py` exposes two helpers:

```python
def select_workflow_model(*, task: str, tier: Tier, premium: bool) -> Optional[str]:
    if not premium: return None
    if tier not in {"pro", "business"}: return None
    if task not in {"review", "resume_generation", "cover_letter"}: return None
    return OPENAI_MODEL_ROUTING.get("premium_high_trust")  # default "gpt-5.5"

def build_workflow_model_overrides(*, tier: Tier, premium: bool) -> dict[str, Optional[str]]:
    return {task: select_workflow_model(task=task, tier=tier, premium=premium)
            for task in ("tailoring", "review", "resume_generation", "cover_letter")}
```

`None` means "no override, use the standard `OPENAI_MODEL_ROUTING[task]` lookup". The premium model name is itself env-configurable (`OPENAI_MODEL_PREMIUM` → routed under the `"premium_high_trust"` key in `OPENAI_MODEL_ROUTING`) so we can rotate models without code changes.

### Constructor-time injection

The orchestrator is constructed inside `WorkspaceService.run_workflow(...)` with the override map:

```python
model_overrides = build_workflow_model_overrides(tier=tier, premium=premium)
orchestrator = ApplicationOrchestrator(
    openai_service=openai_service,
    model_overrides=model_overrides,
    ...,
)
```

Each agent receives its task's override at construction:

```python
review_agent = ReviewAgent(openai_service, model_override=model_overrides["review"])
```

Inside `ReviewAgent.run(...)`, the override flows through `self._openai.run_json_prompt(..., model=self._model_override or None)`. The agent itself doesn't know whether the override came from a premium opt-in or a test fixture — it just forwards whatever was injected at construction.

### Why constructor-time, not per-call

The orchestrator's retry layers (ADR-018) re-issue the SAME agent's `.run(...)` after a transient failure. If the model override were a per-call parameter, every retry path — including the per-agent retry inside `run_agent_step`, the SDK's own retries, and the app-level retry — would need to know about it and pass it through. Each retry path is a separate function and is allowed to compose with the others; threading a model name through all of them is a maintenance liability.

With constructor-time injection, the agent's `self._model_override` is set once and lives for the agent's lifetime. Every retry — at every layer — reads the same `self._model_override`. There's exactly one place to set it (orchestrator construction) and one place to read it (inside each agent's `run` method).

## Alternatives Considered

### 1. Per-call `model_override` parameter on each agent's `.run(...)`
Rejected. Every retry path needs to know about the override and forward it. The per-agent retry helper in `run_agent_step` (ADR-018) constructs the lambda once and re-invokes it — adding a model parameter to the lambda's closure works, but the same lambda is also the deterministic-fallback path (`AgentClass(None).run(...)`), where the model override is meaningless. The deterministic-fallback constructor would need a no-op override field just for symmetry. Worse, the orchestrator would need to thread the override into every `run_agent_step` call site, which means knowing per-call which task name to look up. Constructor injection keeps the orchestrator's call sites clean.

### 2. Read tier from a thread-local request context inside the agent
Rejected. Pull-based context lookup in agents creates an implicit dependency on the request scope — agents stop being unit-testable in isolation, and the dependency is invisible at the constructor's call site. Constructor injection makes the dependency explicit and the agent independently testable with a `model_override="gpt-5.5"` argument.

### 3. Resolve the model inside `OpenAIService._create_response_with_app_retry`
Rejected. The OpenAI service layer is below the agent layer; it doesn't know which task is firing. Moving tier-awareness into the OpenAI layer would either require passing the task name through to every `responses.create` call (which is what we're trying to avoid), or having the service introspect an opaque blob of context. The agent is the right boundary because it already knows what task it is.

### 4. Resolve at orchestrator entry but route through a custom `OpenAIService` subclass
Considered. Build a `PremiumOpenAIService` that wraps `OpenAIService` and rewrites the model in `run_json_prompt`. Keeps the agents oblivious. Rejected because the wrapper would have to introspect the `task` kwarg in each call — which is fine for `run_json_prompt` (it explicitly takes `task=...`) but the streaming path (`run_text_stream`) and the parser paths take different signatures. The same wrapper class has to handle four call shapes, which is harder to read than each agent forwarding its own `self._model_override`. The constructor-injection pattern is what HelpmateAI's premium routing uses; copying the shape keeps mental load low.

### 5. Make `tailoring` premium-eligible too
Rejected on COGS. The tailoring agent carries the largest grounded payload (full resume + JD + fit analysis + first-pass draft) and runs on every workflow, premium or not. Routing tailoring to `gpt-5.5` would either eat the premium revenue margin or force a price hike on the Pro plan that nobody asked for. The three review-grade agents (`review`, `resume_generation`, `cover_letter`) are where the perceived quality lift lives — they're the surfaces the user reads.

## Consequences

### Positive

- Retry paths (SDK retries, app-level retry, per-agent retry, output-budget retry) are tier-correct by construction. No per-layer awareness of the override.
- Adding a new premium-eligible task is two lines: append it to `_PREMIUM_UPGRADE_TASKS` in `backend/model_routing.py` and to the `build_workflow_model_overrides` dict. The agent and its retry paths inherit the override for free.
- The premium model name is fully env-configurable. Rotating from `gpt-5.5` to a successor model is a single environment variable change.
- Tailoring's pinning is explicit (the absence from `_PREMIUM_UPGRADE_TASKS` is the source of truth) and defendable (the COGS reasoning is in the module docstring).
- The override function returns `None` defensively when the user's tier or premium flag is wrong. The gate at `/workspace/analyze` (ADR-021) is the authoritative source of *what gets charged*; this router decides *what gets served*. A regression in the gate can't silently issue premium credits without the upgraded model — and vice versa.

### Negative

- Two places to keep in sync if a new task wants premium routing: `_PREMIUM_UPGRADE_TASKS` and `build_workflow_model_overrides`. Mitigated by a unit test in `tests/backend/test_tier_aware_workflow_model.py` that pins the exact override dict shape; adding a task and forgetting one of the two locations fails CI.
- The orchestrator constructor now takes one more argument (`model_overrides`). Default to an empty dict so the deterministic path and existing test fixtures don't need to construct it; the dict's `.get(task)` returns `None` and the standard model lookup wins.
- A Free user who somehow bypasses the gate and reaches model selection with `premium=True` would still be served `None` (standard model) because `_PREMIUM_ELIGIBLE_TIERS` is the second check. Defensive layering, not a guarantee — the gate is the source of truth.

## Follow-Up

- Once Day 43 (Lemon Squeezy) lands and the resolver returns real tiers, watch the `OPENAI_MODEL_PREMIUM` cost per premium application. The COGS analysis used a 1.5× multiplier estimate vs `gpt-5.4`; live numbers may differ.
- Consider extending the same pattern to `assistant_turns` (a "premium assistant" tier?) — but only if there's a real product reason. The current decision is to keep the assistant on the standard mini model for everyone.
- Document the premium-eligible task list in the pricing page so users know which surfaces upgrade and which don't.

## Related

- [ADR-020](ADR-020-tier-resolution-via-single-shim-function.md): the resolver whose output feeds this router.
- [ADR-021](ADR-021-atomic-quota-with-refund-on-failure.md): the gate that authorizes the premium opt-in; this router serves what the gate authorized.
- [ADR-018](ADR-018-three-layer-llm-retry-and-per-agent-fallback-isolation.md): the retry layers that inherit the model override transparently because it lives on the agent instance.
- [ADR-010](ADR-010-single-pass-review-corrections-and-task-tuned-model-budgets.md): the per-task model routing baseline this premium override sits on top of.
