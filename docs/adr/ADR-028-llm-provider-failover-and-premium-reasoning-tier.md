# ADR-028: LLM Provider Failover (Kimi K2) and Premium Reasoning Tier

- Status: Partially Accepted — Decision 2 **Accepted & shipped**
  (2026-05-18); Decision 1 **Proposed**, gated on the operator
  spend/outage input in Action Items
- Date: 2026-05-18
- Deciders: Operator (single-maintainer project)

## Context

Two questions surfaced from the Day 47–52 résumé/parsing resilience
work and the follow-up cost/latency research:

1. **Provider single-point-of-failure.** Every LLM-backed surface
   (the 4-agent pipeline, the résumé parser, the JD parser, the
   JD-summary panel, the assistant) calls OpenAI through one
   `src/openai_service.py::OpenAIService`. The resilience arc shipped
   this session (escalating output budget to a 16k ceiling;
   `OpenAIUnavailableError` with `outage`/`rate_limited`/`misconfigured`
   classification; a per-run circuit breaker that keeps succeeded
   agents and short-circuits the rest; honest "OpenAI is having a
   moment" surfacing across the pipeline + parsers + jd_summary)
   already makes a *genuine provider outage* degrade **gracefully and
   honestly** — but the degraded path is the low-fidelity
   deterministic parser / heuristic agents. A second provider could
   make the degraded path *near-full quality* instead.

2. **Premium tier may be paying for a capability it doesn't use.**
   Per ADR-022, premium (Pro/Business + `premium=True`) upgrades
   exactly `review`, `resume_generation`, `cover_letter` from
   `gpt-5.4` to `gpt-5.5`; `tailoring` stays on mini (COGS). Verified
   this session: the override swaps only the *model*, not the
   reasoning effort — those tasks run at `OPENAI_REASONING_DEFAULT`
   ("medium") premium or not. `gpt-5.5` is 2× `gpt-5.4` ($5/$30 vs
   $2.50/$15 per 1M tok); its price premium is largely justified by
   deep-reasoning-at-high-effort, which this configuration does not
   invoke. So premium pays frontier price for the *least
   differentiated* slice of `gpt-5.5`.

Constraints / forces:

- **EU/PII posture** (ADR-024/025; Supabase EU; Frankfurt VPS;
  explicit PII rules). Résumé and JD text are PII-heavy. Moonshot's
  first-party Kimi API is Beijing-hosted; OpenAI-compatible
  aggregators (Fireworks, Together) are US; none are EU-resident
  without further diligence. OpenAI offers a contracted EU
  data-residency endpoint (+10%).
- **Single maintainer, pre-revenue** (ADR-026 posture). Ops burden
  and recurring spend are first-class costs.
- **Unknown input:** current monthly OpenAI spend and observed
  real-outage frequency are not yet quantified. The cost/benefit —
  and whether failover is even *needed* beyond the graceful path
  already shipped — hinges on these. This ADR makes them an explicit
  go/no-go gate rather than guessing.

Research snapshot (2026-05, verify before relying):

| | input $/1M | output $/1M | cached input | speed (fast provider) |
|---|---|---|---|---|
| gpt-5.4-mini | 0.75 | 4.50 | 0.075 (90% off) | ~160 t/s, reasoning TTFT |
| gpt-5.4 | 2.50 | 15.00 | 0.25 | — |
| gpt-5.5 | 5.00 | 30.00 | 0.50 | — |
| Kimi K2.5 | ~0.60 | ~2.50 | ~0.15 (75% off) | ~330 t/s, sub-1s TTFT (non-thinking) |
| Kimi K2.6 | ~0.73–0.95 | ~3.49–4.00 | ~0.15 | — |

Key seam fact: Kimi K2 exposes an **OpenAI-API-compatible** endpoint,
so a secondary provider is a `base_url` + `api_key` + model-id swap
through the existing `OpenAIService` constructor — no new client, no
call-site changes. `OpenAIUnavailableError` + `_classify_openai_exception`
+ the circuit breaker are precisely the failover seams.

## Decision

This ADR proposes **two separable decisions**. Recommendation in
**bold**; both are gated (see Action Items).

### Decision 1 — Kimi K2 as a per-task *failover* provider (recommended: YES, gated)

On a classified `OpenAIUnavailableError` of category `outage` or
`rate_limited`, retry the *same* request against a configured Kimi K2
OpenAI-compatible endpoint **before** the deterministic/heuristic
fallback. `misconfigured` does NOT fail over (our bug, not OpenAI's —
a bad key/model would just fail on Kimi too; keep the loud ops alert).
Provider is selected **per task** via the existing
`OPENAI_MODEL_ROUTING` / `model_routing` pattern so PII-heavy tasks
(`profile` résumé parse, `job` JD parse, `resume_generation`,
`cover_letter`) can be held OpenAI-only on failover while low-PII
surfaces (`assistant`/`product_help`, `jd_summary`) fail over freely —
the EU/PII decision becomes a config knob, not a code rewrite.

Not adopted: Kimi as *primary* (Decision-1 variant C) — adds a
quality-validation surface (prompts are gpt-5-tuned; would need the
quality fixtures re-run) and reverses the deliberate fast-fail product
calls; revisit only if spend data demands it. Not adopted: self-host
(variant D) — infra cost + ops + a quality *regression* on exactly
the structured-extraction tasks; infeasible on a CPU VPS.

### Decision 2 — Premium reasoning effort (ACCEPTED & shipped 2026-05-18)

**Validated empirically**, then implemented. A 3-arm A/B over the
6-scenario ReviewAgent harness (3 clean = over-correction guard, 3
adversarial = planted-fabrication detection + correction —
`tests/quality/review_model_ab_runner.py`, 18 LLM calls):

| arm | model · reasoning | adv detection | adv correction | clean no-false-reject |
|---|---|---|---|---|
| baseline (free/standard) | gpt-5.4 · medium | **1.0** | 0.958 | 1.0 |
| premium today | gpt-5.5 · medium | **1.0** | **0.911** | 1.0 |
| premium fixed | gpt-5.5 · **high** | **1.0** | **1.0** | 1.0 |

Findings: (1) detection is **perfect at the free model** — gpt-5.5
buys *zero* grounding-catch. (2) The shipped premium config
(`gpt-5.5@medium`) is **≤ free gpt-5.4@medium** (correction regresses
0.958→0.911 via the embellishment scenario) — paying 2× for a
tie-to-regression. (3) gpt-5.5's value is **entirely in high
reasoning** (the only arm perfect on all three; fixes the two
residual correction misses both medium models share) — the exact
slice ADR-022's model-only override never invoked.

**Decision:** premium lifts `review` to **gpt-5.5 @ high reasoning**
(not the indefensible `@medium`). Reasoning effort is now
premium-aware *only for `review`*, via `build_workflow_reasoning_overrides`
+ a `reasoning_effort` override threaded ApplicationOrchestrator →
ReviewAgent → `OpenAIService.run_structured_prompt` (exact parallel
to ADR-022's model-override plumbing). `resume_generation` /
`cover_letter` are **unchanged** (not measured — no evidence to act
on; their own eval can revisit). Standard/free runs are byte-for-byte
unaffected (override is `None` → routed `medium`). This refines
ADR-022 (which set the premium *model*); ADR-022 keeps a status note
pointing here.

## Options Considered

### Decision 1

| Option | Complexity | Cost | Resilience | EU/PII |
|---|---|---|---|---|
| A. Status quo (graceful deterministic only) | None | $0 | Outage → deterministic-quality for the duration (already honest) | clean |
| **B. Kimi K2 per-task failover** | Low (drop-in via OpenAIService + circuit breaker) | ~$0 idle, Kimi rates only during OpenAI outages (rare) | Outage → near-full quality | per-task knob; PII tasks stay OpenAI |
| C. Kimi K2 primary (some surfaces) | Med (re-tune + re-validate prompts; reverses fast-fail calls) | cheaper steady-state | high | broader PII exposure |
| D. Self-host Kimi-like | High (GPU/ops/SRE) | $300–3000/mo or unusable CPU latency | new SPOF; quality regression | self-controlled but worse |

### Decision 2

| Option | Cost delta | Justified? |
|---|---|---|
| Keep `gpt-5.5@medium` (status quo) | 2× on 3 tasks | pays for least-differentiated slice |
| **Validate → `review`@high only** | +reasoning tokens on `review` only | tests the one defensible task before paying |
| All 3 premium tasks @high | large | `cover_letter` is prose; not reasoning-bound |
| Drop premium model upgrade | −2× | only if validation shows no delta |

## Trade-off Analysis

- **Resilience vs. need.** The graceful+honest degraded path already
  shipped means failover buys *quality during outages*, not
  *availability* (we already don't hard-fail). Its value scales with
  real OpenAI outage frequency × user impact — currently unmeasured.
- **Cost.** Failover (Option 1B) is ~free at idle: Kimi rates apply
  only while OpenAI is genuinely down (rare). Steady-state OpenAI
  spend is unchanged. This is the cheapest resilience upgrade
  available and rides seams already built.
- **EU/PII is the real constraint, not money or latency.** Kimi is
  faster and cheaper; the binding question is whether résumé/JD PII
  may transit a non-EU provider even *during an outage*. The per-task
  knob defers this to an explicit operator policy decision rather
  than baking it in.
- **Premium reasoning is orthogonal and cheaper to test** than any
  integration — it's a measurement + a one-line reasoning override,
  no new dependency.

## Consequences

### Positive
- A genuine OpenAI outage degrades to *near-full quality* (Kimi) for
  non-PII tasks instead of deterministic heuristics.
- Provider risk is no longer a single vendor for the surfaces allowed
  to fail over.
- Premium spend gets validated against a real quality signal instead
  of assumed.

### Negative
- A second provider account, API key, billing, and a model-id to
  track/rotate (mitigated: env-config, same as `OPENAI_MODEL_PREMIUM`).
- Failover path needs its own test coverage + a periodic
  smoke-check that the Kimi key still works (a cold failover that
  fails is worse than a known-good deterministic one).
- EU/PII policy must be explicitly decided per task and documented.

### Neutral
- Prompts are gpt-5-tuned; acceptable for a *failover* path
  (Kimi-degraded > deterministic-degraded even if not gpt-5-equal).
  Would need fixture re-validation only if promoted to primary.

## Alternatives considered

See Options tables. Self-host (1D) was assessed and rejected on
cost/ops/quality grounds for a single CPU VPS. Kimi-as-primary (1C)
deferred pending steady-state spend data and would reopen the
fast-fail product decisions.

## Action Items (go/no-go gate)

1. [ ] **Operator inputs (blocks acceptance):** quantify (a) monthly
       OpenAI spend and (b) real OpenAI-outage frequency from Sentry /
       `aijobagent_run_traces`. If outages are negligible and spend is
       small, Decision 1 may rationally be **A (no-op)** — the
       graceful path already shipped is sufficient.
2. [ ] **Operator policy (blocks 1B):** decide which tasks may fail
       over to a non-EU provider with PII. Default proposal:
       low-PII only (`assistant`/`product_help`, `jd_summary`);
       `profile`/`job`/`resume_generation`/`cover_letter` stay
       OpenAI-only on failover.
3. [ ] If 1B accepted: add a `secondary_provider` config (base_url +
       key + per-task model map) and a failover branch in the
       `OpenAIUnavailableError` handling (one new call through the
       existing `OpenAIService`); hermetic test for
       failover-on-outage + PII-task-does-not-fail-over.
4. [ ] Decision 2: run the `review` premium A/B; record the
       grounding-delta; then raise `review`→high *or* drop the
       upgrade *or* (policy permitting) point premium at Kimi.
5. [ ] On acceptance: flip Status to Accepted, move to the right
       index cluster, update the "Current state note", DEVLOG entry.

## References

- ADR-018 (three-layer retry + per-agent fallback isolation) — the
  resilience lineage this extends.
- ADR-022 (tier-aware model selection via constructor injection) —
  the `model_routing` seam Decision 1's per-task provider + Decision 2
  reuse.
- ADR-021 (atomic quota), ADR-024/025 (observability + EU/GDPR) — the
  PII/residency constraints.
- DEVLOG Days 47–52 — the résumé-fix → resilience arc (escalating
  budget, circuit breaker, classification, honest-outage surfacing)
  that makes a failover provider a small, well-seamed addition.
