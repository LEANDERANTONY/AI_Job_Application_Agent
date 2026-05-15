# Architecture Overview

This document describes the current runtime architecture of the AI Job Application Agent.

## System Goal

The app helps a candidate:

- sign in with Google
- upload and parse a resume
- search technical jobs or import a supported job link
- upload or paste a job description
- review a structured JD summary
- run a grounded agentic workflow
- review a tailored resume and cover letter
- ask grounded follow-up questions in the workspace assistant
- export DOCX or PDF versions of the generated documents (the earlier Markdown export path was removed in 2026-05; see [ADR-015](adr/ADR-015-docx-first-artifact-export-with-theme-palette.md))

## Runtime Shape

The product now runs as a split web application:

- `frontend/` is the Next.js workspace deployed on Vercel
- `backend/` is the FastAPI API deployed on the VPS
- `src/` contains the shared Python workflow, builders, orchestration, auth helpers, and persistence logic
- `backend/vps/` contains the Docker Compose + Caddy deployment bundle for the backend stack

This is no longer a Streamlit runtime. The old Streamlit shell and related deployment files were removed from the active codebase.

## High-Level Flow

1. The user opens the Next.js workspace.
2. The user signs in with Google through Supabase-backed auth endpoints.
3. The user uploads a resume.
4. The backend parses the resume and builds a normalized candidate profile.
5. The user can search configured Greenhouse, Lever, Ashby, and Workday sources via the Supabase-cached job index (or paste a supported job URL, or continue manually with JD text).
6. The app builds a structured JD summary for review.
7. The user explicitly triggers the agentic workflow.
8. The orchestrator runs `tailoring`, `review`, `resume_generation`, and `cover_letter`. The earlier `fit` and `strategy` stages were removed from the live workflow; the deterministic fit-scoring service in `src/services/fit_service.py` is still available as a building block for `tailoring` but is no longer a visible workflow stage.
9. Builders assemble the tailored resume and cover letter.
10. The workspace assistant answers grounded questions from the current workspace state.
11. Export helpers produce DOCX and PDF files for the current document; both formats share the same theme palette (`classic_ats`, `professional_neutral`).
12. For authenticated users, the latest workspace snapshot and saved jobs are persisted in Supabase.

## Main Modules

### `frontend/`

Owns the user-facing workspace:

- account state and sign-in flow (signed-out users hitting `/workspace` get redirected to the landing page; cross-origin host strip mirrors the existing app-subdomain middleware)
- resume intake (Upload mode + Build with assistant conversational chat; see [ADR-016](adr/ADR-016-conversational-llm-resume-builder.md))
- job search and saved jobs
- JD review
- workflow progress UI
- document preview and export actions
- assistant chat — not gated; answers product-help questions from the first visit and grounded package questions once an analysis has run; see [ADR-017](adr/ADR-017-workspace-assistant-state-aware-context.md)

Step rail navigation: Resume / Job Search / Job Detail are independently accessible — a user can paste a JD without a resume, or browse listings without uploading anything. Only Analysis is gated (it requires both a parsed resume and a parsed JD); the rail-level lock is a hint, and the AnalysisRunner page surfaces what's missing when the user lands there early. See [ADR-019](adr/ADR-019-independent-step-navigation.md).

### `backend/`

Owns the FastAPI API surface:

- `backend/app.py` bootstraps the API
- `backend/observability.py` is the single observability bootstrap, imported before `FastAPI()` is constructed so the Sentry ASGI middleware wraps the app at startup; no-op when the Sentry DSN / PostHog key are empty; see the Observability And Telemetry Layer section and [ADR-024](adr/ADR-024-observability-stack-sentry-and-posthog.md)
- `backend/nightly_eval.py` is the manual-only LLM quality-regression CLI; exists + tested but deliberately not on a production cron at pre-revenue stage; see [ADR-026](adr/ADR-026-manual-only-nightly-eval-at-pre-revenue-stage.md)
- `backend/routers/health.py` exposes deployment smoke signals (also the Sentry Uptime monitor target)
- `backend/routers/jobs.py` exposes the cache-backed search, the `?live=true` escape-hatch fan-out, direct job-resolution endpoints, and the bearer-protected `POST /admin/refresh-cache` endpoint that drives the cached-jobs refresh worker
- `backend/routers/auth.py` owns auth/session endpoints
- `backend/routers/workspace.py` owns resume, JD, workflow, assistant (both non-streaming and SSE), persistence, preview, export, resume-builder chat, resume-builder export, voice transcription (`/workspace/transcribe`), and artifact feedback (`/workspace/feedback`) endpoints
- `backend/routers/billing.py` owns the HMAC-verified `POST /webhooks/lemonsqueezy` subscription-event endpoint + the customer-portal redirect; the signature-verification + event-routing logic lives in `backend/webhooks/lemonsqueezy.py`
- `backend/prompt_registry.py` loads every LLM prompt from `prompts/<name>/<version>.json` — all 11 builders migrated off Python f-string concats; see [ADR-018](adr/ADR-018-three-layer-llm-retry-and-per-agent-fallback-isolation.md) family + the prompt-registry DEVLOG entries
- `backend/services/job_cache_service.py` runs the per-source refresh + smart-cleanup worker invoked by the admin endpoint

### `src/services/`

Owns deterministic business logic:

- candidate-profile construction from resume input (`profile_service.py`)
- JD normalization (`job_service.py`) plus a `jd_summary_service.py` view layer
- LLM-hybrid resume + JD parsers (`resume_llm_parser_service.py`, `jd_llm_parser_service.py`) — pure-LLM source of truth with a deterministic fallback
- fit scoring (`fit_service.py`) — still used by tailoring, no longer a visible workflow stage
- first-pass tailoring guidance (`tailoring_service.py`)

These services are transport-agnostic and do not depend on Next.js or FastAPI.

### `src/agents/`

Owns the supervised orchestration layer.

The active orchestrator path runs:

- tailoring
- review
- resume generation
- cover letter

The earlier `fit` and `strategy` stages are no longer part of the live workflow. The `TailoringAgent` consumes the structured `FitAnalysis` produced by `src/services/fit_service.py` directly — no FitAgent narration step. Each agent has a Tier-2/Tier-3 quality runner under `tests/quality/` that scores it on fixture (resume, JD) pairs.

**Per-agent retry + fallback isolation.** Each agent step inside the orchestrator gets its own retry budget and its own fallback path. If an agent's LLM call raises `AgentExecutionError` (after the OpenAI service's own SDK + app-level retries exhaust), the orchestrator retries the agent's full `.run(...)` once with a 400 ms delay. If the retry also fails, only THAT agent's deterministic fallback runs — downstream agents continue trying the LLM path. A single bad packet during the Forge agent no longer cascades to "downgrade the whole pipeline to deterministic." The whole-pipeline deterministic fallback remains as a safety net for the unusual case where a per-agent deterministic path itself errors out. If every agent ended up falling back per-agent (zero LLM successes), `result.mode` is honestly downgraded to `deterministic_fallback`. See [ADR-018](adr/ADR-018-three-layer-llm-retry-and-per-agent-fallback-isolation.md).

### `src/prompts.py`

Owns grounded prompt builders for the specialist agents and assistant.

### `src/openai_service.py`

Owns the thin OpenAI wrapper used by the workflow and assistant layers.

Responsibilities include:

- task-aware model routing
- Responses API calls (JSON-contract path via `run_json_prompt`, streaming prose path via `run_text_stream`)
- GPT-5 reasoning-effort routing
- usage accounting metadata
- optional persisted usage-event callbacks
- daily-quota preflight checks
- output-budget retry handling (when responses are truncated due to insufficient `max_output_tokens`)
- application-level retry on top of the OpenAI Python SDK's own retries (`max_retries=2`) — adds one extra attempt on the narrow allow-list `APIConnectionError` / `APITimeoutError` / `InternalServerError`. Every `responses.create` in the codebase routes through `_create_response_with_app_retry`, so the resume parser, JD parser, JD summary, all four supervised-workflow agents, and the assistant chat all inherit the retry layer for free. See [ADR-018](adr/ADR-018-three-layer-llm-retry-and-per-agent-fallback-isolation.md).

### `src/assistant_service.py`

Owns the single in-app assistant behavior. The chat is **not gated** on having run an analysis — it answers product-help questions ("how do I use this?", "what's step 03 for?") from the very first visit and grounded package questions ("summarize my fit") once an analysis has run. See [ADR-017](adr/ADR-017-workspace-assistant-state-aware-context.md).

Responsibilities include:

- routing between product-help questions and grounded package questions
- compact workspace-context assembly, including a `workspace_state` projection (`current_step`, `has_resume`, `resume_summary`, `has_jd`, `jd_summary`, `has_analysis`, `saved_jobs_count`, `last_search_query`) sent on every query so the LLM can answer state-aware questions before any analysis exists
- deterministic fallback behavior when assisted execution is unavailable

### Builders and Exporters

- `src/resume_builder.py`: deterministic tailored-resume assembly
- `src/cover_letter_builder.py`: deterministic grounded cover-letter assembly
- `src/exporters.py`: DOCX/PDF export helpers (`export_docx_bytes`, `export_pdf_bytes`) plus HTML preview generation, sharing a theme palette across formats; see [ADR-015](adr/ADR-015-docx-first-artifact-export-with-theme-palette.md)
- `src/job_sources/`: per-provider adapter implementations (Greenhouse, Lever, Ashby, Workday) feeding the cached-jobs refresh worker

The user-facing workspace is now centered on two visible outputs:

- tailored resume
- cover letter

Both ship in two themes (`classic_ats`, `professional_neutral`) and both formats (DOCX, PDF). The earlier Markdown export path was removed in 2026-05 alongside the DOCX rollout. The earlier internal report builder was removed when the FitAgent + bundle endpoint were retired.

### Auth and Persistence Modules

- `src/auth_service.py`: Supabase Auth wrapper for Google OAuth
- `src/user_store.py`: syncs lightweight `app_users` records
- `src/usage_store.py`: persists authenticated assisted usage events
- `src/quota_service.py`: computes daily quota state from persisted usage
- `src/saved_workspace_store.py`: persists and loads the latest reloadable workspace snapshot
- `src/saved_jobs_store.py`: persists and loads shortlisted jobs
- `src/cached_jobs_store.py`: service-role-backed access layer for the global `cached_jobs` index — bulk upsert, smart cleanup, ranked search via Postgres RPC; see [ADR-013](adr/ADR-013-cached-jobs-cache-layer-with-scheduled-refresh.md) and [ADR-014](adr/ADR-014-postgres-rpc-for-ranked-search.md)
- `src/resume_builder_store.py`: persists and loads conversational resume-builder draft sessions (`resume_builder_sessions` table) with the 7-day TTL + active-user refresh policy; see [ADR-016](adr/ADR-016-conversational-llm-resume-builder.md)

### `src/config.py`

Owns environment-backed configuration for:

- model routing
- reasoning routing
- quota defaults
- auth and Supabase settings
- saved-workspace retention settings
- frontend/backend integration settings

### `src/schemas.py`

Owns shared typed models for:

- resumes
- candidate profiles
- work experience
- education
- job descriptions
- fit analyses
- tailoring drafts
- tailored resume artifacts
- cover letter artifacts
- internal reports
- agent outputs
- orchestrated workflow results
- auth and persistence records

## Persistence Model

The runtime uses a split state model:

- browser state for the current workspace session
- Supabase Postgres for authenticated persistence and the global cached-jobs index

Per-user persistent state:

- `app_users`
- `usage_events`
- `saved_workspaces`
- `saved_jobs`
- `resume_builder_sessions`

Global (non-user-scoped) state:

- `cached_jobs` — the indexed set of upstream postings refreshed every 4 hours (six times a day) by the backend's `refresh_cached_jobs` worker; see [ADR-013](adr/ADR-013-cached-jobs-cache-layer-with-scheduled-refresh.md)

Each `saved_workspaces` row stores one latest snapshot per user, including enough data to restore the current resume/JD/workflow state.

Each `saved_jobs` row stores one shortlisted posting per user and normalized job id, including:

- source/provider identity
- title, company, location, and employment type
- source URL
- normalized summary and description text
- provider metadata
- saved and updated timestamps

Each `resume_builder_sessions` row stores one in-progress conversational resume-builder draft per user with a 7-day TTL refreshed on every save. A `pg_cron` job (`cleanup-expired-resume-builder-sessions`) hard-deletes expired rows every 5 min and RLS hides expired rows from per-user queries; see [ADR-016](adr/ADR-016-conversational-llm-resume-builder.md).

Each `cached_jobs` row holds one upstream posting keyed on `(source, job_id)`. The table has GENERATED STORED columns (`work_mode`, `employment_type_norm`) backing the dropdown filters and `removed_at` tombstones for upstream-closed jobs the user has bookmarked. A `pg_cron` + `pg_net` schedule (`cached_jobs_refresh_4h`) POSTs to `/admin/refresh-cache` every 4 hours, six times a day (see `docs/sql/job_cache_cron_setup.sql` for the template — production runs `0 */4 * * *`); ranked search reads from this table via the `search_cached_jobs_ranked` RPC, per [ADR-014](adr/ADR-014-postgres-rpc-for-ranked-search.md).

`aijobagent_run_traces` is an append-only cost-attribution table — one row per successful LLM call (`user_id`, `model`, `task`, `prompt_tokens`, `completion_tokens`, `cost_usd`, `created_at`). Writes are best-effort: a missing table or a write error never propagates to the user-facing path. It is the canonical answer to "what is OpenAI spend doing", separate from the Sentry/PostHog telemetry surface.

`aijobagent_feedback` holds one row per artifact thumbs-up/down (`user_id`, `workspace_id`, `artifact_kind`, `rating`, `comment`, `created_at`), RLS-scoped to the owning user; admin reads go through the service role.

## Observability And Telemetry Layer

Wired Day 46. The compliance posture is enforced at the SDK-init level, not as legalese on a privacy page — see [ADR-024](adr/ADR-024-observability-stack-sentry-and-posthog.md) and [ADR-025](adr/ADR-025-eu-cookie-consent-banner-and-gdpr-analytics-gating.md).

Two vendors, one bootstrap path:

- **Sentry** — error tracking, performance traces, AI Agents Monitoring (`OpenAIIntegration(include_prompts=False)` — token/model/latency spans without prompt-body PII), Logs, and session replay (errors-only). `backend/observability.py` is the only place the SDK is touched on the backend; it's imported before `FastAPI()` is constructed so the ASGI middleware wraps the app at startup. The `before_send` hook drops intentional `HTTPException` 4xx flow-control + the "not configured / temporarily unavailable" 5xx guards so the issue feed stays focused on genuine bugs. A `_running_under_pytest()` check skips Sentry entirely during the test suite. Frontend Sentry is wired via `instrumentation-client.ts` / `instrumentation.ts` / `sentry.server.config.ts` / `sentry.edge.config.ts`; `next.config.ts` uploads source maps through `withSentryConfig`.
- **PostHog** — product analytics, session replay, identify/group cohorts. The free Developer plan caps at one project per org, so the project is shared with the developer's other product; every event carries a `product: "jobagent"` super-property (frontend `posthog.register`, backend `capture_event` merge) so dashboards slice cleanly with `where properties.product = 'jobagent'`. Exception capture is off — Sentry is the source of truth for errors.

Both clients are no-ops when their DSN / key is empty, so dev, CI, and the test suite run without observability wiring or network calls.

### Consent gating

The single source of truth is `localStorage["jobagent-cookie-consent"]`, set by the custom in-house cookie banner (`frontend/src/components/cookie-consent.tsx`), three states: `pending` / `accepted` / `declined`. The split:

- **Always-on** (legitimate interest, GDPR Art. 6(1)(f) — crash reporting is operationally necessary): Sentry error tracking + traces + Feedback widget. Load regardless of banner state.
- **Consent-gated** (explicit opt-in required, ePrivacy Art. 5(3)): PostHog product analytics + PostHog session replay + Sentry Session Replay. Load only when consent `=== "accepted"`.

A `jobagent-cookie-consent-change` custom event re-evaluates the gated integrations on flip without a page reload (`Sentry.addIntegration(...)` hot-adds Replay; PostHog `opt_in_capturing()` / `opt_out_capturing()`). The banner is in-bundle (no third-party JS loads before consent) and scoped under the `.ja-cookie-banner` CSS class.

### Uptime

A Sentry Uptime monitor pings `https://api.job-application-copilot.xyz/health` every 5 minutes from the EU region. Configured in the Sentry dashboard rather than in code — a fresh-project rebuild must recreate it manually.

## Testing Model

The repo includes focused tests for:

- resume parsing
- JD parsing (deterministic + LLM-hybrid)
- profile normalization
- job normalization
- tailoring guidance
- orchestrator behavior
- resume and cover-letter building
- DOCX + PDF export formatting
- auth and quota behavior
- saved-workspace persistence
- saved-job persistence
- cached-jobs store + RPC arg shape
- cached-jobs refresh worker (per-source isolation, cleanup gating, status reporting)
- per-provider job source adapters (Greenhouse, Lever, Ashby, Workday)
- conversational resume-builder turn handling + structuring pass
- backend workspace routes
- assistant SSE streaming endpoint
- OpenAI application-level retry contract (`tests/test_openai_app_retry.py`): retries on the narrow allow-list `APIConnectionError` / `APITimeoutError` / `InternalServerError`, does NOT retry on 4xx / auth / persistent rate-limit, returns success after retry, raises on double-failure
- per-agent orchestrator behavior (`tests/test_orchestrator.py`): per-agent retry recovers a flaky agent, per-agent fallback isolates a single failing agent (downstream agents still use LLM), `result.mode` reconciles to `deterministic_fallback` when no agent succeeded with LLM
- tier enforcement (`tests/backend/test_tiers.py`, `test_quota.py`, `test_workspace_quota_enforcement.py`, and siblings): atomic check-and-increment under thread races, refund-on-failure, lifetime-vs-monthly period switching, P0001 → 429 translation, Business unbounded-retention skip
- Lemon Squeezy webhook (`tests/backend/test_lemonsqueezy_webhook.py`): HMAC signature verification, event routing, unknown-variant silent-ack
- prompt registry byte-identity (`tests/test_prompts.py`): every one of the 11 migrated JSON templates is asserted bit-exact against the original Python concat
- voice transcription + artifact feedback backend routes (`tests/backend/test_transcribe.py`, `test_feedback.py`): multipart handling, 60s overrun rejection, RLS-scoped feedback writes

The `_running_under_pytest()` guard means Sentry never initializes during the test run, so the observability wiring adds zero test-suite coupling beyond a small leaky-detail-allowlist line-offset in `tests/test_error_messages.py`.

Tier-2 / Tier-3 quality runners under `tests/quality/` evaluate LLM-driven components (resume parser, JD parser, renderer fidelity, skill canonicalization, tailoring, review, resume generation, cover letter, resume builder, assistant, end-to-end orchestrator) on fixture sets with weighted scorecards and a `--include-llm` cost gate. `backend/nightly_eval.py` wraps these into a single unattended batch with regression-threshold checking — manual-only at pre-revenue stage, see [ADR-026](adr/ADR-026-manual-only-nightly-eval-at-pre-revenue-stage.md).

## Current Constraints

- Long AI-assisted runs still execute as one request/response cycle today; they are not yet background jobs.
- The product stores one latest saved workspace snapshot per user; it does not expose a multi-entry history browser.
- Large binary artifacts are regenerated on demand instead of being stored in object storage.
- The internal report builder still exists in Python, but the visible workspace now centers on resume and cover letter only.

## Next Architecture Step

The next meaningful expansion is product hardening on the current stack:

- background execution for long-running workflow jobs
- tighter hosted reliability around retries and timeouts
- continued UI simplification around review and export
- broader hosted QA across Vercel, VPS, Supabase, and Cloudflare
