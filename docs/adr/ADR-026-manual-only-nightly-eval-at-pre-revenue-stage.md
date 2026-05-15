# ADR-026: Manual-Only `nightly_eval` at Pre-Revenue Stage

Date: 2026-05-16

Status: Active (auto-revert when revenue justifies)

## Context

Day 44 introduced `backend/nightly_eval.py` — a CLI that wraps the existing per-agent quality runners under `tests/quality/` into a single unattended batch job, aggregates each runner's headline metric into one JSON summary, compares the metrics against a saved baseline, and exits non-zero on regression beyond a configurable threshold. The recommended cron line in `docs/operations.md` runs it daily at 3:30 UTC.

When the cron line was about to be installed, a re-check of the cost shape produced an uncomfortable number:

- Each `--include-llm` run = the full 5-runner suite, including `orchestrator_e2e` which runs the four-agent pipeline (Tailoring + Review + ResumeGen + CoverLetter) end-to-end against six fixture pairs.
- Per-run cost: **~\$0.25 in OpenAI** at `gpt-5.4-mini` baseline pricing.
- Daily cadence: **~\$7.50/month**, every month, forever, with zero paying users today.

That's not catastrophic — it's a small dollar amount — but it's also pure cost paid against a safety net for a failure mode (silent model regression) that hasn't materialized yet. With no paying users to amortize it against, and with a sibling product (HelpmateAI) that faces the same trade-off at a much larger \$45-90/mo scale, the discipline of "no automatic LLM spend before first revenue" needed to apply consistently across both products.

The decision had to balance:

- **Real protection value.** The nightly eval is the right tool to catch silent drift after a model upgrade — the day OpenAI rotates a model snapshot under our nose (which has happened) is exactly when we want today's metrics on yesterday's baseline.
- **Real cost.** ~\$7.50/mo at pre-revenue stage is small in absolute terms but is also indefinite, growing if cadence or coverage expands, and on a product with zero users to justify it.
- **Reversibility.** Whatever we do now must be one cron-line edit away from "back on" the moment a paid user lands and the COGS math flips.

## Decision

Switch `nightly_eval` to **manual-only mode** by default. The script still exists, is still tested, and is still runnable from a shell. The single lever is the crontab:

1. **No active cron line on the VPS.** The `30 3 * * * docker exec ai-job-application-agent-api python -m backend.nightly_eval --include-llm ...` line stays documented in `docs/operations.md` and is shown as a commented block in `crontab -e`, but is not active. `crontab -l` on the VPS shows zero `nightly_eval` lines.
2. **Free deterministic cron stays an option.** The deterministic-only runners (`resume_parser`, `jd_parser`) cost \$0 to run and could in principle be scheduled. They're not scheduled either, because their value is low without the LLM-based runners alongside (a deterministic-parser drift would be caught by the regular test suite on every PR; that's not what the nightly eval is for).
3. **No Sentry Crons monitor.** Unlike the sibling HelpmateAI product, this CLI never had a Sentry monitor wired in — the script is pure-CLI, no in-process check-in. So nothing to delete, nothing to gate behind an env var.

### Manual run pattern

For ad-hoc spot-checks (e.g. after shipping a meaningful model or prompt change):

```bash
ssh -p <port> <user>@<vps-host> \
  "docker exec ai-job-application-agent-api python -m backend.nightly_eval \
     --include-llm \
     --baseline /var/log/aijobagent-nightly-eval.last.json \
     --output /var/log/aijobagent-nightly-eval.last.json"
```

Returns the headline metrics + regression markers. Cost per spot-check: ~\$0.25. Use it whenever a prompt change, model swap, or agent-pipeline change lands that could plausibly move quality.

### Re-enable path (one-step flip when revenue justifies)

1. **Uncomment the cron line.** `docs/operations.md` has the recommended line. Move it out of the documentation block and into an active crontab entry.

That's the whole flip. The script's baseline-comparison logic already handles "first night without a prior baseline" gracefully (treats it as no-regression), so the first scheduled run just establishes the baseline for tomorrow's comparison.

### Recommended cadence on re-enable

When revenue does justify turning it back on, the recommended cadence is **Mon + Thu (twice a week)** rather than daily. ~\$2/mo, 3-4 day detection window. Daily is only justified once revenue is large enough that 24h detection on a model regression is the right SLO.

## Consequences

### Positive

- **~\$7.50/month saved at pre-revenue stage.** Small absolute but real, and the discipline matters as a signal — "no automatic LLM spend before first revenue" is the rule. Letting this one slip past would establish the wrong precedent.
- **Consistency with sibling product.** HelpmateAI's nightly eval is also manual-only (ADR-020 over there). Both products have the same posture so a future "re-enable when revenue is here" decision applies uniformly.
- **Manual runs still work.** The script is fully tested + runnable from a shell. The operator can spot-check whenever a prompt or model change lands without committing to recurring cost.
- **Re-enable is trivial.** Single crontab edit. No code change, no env-var migration, no monitor recreation. The fence is the cron line; nothing else.

### Negative

- **Lose continuous drift detection.** A model regression that lands between manual runs is invisible until the next manual run. Mitigation: model upgrades + prompt changes are infrequent enough at MVP stage that "after each change" coverage approximates daily coverage.
- **Operational knowledge required.** The operator has to remember to run the eval after meaningful changes. Mitigation: this ADR + the DEVLOG Day 44 entry + the `docs/operations.md` cron block all flag the pattern.
- **No accumulated baseline timeline.** Without scheduled runs, there's no "metrics over the last 30 nights" view to spot slow drift. Mitigation: spot-checks save to the same baseline file, so each manual run does update the baseline forward — drift across a longer window still gets caught, just at lower cadence.

### Neutral

- **The CLI doesn't have a Sentry monitor.** Unlike HelpmateAI's nightly eval which had a Crons heartbeat that needed env-gating, this one is plain CLI. Simpler manual-only posture as a result.

## Alternatives considered

- **Daily forever (don't change anything).** Costs ~\$7.50/mo at pre-revenue, ~\$90/year. Rejected on the discipline rather than the absolute cost — keeping a recurring LLM spend live for a safety net no user benefits from yet sets the wrong precedent.
- **Weekly only (1x/week).** Single Sunday run, ~\$1/mo. Considered. Rejected because the single weekly data point makes regression hard to distinguish from fixture noise, and the 7-day detection window is uncomfortably wide. Mon+Thu (twice a week) is the better cadence — kept as the re-enable default.
- **CI-triggered eval on prompt/model changes only.** Detect when a prompt JSON or `OPENAI_MODEL_*` env changes in PR diffs + auto-run eval. Brittle: most regressions come from OpenAI rotating snapshots silently, not from our config changing, so the trigger would catch the wrong class of change.
- **Run the deterministic-only subset on schedule.** Costs \$0 and gives some signal. Rejected: the parser scorecards are also covered by the dev test suite on every PR, so the value of nightly-only signal there is marginal. The LLM runners are where the unique value lives.
- **Delete `backend/nightly_eval.py` until revenue lands.** Throws away the tested CLI + docs. Re-enabling would become a multi-day rebuild. Rejected — keeping the safety net cocked but unloaded is cheaper than disassembling it.

## References

- DEVLOG Day 44: Schema-strict outputs, nightly eval CLI, cost tracking, and Codex review fixes
- `backend/nightly_eval.py` — the CLI, no Sentry monitor wiring (pure-CLI manual-run shape)
- `docs/operations.md` — the cron block is documented but commented out
- ADR-024: Observability stack — the Sentry Logs surface that would be the natural alerting target on regression
- HelpmateAI ADR-020: same decision at the sibling product's larger cost scale
