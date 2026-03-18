# Architecture Overview

This document describes the current runtime architecture of the AI Job Application Agent.

## System Goal

The app helps a candidate:

- sign in with Google
- upload and parse a resume
- upload or paste a job description
- generate deterministic fit and tailoring state from those inputs
- run a supervised assisted workflow on demand
- review the tailored resume, cover letter, and application strategy
- export those artifacts as Markdown or PDF
- reload the latest saved workspace snapshot back into `Manual JD Input`

The current codebase is a Streamlit-first product shell around backend-ready parsing, service, orchestration, auth, and persistence layers.

## High-Level Flow

1. The user opens the Streamlit app.
2. The user signs in from the sidebar account panel.
3. The user uploads a resume on `Upload Resume`.
4. The app parses the resume and builds a normalized candidate profile.
5. The user opens `Manual JD Input` and uploads or pastes a job description.
6. Deterministic services build the job model, fit analysis, and first tailoring draft.
7. The supervised workflow can be triggered explicitly from the JD page.
8. The orchestrator runs `fit`, `tailoring`, `strategy`, `review`, `resume_generation`, and `cover_letter` through the routed OpenAI service when available, with deterministic fallback where supported.
9. Builders assemble the current workflow state into a tailored resume artifact, cover letter artifact, and application strategy report.
10. Export helpers produce Markdown and PDF bytes for the current session.
11. For authenticated users, usage events and the latest saved workspace snapshot are persisted in Supabase Postgres.
12. The sidebar `Reload Workspace` action restores that latest saved snapshot back into `Manual JD Input`.

## Main Modules

### `app.py`

Thin entrypoint that imports and starts the Streamlit UI app.

### `src/ui/`

Owns the Streamlit shell:

- page setup
- navigation
- theme and visual components
- page-level rendering
- sidebar account actions
- session-state orchestration

`src/ui/workflow.py` is the main boundary between Streamlit state and the transport-agnostic services, builders, stores, and orchestrator.

### `src/parsers/`

Owns low-level file ingestion and extraction:

- resume parsing
- JD parsing
- defensive file validation

Compatibility wrappers remain at:

- `src/resume_parser.py`
- `src/jd_parser.py`

### `src/services/`

Owns deterministic business logic:

- candidate-profile construction from resume input
- candidate-context assembly
- JD normalization
- fit scoring
- first-pass tailoring guidance

These services are transport-agnostic and do not depend on Streamlit.

### `src/agents/`

Owns the supervised orchestration layer.

The active orchestrator path runs:

- fit
- tailoring
- strategy
- review
- resume generation
- cover letter

The repo still contains `ProfileAgent` and `JobAgent`, but they are not part of the current live orchestrator path.

### `src/prompts.py`

Owns grounded prompt builders for the specialist agents and assistant.

### `src/openai_service.py`

Owns the thin OpenAI wrapper used by the workflow and assistant layers.

Responsibilities include:

- task-aware model routing
- Responses API calls
- GPT-5 reasoning-effort routing
- usage accounting for current runtime metadata
- optional persisted usage-event callbacks
- optional daily-quota preflight checks
- incomplete-response retry handling

### Builders and Exporters

- `src/report_builder.py`: deterministic application-strategy report assembly
- `src/resume_builder.py`: deterministic tailored-resume assembly
- `src/cover_letter_builder.py`: deterministic grounded cover-letter assembly
- `src/exporters.py`: Markdown/PDF export helpers and HTML preview generation

The exporter is WeasyPrint-first with ReportLab fallback.

### Auth and Persistence Modules

- `src/auth_service.py`: Supabase Auth wrapper for Google OAuth
- `src/user_store.py`: syncs lightweight `app_users` records
- `src/usage_store.py`: persists authenticated assisted usage events
- `src/quota_service.py`: computes daily quota state from persisted usage
- `src/saved_workspace_store.py`: persists and loads the latest reloadable workspace snapshot

### `src/config.py`

Owns environment-backed configuration for:

- model routing
- reasoning routing
- quota defaults
- auth and Supabase settings
- saved-workspace retention settings
- local static paths

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
- application reports
- agent outputs
- orchestrated workflow results
- auth and persistence records

### `src/errors.py`

Owns shared typed application errors used across parsing, services, UI, auth, and orchestration.

## State Model

The runtime uses a split state model:

- `st.session_state` for current-session UI and workflow state
- Supabase Postgres for authenticated cross-session persistence

Current-session state includes:

- `current_menu`
- `resume_document`
- `candidate_profile_resume`
- `candidate_profile`
- `job_description_raw`
- `job_description_source`
- `job_description`
- `fit_analysis`
- `tailored_resume_draft`
- `agent_workflow_signature`
- `agent_workflow_result`
- cached export bytes and signatures
- unified assistant conversation history
- authenticated session tokens and synced app-user snapshot

Persistent authenticated state includes:

- `app_users`
- `usage_events`
- `saved_workspaces`

Each `saved_workspaces` row stores one latest snapshot per user, including:

- `workflow_signature`
- `workflow_snapshot_json`
- `report_payload_json`
- `cover_letter_payload_json`
- `tailored_resume_payload_json`
- `expires_at`

That split is deliberate. Current work stays fast inside Streamlit reruns, while quotas and the latest reloadable snapshot live in Supabase.

## Testing Model

The repo includes focused tests for:

- resume parsing
- JD parsing
- profile normalization
- job normalization
- fit scoring
- tailoring guidance
- orchestrator behavior
- report and cover-letter building
- export formatting
- auth and quota behavior
- saved-workspace persistence and reload behavior
- UI workflow state behavior

These tests are intentionally fast and fixture-light so they can run locally and in CI.

## Current Constraints

- `Job Search` is still a placeholder rather than a real provider integration.
- Resume intake is currently login-first in the active UI.
- The product stores only one latest saved workspace snapshot per user; it does not expose a separate history browser.
- Large binary artifacts are not stored in object storage; PDFs are regenerated on demand.
- Streamlit remains the only runtime client even though the service boundaries are backend-ready.

## Next Architecture Step

The next meaningful expansion is still product hardening on the current stack, followed by backend extraction when concurrency and product-control needs justify it.

Near-term targets:

- deployment hardening for the hosted Render environment
- tighter UX around reload, quotas, and artifact review
- continued saved-workspace payload compatibility safety

Later extraction targets:

- FastAPI boundary for orchestration, auth-owned persistence, and export jobs
- Docker as the standard service runtime
- background execution for long-running workflow jobs
- keeping Streamlit as a client during the transition
