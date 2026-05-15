# Deployment

The day-2 operational runbook: scheduled-job inventory, observability
env vars, manual runbook entries, and the operational gotchas that bit
hard enough to need writing down. Anything that doesn't fit cleanly
into `architecture.md` or an ADR lives here.

## Scheduled jobs — the complete inventory

This is the authoritative list of everything that runs on a schedule
in production. **Nothing here spends OpenAI tokens.** Audited 2026-05-16.

| Job | Where | Schedule | What it does | LLM cost |
| --- | --- | --- | --- | --- |
| `cached_jobs_refresh` | Supabase `pg_cron` + `pg_net` | every 4h (`0 */4 * * *`, six runs/day) | POSTs `/api/admin/refresh-cache` so the backend re-polls the Greenhouse/Lever/Ashby/Workday boards into `cached_jobs` | **\$0** — upstream job-board APIs are free; no LLM in the refresh path |
| `cleanup-expired-resume-builder-sessions` | Supabase `pg_cron` | every 5 min (`*/5 * * * *`) | Hard-deletes `resume_builder_sessions` rows past their 7-day TTL | **\$0** — plain SQL `DELETE`, no LLM |
| `backend.nightly_eval` | VPS host crontab | **NOT INSTALLED** | Would run the LLM quality eval; deliberately not scheduled | would be ~\$0.25/run if enabled |

Two things worth internalizing:

1. **The only scheduled LLM-spending job that *could* exist is `nightly_eval`, and it is intentionally not on the cron.** See the next section + [ADR-026](adr/ADR-026-manual-only-nightly-eval-at-pre-revenue-stage.md). If you ever see OpenAI spend with no user traffic, it is NOT a rogue cron — check for a stuck retry loop or a manual run left running instead.
2. **The cache-refresh schedule drifted from its own template.** `docs/sql/job_cache_cron_setup.sql` still defaults to `*/30 * * * *` (every 30 min — the original aggressive cadence). Production was dialed back to `0 */4 * * *` (every 4h) to cut Supabase `pg_net` egress + backend churn once the job catalog stopped changing every few minutes. The SQL file is a template, not the source of truth; `SELECT jobname, schedule FROM cron.job;` in the Supabase SQL editor is. If you re-run the template verbatim it will re-pin the schedule to 30 min — edit the cron expression before pasting.

## Nightly quality eval (`backend.nightly_eval`) — manual-only

The nightly eval is the production-safety guard against silent model
drift. The quality runners under `tests/quality/` already exist for
human inspection; this CLI wraps them into a single batch job suitable
for an unattended cron and exits non-zero on any regression.

**It is intentionally not on the production cron at pre-revenue
stage.** The `--include-llm` run costs ~\$0.25 and a daily cadence is
~\$7.50/mo of recurring OpenAI spend for a safety net no paying user
benefits from yet. The full rationale + the one-step re-enable path is
[ADR-026](adr/ADR-026-manual-only-nightly-eval-at-pre-revenue-stage.md).
Run it **manually after any prompt change, model swap, or
agent-pipeline change** that could plausibly move quality.

### What it runs

- `resume_parser` — deterministic regex parser scorecard against the 15
  fixtures in `tests/quality/sample_resumes/`. Fast (<5s), \$0.
- `jd_parser` — deterministic JD parser scorecard against the 15
  fixtures in `tests/quality/sample_jds/`. Fast (<5s), \$0.
- `tailoring` — TailoringAgent against six (resume, JD) pairs. Runs in
  deterministic fallback by default; opt into LLM mode with
  `--include-llm` (~\$0.05 / run).
- `review` — ReviewAgent on the three clean scenarios. Adversarial
  scenarios stay in the dev workflow because they need an LLM to
  produce stable approval-rate signals.
- `orchestrator_e2e` — full Tailoring → Review → ResumeGen → CoverLetter
  chain. Requires `--include-llm` (~\$0.20 / run); skipped otherwise.

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

### Manual run pattern (the supported path today)

The deterministic-only spot-check costs \$0 and is safe to run anytime:

```
docker exec ai-job-application-agent-api \
  python -m backend.nightly_eval --runner resume_parser --runner jd_parser -v
```

The full LLM run (~\$0.25) after a meaningful change, comparing against
the last saved baseline and updating it forward:

```
docker exec ai-job-application-agent-api \
  python -m backend.nightly_eval --include-llm \
    --baseline /var/log/aijobagent-nightly-eval.last.json \
    --output  /var/log/aijobagent-nightly-eval.last.json
```

The first run without a baseline is treated as "no regression check"
and writes the baseline for next time.

### Re-enable path (when revenue justifies)

Single crontab edit. The recommended *re-enabled* cadence is **Mon+Thu
(`30 3 * * 1,4`)**, not daily — ~\$2/mo, 3-4 day detection window:

```
30 3 * * 1,4 docker exec ai-job-application-agent-api python -m backend.nightly_eval --include-llm --baseline /var/log/aijobagent-nightly-eval.last.json --output /var/log/aijobagent-nightly-eval.last.json >> /var/log/aijobagent-nightly-eval.log 2>&1
```

There is no Sentry Crons monitor for this CLI (it's pure-CLI, no
in-process heartbeat), so re-enabling needs no monitor recreation —
just the crontab line. See [ADR-026](adr/ADR-026-manual-only-nightly-eval-at-pre-revenue-stage.md).

### Alerting

The script logs `nightly_eval_runner_finished` per runner and a single
`nightly_eval_failed` / `nightly_eval_regressed` warning at the end when
something is off. When the cron is re-enabled, the natural alerting
target is Sentry Logs (the observability stack already ships
`enable_logs=True` — see below): tail for `"overall_pass": false`.

## Observability stack (Sentry + PostHog)

Wired Day 46 ([ADR-024](adr/ADR-024-observability-stack-sentry-and-posthog.md)
+ [ADR-025](adr/ADR-025-eu-cookie-consent-banner-and-gdpr-analytics-gating.md)).
Both clients are no-ops when their DSN / key is empty, so dev + CI run
without the secrets.

### Backend env vars (VPS `.env`, server-only)

| Var | Production value | Notes |
| --- | --- | --- |
| `SENTRY_DSN` | the `jobagent-backend` project DSN | empty → Sentry init skipped entirely |
| `SENTRY_TRACES_SAMPLE_RATE` | `0.1` | 10% trace sampling, free-tier-healthy |
| `SENTRY_PROFILES_SAMPLE_RATE` | `0.05` | 5% profiling |
| `SENTRY_SEND_DEFAULT_PII` | `false` | `OpenAIIntegration(include_prompts=False)` — no prompt bodies leave the box |
| `SENTRY_RELEASE` | unset | falls back to `BackendSettings.service_version` |
| `POSTHOG_API_KEY` | the shared project key | server-side `capture_event` merges `product: "jobagent"` |
| `POSTHOG_HOST` | `https://eu.i.posthog.com` | EU region |
| `AIJOBAGENT_ENVIRONMENT` | `production` | tags every Sentry + PostHog event so dashboards split prod from preview |

### Frontend env vars (Vercel, `NEXT_PUBLIC_*` inlined into the bundle)

| Var | Production value | Notes |
| --- | --- | --- |
| `SENTRY_AUTH_TOKEN` | a personal Sentry token | source-map upload via `withSentryConfig`. Org-scoped token, but `withSentryConfig` only uploads maps for the project it's configured for — it does NOT leak other projects' maps |
| `NEXT_PUBLIC_SENTRY_DSN` | the `jobagent-frontend` DSN | |
| `NEXT_PUBLIC_SENTRY_ENVIRONMENT` | `production` | |
| `NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE` | `0.1` | |
| `NEXT_PUBLIC_SENTRY_REPLAYS_ON_ERROR_SAMPLE_RATE` | `1.0` | 100% replay on errored sessions; ambient session sampling is `0` (PostHog handles ambient replay) |
| `NEXT_PUBLIC_POSTHOG_KEY` | the shared project key | |
| `NEXT_PUBLIC_POSTHOG_HOST` | `https://eu.i.posthog.com` | |

### What loads when (the GDPR split)

The cookie banner's `localStorage["jobagent-cookie-consent"]` is the
gate. **Always-on** regardless of consent (legitimate interest, GDPR
Art. 6(1)(f)): Sentry error tracking + traces + Feedback widget —
crash reporting is operationally necessary. **Consent-gated** (requires
`=== "accepted"`): PostHog product analytics + PostHog session replay +
Sentry Session Replay. A `jobagent-cookie-consent-change` event
hot-adds Sentry Replay via `Sentry.addIntegration(...)` on consent flip
without a page reload. Full rationale in
[ADR-025](adr/ADR-025-eu-cookie-consent-banner-and-gdpr-analytics-gating.md).

### Sentry-Vercel integration note

The Sentry-Vercel marketplace integration's env-var-upsert step
conflicts with a pre-existing `NEXT_PUBLIC_SENTRY_DSN` and fails to
save. Production uses the **manual fallback**: `SENTRY_AUTH_TOKEN` set
directly in Vercel env. Source-map upload behaves identically; the only
thing missing vs. the auto-integration is per-deploy release markers,
backfillable from `VERCEL_GIT_COMMIT_SHA` if ever needed.

### Uptime monitor

Sentry Uptime monitor pings `https://api.job-application-copilot.xyz/health`
every 5 min from the EU region. Configured in the Sentry dashboard
(not in code), so a fresh-project rebuild needs to recreate it manually.

## Cost tracking (`aijobagent_run_traces`)

Every successful LLM call records a row in `aijobagent_run_traces` with
prompt tokens, completion tokens, and a USD cost computed against the
pricing map in `src/openai_service.py`. See
`docs/sql/supabase-run-traces.sql` for the schema. Apply the migration
in the Supabase SQL editor before deploying the new backend bits — the
runtime tolerates a missing table (best-effort writes, no exception
propagated) but the cost-attribution queries assume the table exists.

Pricing map and per-million-token costs are in `src/openai_service.py`
under `_MODEL_PRICING_USD_PER_MILLION`. When OpenAI changes a model's
price, update **both** the prices in code AND the README pricing
reference in the same commit.

This table is also the answer to "is anything draining the OpenAI
budget?" — `SELECT date_trunc('day', created_at) d, sum(cost_usd)
FROM aijobagent_run_traces GROUP BY d ORDER BY d DESC;` shows daily
spend. A row with no corresponding user request is the signature of a
stuck retry or a forgotten manual eval, not a rogue cron (there is no
LLM-spending cron — see the inventory at the top).

## Operational gotchas (the runbook entries that cost real time)

1. **Docker Compose project-name is load-bearing.** The VPS runs
   multiple sibling products' containers. Compose derives the project
   name from the directory unless `-p` is passed. The Job Agent stack
   was originally brought up by the GitHub Actions deploy with an
   explicit project name; recreating containers manually **without the
   matching `-p` flag** creates a parallel set of empty named volumes
   and orphans the real data. Always confirm
   `docker compose -p <project> ps` shows the live containers before
   `up -d`. When in doubt, `docker volume ls` and check which volume
   set actually has the data before recreating anything.
2. **Caddy runtime config is wiped on restart unless it's in git.**
   Reverse-proxy blocks added live via the Caddy admin API (or hand-
   edited in the running container) vanish on the next `caddy reload` /
   container restart. The Job Agent's `api.job-application-copilot.xyz`
   block must live in the committed `backend/vps/Caddyfile`, not just
   in the running config. If the API domain 502s after an unrelated
   restart, this is the first thing to check.
3. **PostHog free tier is one project for both products.** Don't try
   to create a second PostHog project for "clean separation" — the
   Developer plan caps at one. Every event already carries
   `product: "jobagent"` (frontend `posthog.register`, backend
   `capture_event` merge). Dashboards MUST filter
   `where properties.product = 'jobagent'` or they'll show the sibling
   product's traffic mixed in.
4. **Sentry blocks the Chrome MCP on `*.sentry.io`.** Browser-driven
   automation against the Sentry dashboard fails silently. Use the
   Sentry REST API (or the Sentry MCP tools) for any dashboard
   mutation — monitor deletion, project settings, code mappings.
5. **`nightly_eval` is manual-only by design — don't "fix" the missing
   cron.** A future contributor noticing there's no nightly-eval cron
   line and "restoring" it would silently start ~\$7.50/mo of OpenAI
   spend. The absence is deliberate and documented in
   [ADR-026](adr/ADR-026-manual-only-nightly-eval-at-pre-revenue-stage.md);
   it stays off until revenue justifies it.
