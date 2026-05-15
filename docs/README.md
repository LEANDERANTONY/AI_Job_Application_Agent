# Docs index

This is the docs-governance file for the AI Job Application Agent. It catalogs every tracked Markdown / reference doc in the repo, says who each one is for and when to update it, and records the criteria for keeping a file tracked vs. local-only. Treat it as a living index — when a doc is added, refactored, or pruned, update the relevant row here **in the same commit**.

---

## Tracked docs

### Project-level

| File | Audience | Update trigger |
|---|---|---|
| [`README.md`](../README.md) | First-time visitor to the GitHub repo | Headline capability ships (payments going live, a new pipeline stage), tech-stack additions, ADR/test counts drift, or links go stale |
| [`DEVLOG.md`](../DEVLOG.md) | Future-me + external reviewers reading the chronology | Add a `## Day N` entry per substantial commit series (cadence ~per PR-cluster during heavy iteration). Latest entry at the bottom. Historical entries are never rewritten |

### Architecture + how-it-works

| File | Audience | Update trigger |
|---|---|---|
| [`docs/architecture.md`](architecture.md) | New contributor or external reviewer reading the full runtime | Runtime-shape change (new module, new persisted table, new observability surface, retired component) |
| [`docs/operations.md`](operations.md) | Operator running / troubleshooting the VPS + Supabase + Vercel stack | Scheduled-job changes, observability env-var changes, a new operational gotcha that bit hard enough to need a runbook entry |
| [`docs/lemon-squeezy.md`](lemon-squeezy.md) | Operator wiring Lemon Squeezy for the first time | LS event-mapping changes, new variant ID / pricing tier, webhook URL or secret rotation |
| [`prompts/README.md`](../prompts/README.md) | Anyone editing an LLM prompt | Registry schema changes, a new prompt version (`v2.json`) lands, a builder is added or migrated |
| [`frontend/README.md`](../frontend/README.md) | First-time visitor to the `frontend/` package | Build / dev / lint commands change, package layout reorganizes |

### Architecture Decision Records

| File | Audience | Update trigger |
|---|---|---|
| [`docs/adr/ADR-NNN-*.md`](adr/) | Anyone wondering "why was this decision made" | **NEVER edit an accepted ADR's Decision section** — they're historic by design. If the decision changes, write a new ADR that supersedes it and add a status note to the old one rather than rewriting it |
| [`docs/adr/README.md`](adr/README.md) | ADR index page | Update **every time** a new ADR lands — add it to the right thematic cluster (Core / Tiering+Payments / Observability+Compliance / Maintenance) and refresh the "Current state note" if the decision changes the production picture |

### Evaluation methodology

| File | Audience | Update trigger |
|---|---|---|
| [`tests/quality/LATENCY-RESULTS.md`](../tests/quality/LATENCY-RESULTS.md) | Reader comparing latency before/after a perf change | **Snapshot artifact** — when a new latency baseline is captured, append a new dated section rather than overwriting the original baseline |

### Schema migrations (informational)

The `docs/sql/*.sql` files are reference copies of the Supabase migrations applied to production. They're tracked so a fresh-DB redeploy can rebuild the schema without paging through Supabase Studio history.

| File | What it sets up |
|---|---|
| `docs/sql/supabase-bootstrap.sql` | Core schema: `app_users`, `usage_events`, `saved_workspaces`, `saved_jobs` + RLS |
| `docs/sql/supabase-saved-jobs.sql` | `saved_jobs` table + RLS + TTL columns |
| `docs/sql/supabase-resume-builder.sql` | `resume_builder_sessions` + 7-day-TTL `cleanup-expired-resume-builder-sessions` pg_cron job |
| `docs/sql/supabase-quota-counters.sql` | `aijobagent_quota_counters` + atomic `increment_aijobagent_counter` RPC + tier matrix |
| `docs/sql/supabase-subscriptions.sql` | `aijobagent_subscriptions` table for the Lemon Squeezy integration |
| `docs/sql/supabase-run-traces.sql` | `aijobagent_run_traces` cost-attribution table (prompt/completion tokens + USD cost) |
| `docs/sql/supabase-feedback.sql` | `aijobagent_feedback` artifact thumbs-up/down table + RLS |
| `docs/sql/job_cache_cron_setup.sql` | **Template, not source of truth.** The `cached_jobs` refresh pg_cron schedule. Defaults to `*/30`; production runs `0 */4`. `SELECT jobname, schedule FROM cron.job;` is authoritative |

Update trigger: only when a new migration lands. Old `.sql` files are append-only.

---

## Untracked files (local-only, gitignored)

These exist on the developer machine but never on the remote. They carry working-context value but don't belong in the public repo.

| File | Why local |
|---|---|
| `AGENT.md` (repo root) | Working briefing for new chat agents — codebase layout, infra topology, Supabase inventory, observability wiring, scheduled-job list, the painful-things runbook. Carries VPS hostnames + Supabase project IDs that are working-briefing material, not a public README artifact. Rebuild from commit history if lost |
| `improvements.md`, `deployment-plan.md`, `docs/project_strategy.md` | Personal planning scratchpads — draft plans + exploratory notes, not durable artifacts |
| `VISUAL_LOOP_MVP.md` | Local design/planning notes |
| `design_system/` | Internal design specs (landing + workspace UI specs, inspiration). Substantive but not part of the public docs surface |
| `.env`, `openai_key.txt`, `*.pem`, `deploy/vps/.env` | Secrets — never tracked, `.env.example` is the tracked template |

---

## Pruning criteria — when to delete a tracked doc

A tracked doc is a candidate for removal when **any one** is true:

1. **Superseded by another tracked doc.** Two docs on the same topic create two sources of truth that drift. Pick the canonical one, fold in the useful parts, delete the redundant file.
2. **It documented a recipe that's now fully shipped + tested.** Migration recipes and wiring instructions have a fixed lifespan — once done and green, the ADR + the code are the durable record.
3. **Its own preamble says it's not for public consumption.** Either commit to publishing it or move it to local-only.
4. **The context it captured is no longer accurate.** A stale architecture doc is worse than no doc because a reader trusts it. Prefer rewriting as a new doc + deleting the stale one over incremental edits that leave half-truths.

Before deleting, check whether the doc is referenced elsewhere (`grep -r "filename" docs/ README.md DEVLOG.md`) and update or remove the references in the same commit.

---

## Local-only criteria — when a doc shouldn't be tracked

Keep a new doc untracked (and add it to `.gitignore` in the same commit) when **any one** is true:

1. **It contains operational secrets, hostnames, or infra IDs** that don't belong in a public repo. `.env` is the canonical example; `AGENT.md` is the borderline case (VPS hostnames + Supabase project IDs — working details, not credentials).
2. **Its purpose is a working briefing, not a durable artifact.** A "what-the-next-agent-should-know" file is edited freely without versioning anxiety — that's the opposite of an ADR.
3. **It's a personal scratchpad** (TODO lists, draft plans). If a piece becomes durable, promote it into a tracked doc later.
4. **It's auto-generated** on every run.

---

## Adding a new tracked doc

1. **Pick the right home.** Decision records → `docs/adr/`. Operational guidance → `docs/`. Code-package docs (like `frontend/README.md`) stay next to their code.
2. **Add a row to the tables above.** The audience + update-trigger fields are load-bearing — without them, a future contributor doesn't know whether the doc is edited per-PR or only on a specific event.
3. **Cross-link from the canonical readers** (`README.md`, `architecture.md`, `operations.md`) if relevant. Orphan docs rot.
4. **Commit the new doc + this index update + any cross-links in the same commit.** Don't let docs governance lag behind the docs.

---

## Maintenance cadence

This file is updated on the same commit that adds a new doc, demotes a tracked file to local-only or deletes it, or materially changes the audience / update-trigger of an existing doc. Plain Markdown edit + commit, no automation — the point is to be cheap enough to maintain that it stays accurate.
