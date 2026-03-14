# Architecture Overview

This document describes the current runtime architecture of the AI Job Application Agent.

For the broader architectural direction, delivery strategy, multi-agent design, and backend/frontend migration plan, see [docs/project_strategy.md](project_strategy.md).

## System Goal

The app helps a candidate prepare stronger application inputs by:

- parsing an uploaded resume
- parsing a job description from file upload, sample input, or pasted text
- scoring baseline fit against a target role
- generating deterministic tailoring guidance
- running a supervised specialist-agent workflow on demand
- generating a tailored resume artifact and application report
- exporting those artifacts as Markdown, PDF, or ZIP
- gating assisted workflow execution behind authenticated account state when configured
- persisting usage, workflow history, and artifact metadata for authenticated users
- regenerating historical downloads from saved workflow payloads

The current codebase is structured as a Streamlit-first product shell around backend-ready domain, orchestration, auth, and persistence layers.

## High-Level Flow

1. The user opens the Streamlit app.
2. The user chooses one of four UI flows:
   - resume upload
   - job search placeholder
   - manual job-description input
   - authenticated history
3. Resume files are parsed into normalized text.
4. Job descriptions are parsed, cleaned, and reduced into structured requirements.
5. Deterministic services generate a fit snapshot and a first tailoring draft.
6. If assisted workflow is enabled, Google sign-in restores or creates authenticated account state through Supabase Auth.
7. A supervised agent workflow can be triggered explicitly from the JD screen.
8. The orchestrator runs specialist agents, bounded review passes, and final resume generation through the routed OpenAI service when available, with deterministic fallback where supported.
9. Builders assemble the current workflow state into a deterministic application report and tailored resume artifact.
10. Export helpers produce Markdown, PDF, and ZIP bytes for the current session.
11. For authenticated users, usage events, workflow runs, and artifact metadata are persisted in Supabase Postgres.
12. The History page reconstructs saved reports and resumes from stored payload JSON rather than from current in-session inputs.
13. Streamlit state keeps current-session inputs and view state available across reruns and navigation.

## Main Modules

### `app.py`

Acts as a thin entrypoint:

- imports the Streamlit UI app
- starts the main UI function

### `src/ui/`

Owns the Streamlit UI shell:

- page setup
- navigation
- styling and visual components
- page-level render functions
- session-driven flow transitions
- authenticated account panel and History page rendering

`src/ui/workflow.py` is the main boundary layer between Streamlit state and the transport-agnostic services, builders, stores, and orchestrator.

### `src/parsers/`

Owns raw file ingestion and low-level extraction:

- resume parsing
- job-description parsing
- file validation and defensive parsing behavior

Compatibility wrappers remain at:

- `src/resume_parser.py`
- `src/jd_parser.py`

### `src/services/`

Owns deterministic normalization and non-UI workflow helpers:

- candidate profile creation from resume input
- candidate-context building for analysis and prompting
- job-description normalization into shared schemas
- fit scoring against job requirements
- deterministic resume-tailoring guidance

These services are pure business-logic components and do not depend on Streamlit.

### `src/report_builder.py`

Owns deterministic final report assembly from:

- normalized candidate data
- normalized job data
- deterministic fit output
- deterministic tailoring output
- optional supervised agent output

The report builder produces the exact payload later reused for authenticated historical report regeneration.

### `src/resume_builder.py`

Owns deterministic final tailored-resume assembly from the active workflow state and selected resume theme.

### `src/exporters.py`

Owns lightweight export helpers for the application package and tailored resume:

- Markdown bytes
- PDF bytes
- ZIP bundle bytes
- Playwright/Chromium as the primary PDF backend
- ReportLab as the fallback PDF backend

### `src/agents/`

Owns the supervised orchestration layer:

- profile agent
- job agent
- fit agent
- tailoring agent
- strategy agent
- review agent
- resume generation agent
- orchestrator that coordinates them

The agent layer can use OpenAI when configured and falls back to deterministic output when it is not.

### `src/prompts.py`

Owns centralized grounded prompt builders for the specialist agents.

### `src/openai_service.py`

Owns the thin OpenAI client wrapper used by the orchestration and assistant layers.

Responsibilities include:

- task-aware model routing
- Responses API calls
- session usage tracking
- optional persisted usage-event callbacks
- optional daily-quota preflight checks

### `src/assistant_service.py`

Owns the two-mode grounded assistant used in the UI:

- product-help mode (`Using the App`)
- grounded resume/application Q&A mode (`About My Resume`)

This stays separate from the supervised workflow agents because it serves conversational assistance rather than structured workflow output.

### Persistence and Auth Modules

- `src/auth_service.py`: Supabase Auth wrapper for Google OAuth, code exchange, session restore, and sign-out
- `src/user_store.py`: syncs lightweight `app_users` records
- `src/usage_store.py`: persists authenticated assisted usage events
- `src/quota_service.py`: computes daily quota state from persisted usage
- `src/history_store.py`: persists and loads workflow runs plus artifact metadata

### `src/config.py`

Owns project paths and environment-backed configuration:

- static asset directories
- model routing configuration
- auth and Supabase table configuration
- plan-based daily quota defaults
- feature flags such as assisted-workflow login requirements

### `src/schemas.py`

Owns shared typed models for:

- resumes
- candidate profiles
- work experience
- education
- job descriptions
- job requirements
- fit analyses
- tailoring drafts
- tailored resume artifacts
- application reports
- agent outputs
- orchestrated workflow results
- auth and persistence records

### `src/errors.py`

Owns shared typed application errors used across UI, parsing, and future orchestration.

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
- assistant conversation history
- selected history workflow-run id
- authenticated session tokens and synced app-user snapshot

Persistent authenticated state includes:

- `app_users`
- `usage_events`
- `workflow_runs`
- `artifacts`

`workflow_runs` now stores lightweight reconstruction payloads:

- `workflow_signature`
- `workflow_snapshot_json`
- `report_payload_json`
- `tailored_resume_payload_json`

New workflow runs write those payloads through a versioned JSON envelope so historical regeneration can evolve without silently breaking older saved runs. The reader remains backward-compatible with the earlier unversioned payloads.

That split is deliberate. Current in-progress work stays fast and local to Streamlit reruns, while account-bound history and quota enforcement live in Supabase.

## Testing Model

The repo now includes focused tests under `tests/` for:

- resume parsing
- job-description parsing
- profile normalization
- job normalization
- fit scoring
- tailoring guidance
- orchestrator behavior
- report building
- export formatting
- auth and quota behavior
- history persistence and saved-payload reconstruction
- UI workflow state behavior

These tests are intentionally fast and file-light so they can run in local development and CI without large fixtures.

## Current Constraints

- The `Job Search` page is still a placeholder rather than a real provider integration.
- Large binary artifacts are not stored in object storage; the app currently prefers cheap Postgres metadata plus on-demand regeneration.
- Streamlit remains the only runtime client even though the service boundaries are backend-ready.

## Next Architecture Step

The next meaningful expansion is delivery hardening and persistence maturation rather than another new core workflow. The main targets are:

- deployment hardening for a real hosted Streamlit environment
- migration guidance and compatibility hardening for saved workflow reconstruction
- additional UX polish around history, quotas, and exported package review
- optional object storage only if binary artifact retention becomes a product requirement
- later API exposure of the same orchestration entrypoint through FastAPI once multiple clients or async work justify it

That work should continue to live outside the UI layer, primarily in the existing stores, builders, orchestration modules, and future backend wrappers.
