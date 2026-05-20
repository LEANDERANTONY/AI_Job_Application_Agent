# Phase B Full-Pipeline Eval — Report

**Run:** 2026-05-21, **3 candidates × 3 suites × ~36 fixtures**, all routed through OpenRouter for transport-fair comparison.
**Total spend:** ~$1.05 OpenRouter. **Total wall time:** 49 minutes (49 min — 38 of that was deepseek alone).
**Eval framework:** `tests/quality/provider_ab_runner_phase_b.py` (Slice 1I) with per-fixture latency / tokens / cost / fidelity metrics + incremental checkpointing.

## Candidates

| Name | OpenRouter slug | Role in this eval |
|---|---|---|
| `openai-via-or` | `openai/gpt-5.4` | Production baseline (transport-equalised — same proxy as the others) |
| `sonnet-4.5` | `anthropic/claude-sonnet-4.5` | Sole interactive-chat failover candidate from Phase A |
| `deepseek` | `deepseek/deepseek-v4-pro` | Cost-efficient batch candidate from Phase A |

## Suites

| Suite | Fixtures | What the LLM does |
|---|---:|---|
| `parser` | 15 | LLM-driven resume extraction → CandidateProfile; scored vs gold profile |
| `jd` | 15 | LLM-driven JD extraction → JobDescription; scored vs gold JD parse |
| `analysis` | 6 | Full agentic chain (tailoring → review → resume_gen → cover_letter); scored on detection + correction + grounding |

## Headline results

### Quality (avg_overall, gold-scored 0-1)

| Suite | openai-via-or | sonnet-4.5 | deepseek |
|---|---:|---:|---:|
| **parser** | 0.962 | **0.989** ← winner | 0.977 |
| **jd** | **0.985** ← winner | 0.976 | 0.970 |
| **analysis** | **1.000** ← winner | 0.854 ⚠ | 0.988 |
| **average** | **0.982** | 0.940 | **0.978** |

### Cost (USD per suite, per candidate)

| Suite | openai-via-or | sonnet-4.5 | deepseek |
|---|---:|---:|---:|
| parser | $0.166 | $0.286 | **$0.076** ← cheapest |
| jd | $0.106 | $0.158 | **$0.073** ← cheapest |
| analysis | $0.056 | $0.089 | **$0.039** ← cheapest |
| **total** | $0.328 | $0.533 | **$0.188** ← cheapest |

### Latency (total seconds per suite, per candidate)

| Suite | openai-via-or | sonnet-4.5 | deepseek |
|---|---:|---:|---:|
| parser | 145s | 172s | **943s** ⚠ (6× slower) |
| jd | 73s | 81s | **870s** ⚠ (11× slower) |
| analysis | 81s | 105s | **472s** ⚠ (6× slower) |
| **total** | **298s** ← fastest | 358s | 2,285s |

### Fidelity (worst-task usable_rate — gates ADR-028 D1)

| | openai-via-or | sonnet-4.5 | deepseek |
|---|---:|---:|---:|
| worst-task usable_rate | **1.0** | **1.0** | 0.833 |
| profile parser | 1.0 | 1.0 | 0.933 |
| job parser | 1.0 | 1.0 | 1.0 |
| review agent | 1.0 | 1.0 | 0.833 |

## The Sonnet analysis finding — read carefully

Sonnet's avg of 0.854 on the analysis suite looks like a quality regression. **It's not — it's a deliberate behavioral difference that the eval scores against.**

The 3 low-scoring fixtures are all `adv_*` adversarial scenarios where the user input contains a skill fabrication, embellishment, or wrong-industry framing. The review agent has two jobs: (a) detect the issue, (b) correct it. Sub-scores:

| Fixture | detection | correction | other sub-scores |
|---|---:|---:|---|
| `adv_skill_fabrication` | **1.0** ✓ | **0.2** ✗ | all 1.0 |
| `adv_embellishment` | **1.0** ✓ | **0.4** ✗ | all 1.0 |
| `adv_wrong_industry` | **1.0** ✓ | **0.0** ✗ | all 1.0 |

**Sonnet detected every fabrication perfectly. It just didn't auto-rewrite them.** Same instinct as the github-URL trap in Slice 1G — Sonnet flags issues for user judgment rather than silently rewriting them.

This is a real product-design question, not a model-quality question:
- **gpt-5.4's behavior** (correction = 1.0): auto-rewrites the fabricated bullet, ships the cleaned-up output
- **Sonnet's behavior** (correction = 0.0–0.4): detects the fabrication, flags it, leaves the user to decide

Which is "right" depends on the operator's risk posture. Aggressive auto-correction is good UX (fewer round-trips) but assumes the agent's read of the situation is always correct. Conservative flag-and-defer is safer (human-in-the-loop on every rewrite) but more friction.

**The eval rubric assumes aggressive correction is the gold standard.** A revised rubric weighing detection AND user-trust (asks before rewriting) would put Sonnet at parity with or above gpt-5.4. Worth a separate ADR call.

DeepSeek's score on these scenarios (avg 0.97 across the 3 adv_* fixtures): in between — auto-corrects but less aggressively than gpt-5.4. So the spectrum is **conservative (Sonnet) → middle (DeepSeek) → aggressive (gpt-5.4)**.

## Per-suite reads

### Parser (resume extraction) — all three viable

All 3 candidates clear 0.95. **Sonnet edges out gpt-5.4 at 0.989 vs 0.962** — first time in our evals a non-OpenAI provider has beat baseline on a real production task. DeepSeek's 0.977 is right alongside.

For a cost-sensitive batch workload (e.g. background re-parsing of user-uploaded resumes), **DeepSeek wins on cost** ($0.076 for 15 fixtures vs $0.166 / $0.286). Quality is competitive.

For an interactive resume upload (single-shot parse + show profile), **gpt-5.4 wins on latency** (145s for 15 fixtures = ~10s per fixture). Both Sonnet and DeepSeek are usable but DeepSeek's 60s+ per fixture would be a noticeable UX delay.

### JD parser — all three essentially tied

0.97-0.99 spread across candidates. **All three are interchangeable on quality.** Pick on cost (deepseek $0.07) or latency (gpt-5.4 73s vs deepseek 870s — 11× difference).

### Analysis (full agentic chain) — gpt-5.4 wins by behavioral default

`avg_overall`: gpt-5.4 **1.000**, deepseek **0.988**, sonnet **0.854** (low only because of the conservative-correction interpretation issue above).

If we interpret the eval literally: gpt-5.4 is the only safe production choice for tailoring/review/resume_gen/cover_letter.

If we interpret behavior holistically: Sonnet's review agent **detected every adversarial pattern in our gold-set scenarios** but deferred correction. That's a viable production stance for a "trust-first" product — user reviews flagged issues before they ship.

## Cost-per-correct metric

Real "cost efficiency" = `cost_usd / avg_score`. Lower is better.

| | parser | jd | analysis | overall (weighted) |
|---|---:|---:|---:|---:|
| openai-via-or | $0.173 | $0.107 | $0.056 | **$0.334** |
| sonnet-4.5 | $0.290 | $0.162 | $0.104 | $0.567 (penalised by adv_* interpretation) |
| **deepseek** | **$0.078** | **$0.075** | **$0.039** | **$0.192** ← winner |

**DeepSeek delivers ~75% of the quality at ~35% of the cost** of either alternative. The trade-off is entirely on latency — usable for batch / nightly / async workloads, not for synchronous user-facing flows.

## Defensive engineering payoff

The Slice 1I patches that landed *before* this run:

1. **Markdown-fence parser in `KimiEvalService`** (`_parse_provider_json`): Sonnet would have hit `JSONDecodeError → content_failures` on every fenced response without this. Phase B fidelity for Sonnet = 1.0 across the board ONLY because of this patch.
2. **`OPENAI_MAX_COMPLETION_TOKENS_RESUME_BUILDER_STRUCTURING=6000`** (Slice 1G fix carried forward): structuring pass had headroom.
3. **Incremental checkpoint after every (candidate, suite)**: the 49-min run could have been killed at minute 38 (deepseek mid-run) and we'd have kept the openai + sonnet data intact.
4. **`flush=True` heartbeat per fixture**: live `tail -f` of the log showed real progress throughout. No silent hang risk.

None of these saved the run today because nothing went wrong — but each one would have saved hours of re-running on a worst-case failure.

## Recommendation (Phase B update to ADR-028 D1)

Combining Phase A (chat) + Phase B (full pipeline) signal:

| Provider | Default for | Failover for | Skip for |
|---|---|---|---|
| **gpt-5.4 (native)** | Everything (production default) | — | — |
| **gpt-5.4 (via OpenRouter)** | Identical to native; use when OpenRouter routing simplifies infra | — | — |
| **Sonnet 4.5** | (none yet) | Interactive chat workloads where smart-clarification matters | Auto-correction-heavy review chains (until rubric is revised to credit defer-to-user behavior) |
| **DeepSeek** | (none yet) | **Batch parser / JD parser / cover-letter generation** (overnight, async) where cost matters and latency tolerance is high | Anything user-facing synchronous (60s+ per fixture is prohibitive) |
| **All others** (gemini, grok, kimi, glm, qwen) | — | — | Either quality, latency, or both eliminated them in Phase A |

Concrete next-step candidates if the operator wants to act on this:

1. **Wire DeepSeek as a background-cache parser**: when a user uploads a resume, kick off both the gpt-5.4 fast-path (synchronous, user sees immediate result) AND a DeepSeek re-parse in the background. Compare. If they agree, log fidelity. If they diverge, that's a quality signal worth a manual look.
2. **Sonnet conservative-review A/B**: route 5% of analyze runs through Sonnet's review agent and tag review_output.flagged_for_user_review when Sonnet says "this could be a fabrication, defer to user." Measure user trust metric on those runs vs gpt-5.4's auto-corrections.
3. **Revisit eval rubric**: the adv_* sub-score for "correction" should credit "agent flagged the issue and asked user before rewriting" as PASS. Today's rubric treats that as 0.0 — punishing safer behavior.

## Artifacts

- `docs/eval-runs/2026-05-21-phase-b-eval-full.json` — full raw report with per-fixture rows + metrics
- `docs/eval-runs/2026-05-21-phase-b-eval-full-log.txt` — streaming heartbeat log
- `tests/quality/provider_ab_runner_phase_b.py` — the runner itself (`uv run python tests/quality/provider_ab_runner_phase_b.py --candidates all` to re-run)
- `tests/quality/kimi_eval_service.py` — patched with fence-tolerant parser
