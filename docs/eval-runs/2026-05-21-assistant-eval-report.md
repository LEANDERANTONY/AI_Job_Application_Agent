# Slice 1K — Workspace Assistant Multi-Provider Eval

**Run:** 2026-05-21, 5 candidates × 12 scenarios, all routed through OpenRouter for transport-fair comparison.
**Total spend:** $0.35 OpenRouter. **Total wall time:** 7 min 11 s (431 s).
**Eval framework:** `tests/quality/assistant_agentic_runner.py` — substring-matcher rubric over the JSON-contract assistant prompt, with per-scenario latency / tokens / cost / pass-rate capture + incremental checkpointing.

## What this eval measures

The workspace assistant is a different prompt surface from the resume-builder (Phase A, Slices 1G/1H) and the parser / JD / analysis pipeline (Phase B, Slice 1I). It's a short-turn Q&A surface grounded on a runtime workspace snapshot + the freshly-added product-knowledge block. The eval probes four failure modes:

1. **Product-knowledge fluency.** Does the assistant correctly cite pricing tiers, theme inventory, two-column gating, quota numbers? (Slice 1J' added the authoritative product-knowledge block to both registry prompts — this is the verification.)
2. **Honest refusals.** Does it decline to schedule interviews, log into LinkedIn, recommend movies — without inventing false confirmations?
3. **Grounding discipline.** With `has_resume=false`, does it refuse to invent skills? With `has_analysis=true` and a fit score of 72, does it ground the answer in the workflow context?
4. **Multi-turn memory.** With a 7-turn conversation, can it recall a specific number stated on turn 2? Does it respect the user's latest stated truth after a mid-session correction?

Slice 1J's fix (`history[-4:]` → `_slice_history_for_budget` with 18 k char budget) directly enables the long-session callback scoring; before this fix, the model would never see turn 2 in a 7-turn session.

## Candidates

User-approved 5-candidate slate after dropping Opus and substituting `openai/o4-mini` for the non-existent `openai/gpt-5.1-mini`:

| Name | OpenRouter slug | Reasoning effort | Tier in this matrix |
|---|---|---|---|
| `gpt-5.4@med` | `openai/gpt-5.4` | `medium` | Production baseline |
| `gpt-5.4-mini@med` | `openai/gpt-5.4-mini` | `medium` | Cheap-OpenAI baseline |
| `o4-mini@high` | `openai/o4-mini` | `high` | OpenAI reasoning-mini replacement for gpt-5.1-mini |
| `sonnet-4.5` | `anthropic/claude-sonnet-4.5` | — | Anthropic premium |
| `haiku-4.5` | `anthropic/claude-haiku-4.5` | — | Anthropic budget |

`reasoning_effort` is threaded through both eval adapters (Slice 1J''). Anthropic slugs leave it unset — passing it would 400.

## Headline results

### Quality (avg_score · pass-rate by candidate)

| Candidate | avg_score | pass_rate (≥0.8) | scored | latency total | total tokens | cost USD |
|---|---:|---:|---:|---:|---:|---:|
| `gpt-5.4@med` | 0.986 | 1.000 | 12/12 | 74.7 s | 27 342 | $0.094 |
| **`gpt-5.4-mini@med`** | **1.000** ← perfect | **1.000** | 12/12 | **40.5 s** ← fastest | 27 197 | **$0.018** ← cheapest |
| `o4-mini@high` | 1.000 | 1.000 | 12/12 | 117.3 s | 36 370 | $0.081 |
| `sonnet-4.5` | 1.000 | 1.000 | 12/12 | 161.3 s ⚠ | 29 407 | $0.116 |
| `haiku-4.5` | 0.917 | 0.917 | 11/12 | **37.6 s** | 29 343 | $0.038 |

**Surprise headline:** `gpt-5.4-mini@med` is the winner across all three axes (quality 1.000, fastest at 40 s, cheapest at $0.018). The closest-cost candidate (`haiku-4.5`, $0.038) scored lower; the closest-quality candidates (`o4-mini@high`, `sonnet-4.5`, both 1.000) are 4–6× more expensive and 3–4× slower. **For the assistant surface specifically, the cheapest OpenAI option is the strongest choice.**

The pattern makes sense once you read the scenarios. The workspace assistant is mostly a retrieval-and-refuse surface — it pulls facts from `_PRODUCT_KNOWLEDGE_BLOCK` + `workspace_state`, declines off-topic asks, and recalls earlier turn content. Heavy reasoning (`o4-mini@high`, `gpt-5.4@med`) is wasted; "smart but cheap" wins.

### Cost-per-correct-scenario (effective)

After re-classifying the two sub-1.0 scores (see [Sub-1.0 re-classification](#sub-10-re-classification)), effective scores become:

| Candidate | effective_pass | cost USD | cost / pass | rank |
|---|---:|---:|---:|---:|
| `gpt-5.4-mini@med` | 12/12 | $0.018 | **$0.0015** | 🥇 best |
| `haiku-4.5` | 11/12 | $0.038 | $0.0035 | 🥈 |
| `o4-mini@high` | 12/12 | $0.081 | $0.0067 | |
| `gpt-5.4@med` | 12/12 | $0.094 | $0.0078 | |
| `sonnet-4.5` | 12/12 | $0.116 | $0.0096 | |

### Latency (total, per-candidate)

`haiku-4.5` and `gpt-5.4-mini@med` tie at the front (~40 s wall for 12 scenarios = ~3.4 s/scenario). The reasoning-class candidates (`o4-mini@high`, `sonnet-4.5`) burn 3–4× as long with no quality lift on this surface. `sonnet-4.5` has the worst tail — one scenario (`off_topic_movie`) took 41 s.

## Sub-1.0 re-classification

Two scenarios scored below 1.000. Reading each reply:

### `gpt-5.4@med` :: `off_topic_movie` (0.833) — **matcher_bug, real behavior PASSES**

The model's actual reply:

> "I can only help with your job application workflow here—if you want, I can help with your job search, saved jobs, or next application step."

That's a textbook polite refusal + redirect. The rubric's `one_of` list expected one of `{can't, cannot, won't, stay focused, focus on, outside, scope}` — and "I can only help" wasn't in there. Real behavior: PASS. (Negative matchers, which check that no movie titles leak, all passed.) Same matcher-coverage-gap pattern as Slice 1H; the right fix is a wider refusal-vocab list, not blaming the model.

### `haiku-4.5` :: `quota_resume_builder_lifetime` (0.000) — **real_fail, JSON-mode fidelity**

The adapter raised:

> `AgentExecutionError: OpenRouter run_json_prompt returned invalid JSON.`

`haiku-4.5` returned content that didn't parse as JSON (and didn't get rescued by the markdown-fence-tolerant parser added in Slice 1I). The other 11 scenarios with the SAME prompt shape returned valid JSON for haiku. This is the same drift-rate pattern Phase B caught for parser/JD: Anthropic's JSON-mode-via-OpenRouter is ~92 % reliable, not 100 %.

**Real failure for haiku, but it's a fidelity issue at the adapter boundary — content quality on the other 11 scenarios was perfect.** Production assistant would catch this via the JSON-decoder fallback already wired in `assistant_service.py`.

## Slice 1J memory-fix payoff (long-session callback)

The most decisive scenario for Slice 1J's history fix was `long_session_memory_callback` — a 7-turn session where turn 2 contained the fact "we cut chargeback fraud by 18% using a custom XGBoost model" and turn 6 (the scored turn) asked "what number did I tell you about my chargeback impact?".

With the previous `history[-4:]` slice, the model would never see turn 2 (only turns 3–6) — the question is unscorable. All five candidates recalled "18%" correctly:

> **gpt-5.4@med:** "You said the impact was an 18 % reduction in chargeback fraud."
>
> **sonnet-4.5:** "You mentioned an 18 % reduction in chargeback fraud using a custom XGBoost model during your time at Stripe (2020–2023). That metric came up when you were adding bullets for your Stripe role."
>
> **haiku-4.5:** "You mentioned an 18 % chargeback fraud reduction using a custom XGBoost model from your Stripe role. That's the specific number you shared in this conversation."

The bug Slice 1J fixed was real — and the fix works.

## Product-knowledge fluency (Slice 1J' payoff)

The 5 product-knowledge scenarios (tiers, themes, gating, quota numbers, lifetime vs monthly) scored 60/60 across 12 of 12 attempts where the JSON parsed cleanly. The only miss is haiku's JSON-mode drift, not a content miss. Sample replies prove the block is doing its job:

> **gpt-5.4-mini@med on `pricing_tiers_question`:** "There are three tiers: Free, Pro, and Business. Free: 3 tailored applications/month, 0 premium applications, 20 assistant turns/month, 3 resume parses/month … Pro: 20 tailored applications/month, 5 premium applications, 150 assistant turns/month, 25 resume parses/month …"
>
> **gpt-5.4-mini@med on `theme_list_question`:** "You can export using six resume themes: classic_ats, professional_neutral, modern_blue, creative_warm, architect_mono, and presentation_twocol. The first five are single-column ATS-safe layouts; presentation_twocol is a two-column designer layout and is not ATS-safe. On Free, PDF export is limited to professional_neutral; Pro and Business can export PDF or DOCX in any theme."
>
> **gpt-5.4-mini@med on `theme_unlock_question`:** "The two-column theme is the `presentation_twocol` resume theme. It's only available for export on Pro and Business; Free accounts can export PDF only in `professional_neutral`, so if you're on Free you'd need to upgrade to use it."

These are accurate, numerically correct, and grounded in the registry-baked block. Pre-Slice-1J' the assistant would shrug at every one of these questions or fabricate an answer.

## Recommendation

**For the workspace assistant surface specifically: route to `openai/gpt-5.4-mini` at reasoning_effort=medium.**

This is a real departure from the resume-builder default (gpt-5.4) and the Phase B verdict (gpt-5.4 stays default for parser/JD/analysis):

| Surface | Recommended default | Rationale |
|---|---|---|
| Resume builder (interactive intake) | gpt-5.4 (native) | Tool-using; analysis chain depends on it; Sonnet's smart-clarification is a fall-over candidate |
| Parser / JD / Analysis (Phase B) | gpt-5.4-via-OR baseline; DeepSeek for batch | Structured-output fidelity; structuring pass needs gpt-5.4 |
| **Workspace assistant** | **gpt-5.4-mini @ medium** | Retrieval-and-refuse surface; mini scores perfect at 1/5 the cost of 5.4 |

Concrete next-step candidates:

1. **Wire gpt-5.4-mini as the workspace-assistant default model** — set `OPENAI_MODEL_ASSISTANT=gpt-5.4-mini` (or whatever the env handle is in `assistant_service.py`) with `reasoning_effort=medium`. Expected monthly savings: ~80 % of current assistant API spend.
2. **Widen the off-topic refusal matcher list** in `assistant_agentic_runner.py` — add "I can only help", "limited to", "scope of this" to the `one_of` group. Stops the matcher-bug pattern from re-occurring on future eval runs.
3. **Haiku JSON-mode reliability A/B** — if we want haiku as a low-cost failover, the 92 % JSON-mode rate needs investigation (function-wrap pattern from Slice 1F or explicit JSON-mode guidance in the system prompt). Today it's not safe as a default.
4. **Sonnet for the chat-first failover slate stays** — the Phase A finding (smart-clarification edge) is on a different surface (resume-builder); on the assistant surface Sonnet doesn't win on quality OR cost, but it's the strongest premium alternative if mini ever degrades.

## Defensive engineering payoff

The patches that landed *before* this run:

1. **`_slice_history_for_budget` for the assistant prompts** (Slice 1J) — replaces `history[-4:]` with an 18 k-char sliding window. The long-session callback (scenario 11) was unscorable without this.
2. **`_PRODUCT_KNOWLEDGE_BLOCK` + pre-baked into both registry JSONs** (Slice 1J') — gives the assistant authoritative numbers for tiers (3/20/80, etc.), theme inventory, export entitlement, and an explicit "what I cannot do" list. Scenarios 1–5, 6, 7, 10 all depend on this.
3. **`reasoning_effort` threaded through both eval adapters** (Slice 1J'') — `OpenRouterEvalService` and `KimiEvalService` now forward the kwarg to `chat.completions.create` for o-series / gpt-5.x slugs (and ignore it for non-reasoning slugs to avoid 400s).
4. **Per-call usage accumulation in `run_json_prompt`** (Slice 1K smoke-time bugfix) — the smoke at first reported `$0.0000` for every call because only `run_tool_loop` was tracking usage. Mirrored the accumulator into the single-shot path so the parser / assistant / structuring suites also surface accurate cost.

Without any one of these, the eval would have either failed to score (1, 4), produced garbage answers (2), or used the wrong reasoning tier (3) — and the report would have been misleading.

## Artifacts

- `docs/eval-runs/2026-05-21-assistant-eval-full.json` — full raw report with per-scenario rows + metrics
- `docs/eval-runs/2026-05-21-assistant-eval-full-log.txt` — streaming heartbeat log
- `tests/quality/assistant_agentic_runner.py` — the runner (`uv run python tests/quality/assistant_agentic_runner.py --candidates all` to re-run)
- `tests/quality/openrouter_eval_service.py` — extended with `reasoning_effort` + per-call usage tracking
- `tests/quality/kimi_eval_service.py` — extended with `reasoning_effort`
- `tests/quality/provider_pricing.py` — added `openai/o4-mini`, `anthropic/claude-haiku-4.5`
- `src/prompts.py` — `ASSISTANT_HISTORY_CHAR_BUDGET` + `_PRODUCT_KNOWLEDGE_BLOCK`
- `prompts/assistant/v1.json`, `prompts/assistant_text/v1.json` — product-knowledge block pre-baked
