# Resume Builder × `gpt-5.4-mini` (medium + low) — eval addendum

**Run:** 2026-05-21, 2 candidates × 16 effective scenarios (web_search scenarios auto-skipped for non-native-OpenAI providers).
**Total spend:** $0.27 OpenRouter. **Total wall time:** ~7 min 30 s.
**Eval framework:** `tests/quality/resume_builder_agentic_runner.py` — agentic tool-loop scoring with the substring-rubric scenarios (same shape as Slice 1H comprehensive eval).

## What this eval answers

Slice 1K (workspace assistant) showed that `gpt-5.4-mini@low` matched `gpt-5.4@medium` quality at lower cost / latency on the retrieve-and-refuse surface. The obvious next question: does that hold on the **heavier** resume-builder surface — where the model has to drive a tool loop (`fetch_github_readme`), track conversation across many turns, fire `proactive_offer` at the right moments, populate `pending_followups[]`, and survive the 11 K-char structuring-pass canary that broke Sonnet / Gemini / DeepSeek in Slice 1H?

Slate intentionally narrow: just the two mini variants. We're testing whether mini can replace the gpt-5.4 default, not re-running the full ADR-028 D1 matrix. Sonnet / Gemini / DeepSeek baselines come from Slice 1H. Haiku skipped per operator request — Slice 1K's JSON-mode reliability concern (~92 %) is a production no-go on this surface.

## Results (today's run)

| Candidate | raw pass | effective | latency total | per-scn | cost | total tokens |
|---|---:|---:|---:|---:|---:|---:|
| `gpt-5.4-mini@med` | 14 / 16 | **16 / 16** | 247 s | 15.4 s | $0.144 | 231 930 |
| **`gpt-5.4-mini@low`** | 15 / 16 | **16 / 16** | **200 s** | **12.5 s** | **$0.127** | 223 417 |

Re-classification: both candidates trip the **curly-apostrophe matcher bug** (same family Slice 1H flagged). Real behavior PASSES on every flagged "fail":

- `out_of_scope_capability_probe` (both candidates fail raw):
  - mini@med: *"I can't schedule interviews, but I can keep helping with your resume…"*
  - mini@low: *"I can't schedule interviews, but I can help you finish your resume so you're ready to apply…"*

  Both are textbook refusal-with-redirect. The rubric's `one_of` list expected straight-apostrophe `"can't"`; the model emits U+2019 `"can't"`. Same bug Slice 1H caught across providers — the resume-builder runner just never got the normalisation patch the assistant runner has.

- `failed_tool_graceful_fallback` (mini@med fails, mini@low passes):
  - mini@med: *"I couldn't fetch that GitHub repo because the link looks invalid or unavailable. Please **paste** the project's tech stack…"*
  - mini@low: *"I couldn't fetch that README because the repo looks unavailable. Please **describe** the project in your own words…"*

  Behaviorally identical (both honestly explain the failure + ask the user to share). mini@low happened to use the magic keyword "describe" that the rubric lists; mini@med used "paste" which isn't in the list. Plus the same curly-`"couldn't"` issue. mini@med fails the matcher, not the behavior.

So **both candidates are effectively 16 / 16** — perfect on every behavioral signal the rubric is actually trying to test. The only daylight between them is that mini@low got lucky with vocabulary on one scenario.

## Comparison vs Slice 1H baselines (apples-to-apples scope)

Pulling the candidates from `docs/eval-runs/2026-05-21-agentic-eval-v3-comprehensive-5cand.json` for the 16 OpenRouter scenarios:

| Candidate | effective | per-scn lat | total cost | notes |
|---|---:|---:|---:|---|
| `openai` (native gpt-5.4) | 18 / 18 | 8.7 s | $0.142 | Native Responses-API path (faster than OR proxy) |
| `openai-via-or` (gpt-5.4) | 16 / 16 | 8.3 s | ~$0.12 ¹ | Same model, OpenRouter-routed |
| **`gpt-5.4-mini@low`** (new) | **16 / 16** | **12.5 s** | **$0.127** | Reasoning-effort=low |
| `gpt-5.4-mini@med` (new) | 16 / 16 | 15.4 s | $0.144 | Reasoning-effort=medium |
| `sonnet-4.5` | 14 / 16 ⚠ | 17.1 s | $0.977 | 1 real fail on `structured_payload`; 8× the cost |
| `deepseek` | 14 / 16 ⚠ | 57.6 s ⚠ | $0.173 | Real fails on `proactive_offer` + `structured_payload`; 6× slower |
| `gemini` | 12 / 16 ⚠ | 34.4 s | $0.919 | 4 real fails incl. regex-fallback drop |

¹ Slice 1H reported `$0.00` due to the `run_json_prompt` usage-tracking bug we fixed in Slice 1K (Slice 1J'' commit). Estimated ~$0.12 from token totals × pricing.

### Per-axis honest read

**Quality.** All three OpenAI options (native, via-OR, both mini variants) tie at effective perfect on this rubric. Sonnet, DeepSeek, Gemini all have real fails on either `structured_payload` (the 11 K-char structuring pass) or `proactive_offer` firing. **Mini IS strong enough on this surface — it survives the canary scenarios that knocked out the non-OpenAI candidates.**

**Latency.** This is where the story flips vs the assistant findings.

- gpt-5.4 via OR: **8.3 s / scenario** (no reasoning_effort — just answers)
- mini@low: 12.5 s / scenario (50 % slower)
- mini@med: 15.4 s / scenario (85 % slower)

The reasoning-effort tokens add real wall-clock latency. On the assistant surface (short, retrieve-and-refuse turns) the reasoning overhead was minor; on the resume builder (long multi-turn intake with tool calls) it's a noticeable 4–7 s per turn slower. **For an interactive resume-builder where the user is staring at a typing indicator, gpt-5.4 wins on UX.**

**Cost.** Mini's per-token rate is 5× cheaper than gpt-5.4's, but reasoning-effort uses extra completion tokens (~8 K extra at low effort, ~16 K extra at medium). Net:

- gpt-5.4 via OR: ~$0.12 for 16 scenarios (~$0.0075 / scenario)
- mini@low: $0.127 for 16 scenarios (~$0.008 / scenario)
- mini@med: $0.144 for 16 scenarios (~$0.009 / scenario)

**On the resume-builder surface, mini@low costs roughly the same as gpt-5.4.** The per-token win is eaten by the reasoning-token overhead. This is the opposite of what we saw on the assistant surface, where mini was 5× cheaper.

## Why the assistant story doesn't transfer

The workspace assistant is short turns (one user question, one short JSON answer). The reasoning budget barely fires before the answer lands; mini@low spends almost no extra tokens vs no-reasoning. So mini's 5× per-token discount fully translates to cost.

The resume builder is long, tool-using, multi-turn agentic work. Each turn the reasoning model thinks before AND after each tool call. Reasoning tokens accumulate. The discount on per-token rates is offset by the extra tokens spent reasoning. **Net cost ends up similar to gpt-5.4 — and latency suffers.**

This is a meaningful design lesson: reasoning models are great when the inference is short and structured (assistant Q&A) and less great when there's already a lot of agentic structure providing the "reasoning" externally (multi-turn tool loop).

## Recommendation

**Keep gpt-5.4 as the resume-builder production default.** Same recommendation as Slice 1H — this run doesn't move the needle. The mini variants are workable backups but don't earn the switch:

| Surface | Recommended default | Why |
|---|---|---|
| **Workspace assistant** | `gpt-5.4-mini` @ reasoning_effort=low | 1.000 perfect, 1/5 the cost of gpt-5.4, 2-3× faster |
| **Resume builder** (interactive) | `gpt-5.4` (native or via OR) | Same effective quality as mini, but faster (~50 %) at similar cost |
| **Resume builder** (batch / async if ever added) | `gpt-5.4-mini@low` is fine | Quality matches; latency tolerance is the only difference |

Non-OpenAI candidates remain unsuitable for the resume-builder surface on this matrix — Sonnet's `structured_payload` miss is the blocker, and the cost premium isn't justified by anything mini doesn't already deliver.

## Defensive-engineering payoff (carries from earlier work)

This eval was only this fast / cheap because of upstream fixes:

1. **`reasoning_effort` thread-through** (Slice 1J''): Mini A/B at medium vs low only works because the adapter forwards the effort signal to OpenRouter; otherwise both variants would run at default effort and we'd be measuring noise.
2. **Per-instance default reasoning_effort** (this addendum): Added `default_reasoning_effort` to `OpenRouterEvalService.__init__` so the eval matrix can inject the effort tier per candidate without touching production caller code in `resume_builder_service.py`. The kwarg falls back to the instance default when production callers don't pass one.
3. **`run_json_prompt` usage accumulator** (Slice 1K bugfix): Without this, the structuring-pass cost would still read $0.00 — same bug Slice 1H hit on `openai-via-or`. Today's mini cost numbers are accurate because of the patch.

## Artifacts

- `docs/eval-runs/2026-05-21-resume-builder-mini-eval.json` — full raw report with per-scenario rows + metrics for both candidates
- `docs/eval-runs/2026-05-21-resume-builder-mini-eval-log.txt` — streaming heartbeat log
- `tests/quality/resume_builder_agentic_runner.py` — updated candidate dict (now `{slug, reasoning_effort}` per entry); rerun with `--candidates gpt-5.4-mini@med,gpt-5.4-mini@low`
- `tests/quality/openrouter_eval_service.py` — `default_reasoning_effort` constructor param; per-call kwarg falls back to instance default
- Baselines for comparison: `docs/eval-runs/2026-05-21-agentic-eval-v3-comprehensive-5cand.json` + `docs/eval-runs/2026-05-21-comprehensive-eval-report.md` (Slice 1H)
