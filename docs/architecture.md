# Architecture Overview

This document describes the current runtime architecture of the AI Job Application Agent.

For the broader architectural direction, delivery strategy, multi-agent design, and backend/frontend migration plan, see [docs/project_strategy.md](project_strategy.md).

## System Goal

The app helps a candidate prepare stronger application inputs by:

- parsing an uploaded resume
- parsing a job description from file upload, sample input, or pasted text
- importing a LinkedIn data export archive
- merging candidate signals from resume and LinkedIn
- scoring baseline fit against a target role
- generating deterministic tailoring guidance
- running a supervised specialist-agent workflow on demand
- assembling an exportable application package
- keeping extracted data available across Streamlit navigation

The current codebase is structured to support the next phase: resume tailoring, job matching, and application workflow orchestration.

## High-Level Flow

1. The user opens the Streamlit app.
2. The user chooses one of four UI flows:
   - resume upload
   - LinkedIn import
   - job search placeholder
   - manual job-description input
3. Resume files are parsed into normalized text.
4. LinkedIn ZIP exports are normalized into profile, education, skills, preferences, and experience data.
5. Job descriptions are parsed, cleaned, and reduced into structured requirements.
6. Resume and LinkedIn candidate sources are merged into a single candidate profile when both exist.
7. Deterministic services generate a fit snapshot and a first tailoring draft.
8. A supervised agent workflow can be triggered explicitly from the JD screen.
9. A report builder assembles the current workflow state into a deterministic application package.
10. Parsed outputs are stored in `st.session_state` so data survives page switches.
11. The UI renders extracted previews, fit insights, tailoring guidance, agent-review output, and download actions.

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

### `src/parsers/`

Owns raw file ingestion and low-level extraction:

- resume parsing
- job-description parsing
- LinkedIn export parsing
- file validation and defensive parsing behavior

Compatibility wrappers remain at:

- `src/resume_parser.py`
- `src/jd_parser.py`
- `src/linkedin_parser.py`

### `src/services/`

Owns deterministic normalization and non-UI workflow helpers:

- candidate profile creation from parsed sources
- candidate-profile merging and context building
- job-description normalization into shared schemas
- fit scoring against job requirements
- deterministic resume-tailoring guidance

### `src/report_builder.py`

Owns deterministic final report assembly from:

- normalized candidate data
- normalized job data
- deterministic fit output
- deterministic tailoring output
- optional supervised agent output

### `src/exporters.py`

Owns lightweight export helpers for the application package:

- Markdown bytes
- PDF bytes
- Playwright/Chromium as the primary PDF backend
- ReportLab as the fallback PDF backend

### `src/agents/`

Owns the supervised orchestration layer:

- profile agent
- job agent
- fit agent
- tailoring agent
- review agent
- orchestrator that coordinates them

The agent layer can use OpenAI when configured and falls back to deterministic output when it is not.

### `src/prompts.py`

Owns centralized grounded prompt builders for the specialist agents.

### `src/openai_service.py`

Owns the thin OpenAI client wrapper used by the orchestration layer.

### `src/config.py`

Owns project paths and environment-backed configuration:

- static asset directories
- OpenAI model default
- optional OpenAI key loading

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
- agent outputs
- orchestrated workflow results

### `src/errors.py`

Owns shared typed application errors used across UI, parsing, and future orchestration.

## State Model

The app currently relies on `st.session_state` for lightweight workflow persistence.

Tracked state includes:

- `current_menu`
- `resume_document`
- `candidate_profile_resume`
- `linkedin_data`
- `candidate_profile_linkedin`
- `candidate_profile`
- `job_description_raw`
- `job_description_source`
- `job_description`
- `fit_analysis`
- `tailored_resume_draft`
- `agent_workflow_signature`
- `agent_workflow_result`

This is appropriate for a single-user Streamlit MVP. If the app later adds user accounts or long-running workflows, state should move into a persistent store.

## Testing Model

The repo now includes focused tests under `tests/` for:

- resume parsing
- job-description parsing
- LinkedIn export parsing
- profile normalization
- job normalization
- fit scoring
- tailoring guidance
- orchestrator behavior
- report building
- export formatting

These tests are intentionally fast and file-light so they can run in local development and CI without large fixtures.

## Next Architecture Step

The next meaningful expansion is the delivery hardening layer for:

- richer recruiter-facing package structure
- revision loops driven by review-agent feedback
- deployment readiness for Streamlit hosting
- later API exposure of the same orchestration entrypoint through FastAPI

That logic should continue to live outside the UI layer, primarily in `src/report_builder.py`, the existing agent modules, and future backend wrappers.
