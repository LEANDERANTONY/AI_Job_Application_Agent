# Deployment

The day-2 operational runbook: scheduled-job inventory, observability
env vars, manual runbook entries, and the operational gotchas that bit
hard enough to need writing down. Anything that doesn't fit cleanly
into `architecture.md` or an ADR lives here.

## Scheduled jobs — the complete inventory

This is the authoritative list of everything that runs on a schedule
in production. **No scheduled job runs a chat / completion model.**
Audited 2026-05-22; updated 2026-06-23 (lean-mode downgrade + the new
`purge-cron-run-history` job).

| Job | Where | Schedule | What it does | LLM cost |
| --- | --- | --- | --- | --- |
| `cached_jobs_refresh` | Supabase `pg_cron` + `pg_net` | every 4h (`0 */4 * * *`, six runs/day) | POSTs `/api/admin/refresh-cache` so the backend re-polls the Greenhouse/Lever/Ashby/Workday boards into `cached_jobs` | **\$0** now — job-board APIs are free, and **embed-on-write is OFF since the 2026-06-23 lean-mode downgrade** (`JOB_SEARCH_HYBRID_ENABLED=false`, embedding column dropped). When the project is back on Pro + hybrid is re-enabled, this row embeds newly-cached jobs with `text-embedding-3-small` (a few ¢/day). No chat-model call either way |
| `cleanup-expired-resume-builder-sessions` | Supabase `pg_cron` | every 5 min (`*/5 * * * *`) | Hard-deletes `resume_builder_sessions` rows past their 7-day TTL | **\$0** — plain SQL `DELETE`, no LLM |
| `purge-cron-run-history` | Supabase `pg_cron` | daily (`30 3 * * *`) | `DELETE FROM cron.job_run_details WHERE end_time < now() - interval '7 days'`. Bounds pg_cron's own run-history table, which grows unboundedly (the 5-min resume-builder cleanup alone adds ~288 rows/day). Added 2026-06-23 after it had reached ~30k stale rows | **\$0** — plain SQL `DELETE`, no LLM |
| `backend.maintenance` (saved-workspace retention sweep) | VPS host crontab — **verify against prod** | daily (`0 3 * * *` assumed) | Runs `python -m backend.maintenance` → `sweep_expired_workspaces`: deletes saved workspaces past their per-tier retention (Free > 7d, Pro > 30d). Now check-ins to the `saved-workspaces-retention` Sentry cron monitor (M22) | **\$0** — plain `DELETE`, no LLM |
| `backend.nightly_eval` | VPS host crontab | **NOT INSTALLED** | Would run the LLM quality eval; deliberately not scheduled | would be ~\$0.25/run if enabled |

Two things worth internalizing:

1. **The only scheduled job that runs a chat / completion model is `nightly_eval`, and it is intentionally not on the cron.** See the next section + [ADR-026](adr/ADR-026-manual-only-nightly-eval-at-pre-revenue-stage.md). The cache refresh's embed-on-write spends a little on the cheap embeddings model; a *chat-model* bill with no user traffic is NOT a rogue cron — check for a stuck retry loop or a manual run left running instead.
2. **The cache-refresh schedule drifted from its own template.** `docs/sql/job_cache_cron_setup.sql` still defaults to `*/30 * * * *` (every 30 min — the original aggressive cadence). Production was dialed back to `0 */4 * * *` (every 4h) to cut Supabase `pg_net` egress + backend churn once the job catalog stopped changing every few minutes. The SQL file is a template, not the source of truth; `SELECT jobname, schedule FROM cron.job;` in the Supabase SQL editor is. If you re-run the template verbatim it will re-pin the schedule to 30 min — edit the cron expression before pasting.
3. **The saved-workspace retention sweeper was missing from this inventory (M22)** and had no cron monitor. It is now listed above and wrapped in the `saved-workspaces-retention` Sentry cron monitor. **If that monitor never receives a check-in after deploy, the sweeper is NOT actually scheduled** and Free-tier retention isn't being enforced — wire it into the host crontab, e.g. `0 3 * * * cd /app && python -m backend.maintenance`, and confirm the schedule matches the `value` in `SAVED_WORKSPACES_RETENTION_MONITOR_CONFIG`.

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

> ⚠️ **Verify this target (flagged 2026-07-22).** Live probing shows bare
> `/health` returns **404** — the real health route is **`/api/health`**,
> which returns `{"status":"ok", ...}` plus per-provider board counts.
> Either the monitor already points at `/api/health` and the line above is
> stale, or it is pinging the 404 and only passes because it treats any
> HTTP response as "up" — which would make the uptime signal meaningless.
> Confirm in the Sentry dashboard and fix whichever is wrong. The
> smoke-test command is:
> ```bash
> curl -fsS https://api.job-application-copilot.xyz/api/health
> ```

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

## Hybrid-search lean/full switch (fit the Supabase free tier on demand)

Job search runs in one of two modes, toggled without a code change. The
**full** mode is the current production state: Tier 2 hybrid search
(lexical + pgvector semantic, fused by RRF). The **lean** mode is the
pre-Tier-2 state: Tier 1 lexical-only (synonym-expanded full-text). The
ONLY reason to go lean is **storage**: the `embedding vector(1536)`
column + its HNSW index are the bulk of `cached_jobs`'s footprint (the
~20k rows of job *text* are cheap — the per-row 1536-dim vectors and the
HNSW graph are what push the database past the Supabase **free-tier 500
MB** cap). Going lean reclaims that space so the project fits the free
plan; going full restores semantic search when a paid plan is in place.

**This is NOT a row-count change.** Lean mode hosts the *same* ~20k
jobs — it just drops the embeddings. Lexical search (exact-keyword +
synonym/abbreviation expansion) keeps working; what you lose is
concept-level matching (e.g. "ML engineer" ↔ "machine learning
specialist" with no shared keyword).

**The pieces (most already exist):**
- Env flag `JOB_SEARCH_HYBRID_ENABLED` — gates BOTH the search path
  (`search_cached_jobs_hybrid` vs `search_cached_jobs_ranked`) and the
  embed-on-write path in the 4-hourly refresh. Off = lexical-only +
  zero embedding spend. The hybrid RPC also self-degrades to lexical on
  any error, so a stale flag can never 500 the search.
- `docs/sql/supabase-cached-jobs-lean-mode.sql` — the downgrade DDL
  (drop HNSW index → drop hybrid RPC → drop embedding column → VACUUM
  FULL). Idempotent.
- `docs/sql/supabase-cached-jobs-pgvector.sql` + `…-hybrid.sql` — the
  upgrade DDL (re-add column + HNSW, re-create hybrid RPC). Idempotent
  (`IF NOT EXISTS` / `CREATE OR REPLACE`).
- `scripts/backfill_job_embeddings.py` — re-embeds every row on the way
  back to full. Idempotent + resumable (`embedding IS NULL` only).
  ~20k rows ≈ ~200 embedding API calls ≈ a few cents, a few minutes.
- `docs/sql/supabase-cached-jobs-health.sql` — the daily healthcheck's
  stats RPC. **Mode-agnostic since 2026-07-21**: it probes for the
  `embedding` column and reports `null_embedding_count` as JSON null when
  lean, so it needs NO step in either direction. It did not used to be —
  see the warning below.

> ⚠️ **Dropping `embedding` breaks anything that references it.** The
> first lean-mode run (2026-06-23) dropped the column but missed
> `cached_jobs_health_stats`, whose plain-SQL body referenced it. Every
> daily healthcheck then 503'd with `column cj.embedding does not exist`
> for four weeks (Sentry JOBAGENT-BACKEND-7/-8, fixed DEVLOG Day 83).
> The health RPC is now probe-based and safe, but **before dropping the
> column, re-check for other referrers**:
> ```sql
> SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
> WHERE n.nspname = 'public' AND pg_get_functiondef(p.oid) ILIKE '%embedding%';
> ```

**FULL → LEAN (downgrade to the free tier):**
1. Set `JOB_SEARCH_HYBRID_ENABLED=false` in the VPS `.env`; redeploy api
   (`docker compose -p ai_job_application_agent up -d --force-recreate api`).
   Flip the flag FIRST so no request hits the hybrid RPC after its
   backing column is gone.
2. Apply statements 1–3 of `supabase-cached-jobs-lean-mode.sql` (drop
   index → drop RPC → drop column) via the Supabase SQL editor.
3. Run `VACUUM FULL public.cached_jobs;` as its OWN statement (can't run
   in a transaction; brief ACCESS EXCLUSIVE lock, ~seconds on ~20k rows
   — search is unavailable for that window). This is what actually
   returns the freed pages to the OS so `pg_database_size` drops.
4. Confirm: `SELECT pg_size_pretty(pg_database_size(current_database()));`
   is under the free-tier cap.
5. **Smoke the healthcheck** (the step whose absence cost four weeks of
   blind daily failures): `SELECT public.cached_jobs_health_stats(5);`
   must return a jsonb object — not an error. Then confirm no new
   `jobagent-backend` Sentry issue appears after the next 06:00 UTC
   healthcheck run.

**LEAN → FULL (upgrade after a paid plan is in place):**
1. Apply `supabase-cached-jobs-pgvector.sql` (re-adds `embedding` +
   HNSW; the `vector` extension was left enabled so this is one step).
2. Run `python -m scripts.backfill_job_embeddings` (or `docker exec
   ai-job-application-agent-api python -m scripts.backfill_job_embeddings`)
   to embed all rows. Resumable — re-run if interrupted.
3. Apply `supabase-cached-jobs-hybrid.sql` (re-creates the hybrid RPC
   the lean-mode drop removed).
4. Set `JOB_SEARCH_HYBRID_ENABLED=true`; redeploy api. Embed-on-write
   resumes for new rows from the next refresh.

**Safety net (DONE — PERFDB-4 resolved 2026-06-22):** the full
`cached_jobs` base-table DDL (the table, the `search_tsv` generated
tsvector, the GIN/trgm indexes, the `unique (source, job_id)`, the
`work_mode`/`employment_type_norm` generated columns + partial indexes,
the recency btree) is now captured verbatim from the prod catalog into
the tracked `docs/sql/supabase-cached-jobs-base.sql`, so "restore to
full" — or a full disaster-recovery rebuild — is reproducible and a
botched drop can't lose the exact index config. The lean-mode script
only ever drops the *semantic* add-ons (embedding column + HNSW); it
never touches the base table or the lexical indexes.

**CURRENT STATE (2026-06-23): on the FREE plan, LEAN MODE ACTIVE.** The
jobagent Supabase org was downgraded **Pro → free** to cut the ~$25/mo
pre-revenue, and lean mode was executed to fit the 500 MB cap. So job
search is **lexical-only right now** — the "full / hybrid" half below is
the *restore* path for if/when the project goes back to Pro, not the
live config.

**What happened (chronological, jobagent prod 2026-06-23):**
1. Live check found the DB at **470 MB** (climbing — a VACUUM the day
   before had dipped it to 381 MB but the 4-hourly refresh churn refilled
   it within a day; **a plain VACUUM is NOT a durable lever on this
   table** — it re-bloats to its ~485 MB natural high-water-mark in days).
2. Downgraded the org to free.
3. Executed lean mode: `JOB_SEARCH_HYBRID_ENABLED=false` + redeployed api
   (embed-on-write off, search → lexical) → dropped the HNSW index +
   hybrid RPC + `embedding` column (migration
   `cached_jobs_lean_mode_drop_semantic_layer`) → `VACUUM FULL`.
4. Result: **470 → 171 MB** (cached_jobs 451 → 151 MB), all 14,083 jobs
   intact, lexical `search_cached_jobs_ranked` serving live results.
   **330 MB under the cap.**

**Why lean mode holds where VACUUM didn't:** with embed-on-write off and
no HNSW index, the refresh now only touches cheap text columns — there's
no per-row 1536-dim vector churn and no HNSW graph to bloat. The DB sits
at ~150-200 MB and *stays* there. That is the whole point of lean vs a
VACUUM (which the churn undoes in days).

Also corrected: the prior version of this runbook claimed the churn
re-accumulates "~30-60 MB/month" and that a periodic VACUUM is a lever.
**Both were wrong** — re-bloat is ~90 MB/*day* back to the ~485 MB
high-water-mark, so VACUUM buys ~2 days, not months. Lean mode (or Pro)
is the only durable answer.

**Downgrade-at-launch caveat:** free tier (a) **auto-pauses a project
after 7 days of inactivity** — a launched-but-quiet app sleeps and the
next visitor hits a cold backend, and (b) has **no automated backups**
(Pro includes daily + 7-day PITR). For a launching product with real
user data, $25/mo Pro buys backups + always-on; downgrading is sound
*pre*-launch (no users, no risk) but penny-wise at launch. If you do
downgrade, set up a self-managed `pg_dump` backup routine FIRST, then
flip the plan in the dashboard (Organization → Billing → Change plan;
the management API/MCP cannot change billing — it's dashboard-only).

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
6. **Embed-on-write must only embed NEW jobs — never re-embed the
   corpus.** With `JOB_SEARCH_HYBRID_ENABLED=true`, the cache refresh
   embeds newly-cached postings into the `cached_jobs.embedding`
   pgvector column. An earlier cut re-embedded and re-wrote *every*
   job's vector on *every* refresh; the HNSW-index churn blew the
   chunk-upsert statement timeout (`57014`), failed the refresh in a
   loop, piled up dead tuples, and the resulting autovacuum saturated
   the database enough to time `/api/jobs/search` out at the gateway.
   The fix (DEVLOG Day 75) embeds only new / un-embedded rows. If job
   search starts timing out after a refresh, check the backend logs
   for `Failed to upsert chunk ... 57014` — that signature means
   embed-on-write is churning the index again.
