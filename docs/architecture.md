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
- `deploy/vps/` contains the Docker Compose + Caddy deployment bundle for the backend stack

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

- account state and sign-in flow
- resume intake
- job search and saved jobs
- JD review
- workflow progress UI
- document preview and export actions
- assistant chat

### `backend/`

Owns the FastAPI API surface:

- `backend/app.py` bootstraps the API
- `backend/routers/health.py` exposes deployment smoke signals
- `backend/routers/jobs.py` exposes the cache-backed search, the `?live=true` escape-hatch fan-out, direct job-resolution endpoints, and the bearer-protected `POST /admin/refresh-cache` endpoint that drives the cached-jobs refresh worker
- `backend/routers/auth.py` owns auth/session endpoints
- `backend/routers/workspace.py` owns resume, JD, workflow, assistant (both non-streaming and SSE), persistence, preview, export, resume-builder chat, and resume-builder export endpoints
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

### `src/prompts.py`

Owns grounded prompt builders for the specialist agents and assistant.

### `src/openai_service.py`

Owns the thin OpenAI wrapper used by the workflow and assistant layers.

Responsibilities include:

- task-aware model routing
- Responses API calls
- GPT-5 reasoning-effort routing
- usage accounting metadata
- optional persisted usage-event callbacks
- daily-quota preflight checks
- incomplete-response retry handling

### `src/assistant_service.py`

Owns the single in-app assistant behavior.

Responsibilities include:

- routing between product-help questions and grounded package questions
- compact workspace-context assembly
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

- `cached_jobs` — the indexed set of upstream postings refreshed every ~30 min by the backend's `refresh_cached_jobs` worker; see [ADR-013](adr/ADR-013-cached-jobs-cache-layer-with-scheduled-refresh.md)

Each `saved_workspaces` row stores one latest snapshot per user, including enough data to restore the current resume/JD/workflow state.

Each `saved_jobs` row stores one shortlisted posting per user and normalized job id, including:

- source/provider identity
- title, company, location, and employment type
- source URL
- normalized summary and description text
- provider metadata
- saved and updated timestamps

Each `resume_builder_sessions` row stores one in-progress conversational resume-builder draft per user with a 7-day TTL refreshed on every save. A `pg_cron` job (`cleanup-expired-resume-builder-sessions`) hard-deletes expired rows every 5 min and RLS hides expired rows from per-user queries; see [ADR-016](adr/ADR-016-conversational-llm-resume-builder.md).

Each `cached_jobs` row holds one upstream posting keyed on `(source, job_id)`. The table has GENERATED STORED columns (`work_mode`, `employment_type_norm`) backing the dropdown filters and `removed_at` tombstones for upstream-closed jobs the user has bookmarked. A `pg_cron` + `pg_net` schedule POSTs to `/admin/refresh-cache` every ~30 min (see `docs/job_cache_cron_setup.sql`); ranked search reads from this table via the `search_cached_jobs_ranked` RPC, per [ADR-014](adr/ADR-014-postgres-rpc-for-ranked-search.md).

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

Tier-2 / Tier-3 quality runners under `tests/quality/` evaluate LLM-driven components (resume parser, JD parser, renderer fidelity, skill canonicalization, tailoring, review, resume generation, cover letter, resume builder, assistant, end-to-end orchestrator) on fixture sets with weighted scorecards and a `--include-llm` cost gate.

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
