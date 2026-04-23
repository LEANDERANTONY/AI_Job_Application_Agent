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
- export Markdown or PDF versions of the generated documents

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
5. The user can search configured Greenhouse and Lever sources, paste a supported job URL, or continue manually with JD text.
6. The app builds a structured JD summary for review.
7. The user explicitly triggers the agentic workflow.
8. The orchestrator runs `fit`, `tailoring`, `review`, `resume_generation`, and `cover_letter`.
9. Builders assemble the tailored resume and cover letter.
10. The workspace assistant answers grounded questions from the current workspace state.
11. Export helpers produce Markdown and PDF files for the current document.
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
- `backend/routers/jobs.py` exposes search and direct job-resolution endpoints
- `backend/routers/auth.py` owns auth/session endpoints
- `backend/routers/workspace.py` owns resume, JD, workflow, assistant, persistence, preview, and export endpoints

### `src/services/`

Owns deterministic business logic:

- candidate-profile construction from resume input
- JD normalization
- fit scoring
- first-pass tailoring guidance

These services are transport-agnostic and do not depend on Next.js or FastAPI.

### `src/agents/`

Owns the supervised orchestration layer.

The active orchestrator path runs:

- fit
- tailoring
- review
- resume generation
- cover letter

The earlier strategy stage is no longer part of the live workflow.

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
- `src/report_builder.py`: internal report assembly still available for backend use and diagnostics
- `src/exporters.py`: Markdown/PDF export helpers and HTML preview generation

The user-facing workspace is now centered on two visible outputs:

- tailored resume
- cover letter

The resume export path has been simplified to one standard ATS-friendly format.

### Auth and Persistence Modules

- `src/auth_service.py`: Supabase Auth wrapper for Google OAuth
- `src/user_store.py`: syncs lightweight `app_users` records
- `src/usage_store.py`: persists authenticated assisted usage events
- `src/quota_service.py`: computes daily quota state from persisted usage
- `src/saved_workspace_store.py`: persists and loads the latest reloadable workspace snapshot
- `src/saved_jobs_store.py`: persists and loads shortlisted jobs

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
- Supabase Postgres for authenticated persistence

Persistent authenticated state includes:

- `app_users`
- `usage_events`
- `saved_workspaces`
- `saved_jobs`

Each `saved_workspaces` row stores one latest snapshot per user, including enough data to restore the current resume/JD/workflow state.

Each `saved_jobs` row stores one shortlisted posting per user and normalized job id, including:

- source/provider identity
- title, company, location, and employment type
- source URL
- normalized summary and description text
- provider metadata
- saved and updated timestamps

## Testing Model

The repo includes focused tests for:

- resume parsing
- JD parsing
- profile normalization
- job normalization
- fit scoring
- tailoring guidance
- orchestrator behavior
- resume and cover-letter building
- export formatting
- auth and quota behavior
- saved-workspace persistence
- saved-job persistence
- backend workspace routes

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
