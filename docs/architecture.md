# Architecture Overview

This document describes the current runtime architecture of the AI Job Application Agent.

For the broader architectural direction, delivery strategy, multi-agent design, and backend/frontend migration plan, see [docs/project_strategy.md](project_strategy.md).

## System Goal

The app helps a candidate prepare stronger application inputs by:

- parsing an uploaded resume
- parsing a job description from file upload, sample input, or pasted text
- importing a LinkedIn data export archive
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
4. Job descriptions are parsed, cleaned, and reduced into simple structured signals.
5. LinkedIn ZIP exports are normalized into profile, education, skills, preferences, and experience data.
6. Parsed outputs are stored in `st.session_state` so data survives page switches.
7. The UI renders extracted previews that will later feed tailoring and generation steps.

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
- job-description normalization into shared schemas

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
- `job_description_raw`
- `job_description_source`
- `job_description`

This is appropriate for a single-user Streamlit MVP. If the app later adds user accounts or long-running workflows, state should move into a persistent store.

## Testing Model

The repo now includes parser-focused tests under `tests/` for:

- resume parsing
- job-description parsing
- LinkedIn export parsing

These tests are intentionally fast and file-light so they can run in local development and CI without large fixtures.

## Next Architecture Step

The next meaningful expansion is an orchestration layer for:

- tailoring resumes against parsed job descriptions
- scoring fit and missing qualifications
- generating recruiter-facing application artifacts

That logic should live in new `src/agents/`, `src/services/`, and `src/report_builder.py` modules rather than expanding parser code or embedding LLM logic directly into the UI layer.
