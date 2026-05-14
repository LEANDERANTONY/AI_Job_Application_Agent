# Operations runbook

Day-2 operational tasks that don't fit cleanly into `architecture.md`
or an ADR. Cron schedules, alert thresholds, manual runbook entries.

## Nightly quality eval (`backend.nightly_eval`)

The nightly eval is the production-safety guard against silent model
drift. The quality runners under `tests/quality/` already exist for
human inspection; this CLI wraps them into a single batch job suitable
for an unattended cron and exits non-zero on any regression.

### What it runs

- `resume_parser` — deterministic regex parser scorecard against the 15
  fixtures in `tests/quality/sample_resumes/`. Fast (<5s).
- `jd_parser` — deterministic JD parser scorecard against the 15
  fixtures in `tests/quality/sample_jds/`. Fast (<5s).
- `tailoring` — TailoringAgent against six (resume, JD) pairs. Runs in
  deterministic fallback by default; opt into LLM mode with
  `--include-llm` (~$0.05 / run).
- `review` — ReviewAgent on the three clean scenarios. Adversarial
  scenarios stay in the dev workflow because they need an LLM to
  produce stable approval-rate signals.
- `orchestrator_e2e` — full Tailoring → Review → ResumeGen → CoverLetter
  chain. Requires `--include-llm` (~$0.20 / run); skipped otherwise.

Each runner emits a single headline metric (typically average overall
score across fixtures) and a pass/fail bit. The script's exit code is
0 only when every runner passed AND no headline metric dropped by
more than `--regression-threshold` (default 5 percentage points).

### Output

`python -m backend.nightly_eval` prints a one-line JSON summary to
stdout and optionally writes it to `--output`. The JSON includes:

```json
{
  "started_at": "2026-05-15T03:30:00Z",
  "duration_seconds": 31.2,
  "include_llm": true,
  "regression_threshold": 0.05,
  "runners": [{"name": "tailoring", "passed": true, "headline_metric": 0.83, ...}],
  "failures": [],
  "regressions": [],
  "overall_pass": true
}
```

### VPS cron

The backend container ships with `backend/nightly_eval.py` baked in.
Add this line to the host crontab so each night's run lands in the
shared log volume:

```
30 3 * * * docker exec ai-job-application-agent-api python -m backend.nightly_eval >> /var/log/aijobagent-nightly-eval.log 2>&1
```

Run with `--include-llm` when the host has the OpenAI key configured
and you want full coverage:

```
30 3 * * * docker exec -e OPENAI_API_KEY=$(cat /etc/aijobagent/openai_key) ai-job-application-agent-api python -m backend.nightly_eval --include-llm --baseline /var/log/aijobagent-nightly-eval.last.json --output /var/log/aijobagent-nightly-eval.last.json >> /var/log/aijobagent-nightly-eval.log 2>&1
```

Picking `--baseline` and `--output` to point at the same path makes
each night's run compare itself against the previous night's snapshot.
The first night runs without a baseline (treated as "no regression
check") and then writes one for the next night.

### Alerting

The script logs `nightly_eval_runner_finished` per runner and a single
`nightly_eval_failed` / `nightly_eval_regressed` warning at the end when
something is off. Two reasonable alerting hookups depending on what
the rest of the stack uses:

- **Cheap path**: tail `/var/log/aijobagent-nightly-eval.log` from a
  log shipper (Datadog, Promtail, Better Stack) and alert on
  `"overall_pass": false` substrings.
- **Structured path**: an admin endpoint can read the last `--output`
  JSON on demand. No new table needed — the run summary lives on
  disk; the cost-tracking table (`aijobagent_run_traces`) covers the
  per-call cost story separately.

### Manual debugging

Run it locally without LLM to spot fixture issues:

```
python -m backend.nightly_eval --runner resume_parser --runner jd_parser -v
```

To rerun a single runner with LLM mode after a regression alert:

```
python -m backend.nightly_eval --include-llm --runner tailoring -v
```

## Cost tracking (`aijobagent_run_traces`)

Every successful LLM call records a row in `aijobagent_run_traces` with
prompt tokens, completion tokens, and a USD cost computed against the
pricing map in `src/openai_service.py`. See
`docs/sql/supabase-run-traces.sql` for the schema. Apply the migration
in the Supabase SQL editor before deploying the new backend bits — the
runtime tolerates a missing table (best-effort writes, no exception
propagated) but the cron-side tier-margin analysis assumes the table
exists.

Pricing map and per-million-token costs are in `src/openai_service.py`
under `_MODEL_PRICING_USD_PER_MILLION`. Update both the prices in code
AND the README pricing reference when OpenAI changes a model's price.
