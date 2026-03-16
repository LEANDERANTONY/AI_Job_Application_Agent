# ADR-010: Single-Pass Review Corrections and Task-Tuned Model Budgets

## Status

Accepted

## Context

The earlier supervised workflow had grown into a more expensive sequence than the product needed:

- `ProfileAgent` and `JobAgent` were generating summaries that mostly restated deterministic candidate and JD structure already available elsewhere in the system
- the orchestrator ran a bounded revision loop that resent tailoring, strategy, and review through another full pass when review rejected the first draft
- Review was functioning as both a gate and a revision trigger, but the product goal had shifted toward direct grounded correction rather than repeated full-pipeline iteration
- real runtime logs showed that the second tailoring + strategy + review pass was one of the largest contributors to total latency
- the final high-trust stages were worth more model budget than the early summarization stages, but the routing defaults had not yet been tightened around that reality

At the same time, the product still needed:

- deterministic fit analysis as the grounding backbone
- a strong Tailoring step because that stage carries the most content-heavy rewrite work
- a strong Review step that can reject or repair unsupported wording
- a final Resume Generation step that turns the reviewed output into the export-ready artifact

## Decision

Adopt a single-pass supervised workflow with direct review corrections and task-tuned reasoning / output budgets.

The accepted workflow is:

1. `fit`
2. `tailoring`
3. `strategy`
4. `review`
5. `resume_generation`

Implementation details:

1. remove live `ProfileAgent` and `JobAgent` execution from the active orchestrator path
2. keep deterministic `CandidateProfile`, `JobDescription`, `FitAnalysis`, and `TailoredResumeDraft` as the source-of-truth inputs
3. make Review return direct corrected tailoring and strategy outputs when repairs are straightforward
4. stop rerunning the entire tailoring / strategy / review chain after review feedback
5. define review approval in terms of the final corrected state, not only the cleanliness of the incoming draft
6. route earlier cheaper stages to cheaper reasoning levels than the final grounding stages
7. tune output-token caps by observed usage instead of using one oversized default for every task

The current routing defaults following this decision are:

- `fit`: `gpt-5-mini-2025-08-07` with `low` reasoning and a 1600-token output cap
- `tailoring`: `gpt-5-mini-2025-08-07` with `medium` reasoning and a 3200-token output cap
- `strategy`: `gpt-5-mini-2025-08-07` with `low` reasoning and a 1500-token output cap
- `review`: `gpt-5.4` with `medium` reasoning and a 4000-token output cap
- `resume_generation`: `gpt-5.4` with `medium` reasoning and a 3000-token output cap

## Alternatives Considered

### 1. Keep the full Profile + Job + Fit + Tailoring + Strategy + Review + Resume Generation stack

Rejected because Profile and Job were not adding enough unique value relative to the deterministic data they were summarizing, while still costing additional sequential model latency.

### 2. Keep the revision loop but reduce model size only

Rejected because the largest avoidable cost was architectural: repeated full-pipeline passes. Model tuning alone would not remove that structural latency.

### 3. Remove Review entirely and trust Tailoring / Strategy output directly

Rejected because Review is still the main grounding defense against unsupported claims, inferred tenure, and overstated tooling experience.

### 4. Lower every stage to the same cheapest reasoning tier

Rejected because the stages do not have the same risk profile. Review and final resume generation justify more careful reasoning than early fit and strategy summarization.

## Consequences

- the workflow becomes materially faster because it removes redundant live stages and the second-pass loop
- deterministic inputs remain the grounding backbone even though the live agent count is smaller
- Review becomes a direct correcting editor rather than only a rejection gate
- the meaning of `approved` must reflect the final corrected output state, which required updates to UI and report wording
- model routing becomes easier to reason about because costlier reasoning is reserved for the stages that materially affect grounding and final export quality
- PDF output quality remains a separate follow-up concern; the workflow and routing changes improve runtime and correctness, but they do not solve visual export polish by themselves
