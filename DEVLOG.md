# DEVLOG - AI Job Application Agent

This document tracks notable implementation milestones and technical decisions.

## Day 1: Project Setup and Resume Parsing

- Initialized the repository, virtual environment, license, and Streamlit shell.
- Added an MVP navigation flow covering resume upload, LinkedIn import, job search, and manual JD input.
- Chose lightweight parsing dependencies first:
  - `pypdf`
  - `python-docx`

## Day 2: Demo Inputs and Unified File Parsing

- Added sample resumes and sample job descriptions under `static/`.
- Updated parsing code so both uploaded files and local demo files work through the same logic.
- Added basic job-description cleaning and simple extraction for title, location, experience, and skills.

## Day 3: LinkedIn Import and Session Persistence

- Added LinkedIn data-export ZIP ingestion instead of direct LinkedIn API access.
- Parsed summary, education, skills, preferences, publications, and position history where present.
- Stored parsed payloads in `st.session_state` so the UI survives navigation and reruns.

## Day 4: Repo Structure Alignment With GitHub Agent

- Moved the active application logic into `src/`.
- Refactored `app.py` into a cleaner Streamlit entrypoint with section-level render functions.
- Added parser-focused tests under `tests/`.
- Added `docs/architecture.md`, ADR files under `docs/adr/`, a roadmap, and a real README.
- Improved parsing behavior:
  - TXT resumes are now supported
  - job-description cleanup preserves line breaks
  - JD source persistence now stores parsed text instead of the raw uploaded file object

## Day 5: Modular UI and Defensive Parser Refactor

- Reduced root `app.py` to a thin entrypoint and moved UI composition into `src/ui/`.
- Split the codebase into clearer layers:
  - `src/parsers/` for raw ingestion and extraction
  - `src/services/` for normalization and deterministic workflow helpers
  - `src/ui/` for Streamlit theme, components, navigation, and pages
- Kept top-level parser modules as compatibility wrappers so existing imports and tests continue to work.
- Added `ResumeDocument` to the shared schemas and started using typed objects more consistently in the UI.
- Hardened parser behavior with more defensive checks:
  - explicit empty-file handling
  - clearer unsupported-format failures
  - safer PDF and DOCX open failures
  - better LinkedIn ZIP validation and normalization
- Verified the refactor with:
  - `uv run pytest`
  - `uv run python -m compileall app.py src tests`

## Day 6: Deterministic Fit Analysis Foundation

- Expanded the typed schema layer with:
  - `FitAnalysis`
  - `TailoredResumeDraft`
  - richer `CandidateProfile` source signals
- Added shared keyword taxonomy in `src/taxonomy.py` so resume and JD matching use the same vocabulary.
- Improved profile normalization in `src/services/profile_service.py`:
  - basic name and location inference from resumes
  - keyword extraction from resume text
  - merge logic for resume and LinkedIn candidate sources
  - candidate-context text assembly for downstream analysis
- Improved job normalization in `src/services/job_service.py`:
  - empty-input validation
  - must-have and nice-to-have signal extraction
  - cleaner requirement deduplication
- Added new deterministic workflow services:
  - `src/services/fit_service.py`
  - `src/services/tailoring_service.py`
- Updated the Streamlit JD page to render:
  - merged candidate readiness
  - fit score and gap analysis
  - first-pass tailored resume guidance
- Extended test coverage for:
  - profile normalization
  - job normalization
  - fit scoring
  - tailoring output
- Verified the new workflow layer with:
  - `uv run pytest`
  - `uv run python -m compileall app.py src tests`

## Day 7: Supervised Agent Workflow Layer

- Added the first supervised multi-agent stack under `src/agents/`:
  - `profile_agent.py`
  - `job_agent.py`
  - `fit_agent.py`
  - `tailoring_agent.py`
  - `review_agent.py`
  - `orchestrator.py`
- Added `src/prompts.py` for centralized grounded prompt construction.
- Added `src/openai_service.py` as a thin OpenAI wrapper with JSON-response validation and typed failure handling.
- Expanded schemas with typed agent outputs and `AgentWorkflowResult`.
- Kept the system defensive:
  - the agent workflow only runs when the user explicitly clicks a button
  - OpenAI usage is optional
  - if model execution is unavailable or fails, orchestration falls back to deterministic output
- Updated the JD page so it can now:
  - run supervised orchestration on demand
  - cache workflow results against the current candidate/JD signature
  - render profile positioning, fit narrative, tailoring output, and review notes
- Added orchestrator tests covering:
  - deterministic fallback mode
  - successful AI-assisted mode with a fake service
  - graceful fallback when AI execution fails
- Verified the agent layer with:
  - `uv run pytest`
  - `uv run python -m compileall app.py src tests`

## Day 8: Report Builder and Export Layer

- Added `src/report_builder.py` to assemble a deterministic application package from:
  - candidate profile
  - job description
  - fit analysis
  - tailored draft
  - optional supervised agent output
- Added `src/exporters.py` for initial package export handling.
- Updated the JD page to:
  - render an application-package preview
  - expose Markdown download
  - automatically upgrade the package when agent output is available
- Updated top-level UI copy so the app now reflects package/export readiness.
- Added tests covering:
  - report construction
  - export byte formatting
- Verified the report/export layer with:
  - `uv run pytest`
  - `uv run python -m compileall app.py src tests`

## Day 9: Playwright-First PDF Export

- Upgraded the export layer to support polished PDF output.
- Chose the same pattern used in the GitHub agent:
  - Playwright/Chromium as the primary PDF renderer
  - ReportLab as the fallback backend
- Updated the JD page so users can:
  - prepare a PDF package explicitly
  - download a polished PDF once it is generated
- Kept Markdown export as the editable output format for users who want to make manual changes before sharing.
- Added export tests covering:
  - HTML report generation
  - ReportLab fallback when the Playwright backend fails
  - typed failure handling when both PDF backends fail
- Installed and validated local PDF dependencies, including Chromium for Playwright.
- Verified PDF export behavior with:
  - `uv run pytest`
  - `uv run python -m compileall app.py src tests`
  - direct Playwright and fallback PDF smoke checks

## Day 10: Codebase Hardening and CI

- Fixed the pytest configuration so tests can resolve `src` imports:
  - added `[tool.pytest.ini_options]` with `pythonpath = ["."]` to `pyproject.toml`
- Expanded the skill taxonomy in `src/taxonomy.py`:
  - hard skills went from 20 to ~140 entries covering programming languages, data/ML, frameworks, databases, cloud, web/API, and DevOps
  - soft skills went from 10 to 30 entries
- Extracted shared utility functions into `src/utils.py`:
  - `dedupe_strings` and `match_keywords` were duplicated across four service files and the JD parser
  - replaced all copies with imports from the shared module
- Removed Streamlit coupling from the parser layer:
  - removed `@st.cache_data` decorators and `import streamlit as st` from `src/parsers/resume.py` and `src/parsers/jd.py`
  - parsers are now pure functions that work in any context (FastAPI, CLI, tests)
- Updated the GitHub Actions CI workflow:
  - scoped triggers to the `main` branch
  - switched to the official `astral-sh/setup-uv` action
  - added a `python -m compileall` check step
  - enabled verbose test output
- Removed obsolete `requirements.txt` and `requirements-dev.txt` export files since `pyproject.toml` and `uv.lock` are the dependency source of truth.
- Normalized all DEVLOG verification commands from `venv\Scripts\python.exe` to `uv run`.
- Verified the hardened codebase with:
  - `uv run pytest`
  - `uv run python -m compileall app.py src tests`

## Day 11: Scope Tightening Around Resume + JD Workflow

- Removed LinkedIn import from the active product and codebase.
- Simplified candidate-profile handling so the working profile comes directly from resume parsing.
- Deleted LinkedIn parser modules and their test coverage.
- Updated UI navigation and copy to reflect the narrower, lower-friction intake flow.
- Added an ADR documenting why LinkedIn export ingestion was removed from the product scope.
- Verified the removal pass with targeted search, compile checks, and focused tests.

## Day 12: Review-Driven Iteration, Strategy, and Observability

- Added a bounded review-revision loop in the orchestrator so rejected tailoring output is revised before finalizing the workflow result.
- Added the `StrategyAgent` and integrated it into the supervised workflow.
- Added structured JSON logging for workflow and OpenAI request lifecycle events.
- Added session-level OpenAI usage tracking and budget guards.
- Refactored Streamlit state access behind `src/ui/state.py` and moved UI workflow orchestration into `src/ui/workflow.py`.
- Verified the architecture pass with:
  - `uv run pytest`
  - `uv run python -m compileall app.py src tests`

## Day 13: Tailored Resume Artifact and Export Expansion

- Added a dedicated `ResumeGenerationAgent` after review in the supervised pipeline.
- Added `src/resume_builder.py` to build a direct-use tailored resume artifact from grounded workflow state.
- Added resume themes:
  - `classic_ats`
  - `modern_professional`
- Extended export support so both report and tailored resume can be exported as Markdown and PDF.
- Added a combined ZIP export bundle for the resume and report together.
- Added resume diff support in `src/resume_diff.py` and exposed original-vs-tailored comparison in the UI.
- Verified the new artifact and export flow with:
  - `uv run pytest`
  - `uv run python -m compileall app.py src tests`

## Day 14: Grounded Assistant, Model Routing, and Responses API Migration

- Added a shared two-mode assistant panel with:
  - `Using the App`
  - `About My Resume`
- Implemented the assistant as one service with explicit grounded modes instead of creating more orchestrator agents.
- Added per-task model routing so high-trust tasks can use stronger models while lower-risk tasks stay on cheaper tiers.
- Migrated the OpenAI wrapper from Chat Completions to the Responses API.
- Extended usage tracking to retain per-model totals internally while keeping only session-capacity messaging in the UI.
- Added the model sizing and routing reference in `docs/model-latency-and-cost-estimates.md`.
- Added Google sign-in architecture planning in `docs/google-signin-implementation-plan.md`.
- Added ADRs for:
  - the two-mode assistant decision
  - Google sign-in via Supabase as the persistent identity direction
- Verified the current integrated state with:
  - `uv run pytest`
  - successful commit and push to `origin/main`

## Day 15: Google Sign-In Foundation

- Added `src/auth_service.py` as a Supabase-backed auth wrapper for:
  - Google OAuth start
  - auth-code exchange
  - session restore
  - sign-out
- Added Supabase auth configuration in `src/config.py` and example environment variables for local setup.
- Extended `src/ui/state.py` with authenticated user, token, and auth-error state helpers.
- Bootstrapped auth callback handling and session restoration in the Streamlit app shell.
- Added a sidebar account panel for sign-in and sign-out.
- Gated the AI-assisted workflow behind authenticated account state while keeping deterministic resume and JD flows available without login.
- Added focused auth tests and verified the integration with:
  - `uv run pytest`

Persistent per-user usage storage, saved artifact history, and quotas are intentionally left for later Supabase-backed phases.

## Day 16: Persistent App User Record

- Added `src/user_store.py` to sync a lightweight `app_users` record after Google sign-in and on session restore.
- Added `AppUserRecord` to the shared schema layer for plan-tier and account-status state.
- Extended config and environment examples for the `app_users` table name and default account metadata.
- Updated the sidebar account panel to surface persisted plan and account status when the sync succeeds.
- Kept login resilient: auth still works even if the Supabase table or RLS policy is not ready yet.

## Day 17: External Usage Persistence on Supabase Postgres

- Added `src/usage_store.py` to persist assisted usage events in Supabase Postgres for authenticated users.
- Extended `src/openai_service.py` with an optional usage-event callback so persistence stays transport-agnostic.
- Wired authenticated usage-event recording from `src/ui/workflow.py` without leaking Streamlit concerns into the service layer.
- Added the `usage_events` SQL schema and RLS policies in `docs/supabase-usage-events.sql`.
- Kept assisted requests resilient: usage persistence failures are logged but do not break the user-facing AI response.

## Day 18: Daily Quotas From Persisted Usage

- Added `src/quota_service.py` to compute per-user daily assisted limits from persisted `usage_events`.
- Extended `src/usage_store.py` with daily usage aggregation for the current UTC day.
- Wired quota checks into `src/openai_service.py` as a preflight hook so assisted requests stop cleanly when the daily cap is exhausted.
- Updated the JD workflow UI to show daily remaining assisted capacity alongside the existing session-level view.
- Added plan-tier daily quota configuration through environment variables for free and paid tiers.

## Day 19: Workflow History and Artifact Metadata

- Added `src/history_store.py` to persist authenticated workflow runs and artifact metadata in Supabase Postgres.
- Wired supervised workflow completion to create `workflow_runs` records.
- Wired export preparation to create `artifacts` records for generated PDFs and ZIP bundles.
- Added recent workflow and artifact history to the sidebar account panel.
- Added Supabase schema and RLS setup in `docs/supabase-workflow-history.sql`.

## Day 20: History Page and Supabase Bootstrap

- Added a dedicated `History` page in the Streamlit navigation.
- Centralized authenticated history refresh so sign-in and session restore load the same recent workflow and artifact state.
- Added `docs/supabase-bootstrap.sql` as a one-shot setup path for `app_users`, `usage_events`, `workflow_runs`, and `artifacts`.
- Updated README setup guidance to reflect the working Supabase-backed auth, quota, and history path.

## Day 21: Saved-Run Regeneration and History-State Separation

- Extended `workflow_runs` to persist saved reconstruction payloads:
  - `workflow_signature`
  - `workflow_snapshot_json`
  - `report_payload_json`
  - `tailored_resume_payload_json`
- Added historical regeneration helpers so saved reports, tailored resumes, PDFs, and ZIP bundles can be rebuilt from persisted payloads without re-running OpenAI.
- Separated history selection state from the active current workflow run so new exports do not attach to an older historical run by mistake.
- Added additive Supabase migration support in `docs/supabase-workflow-history-payloads-migration.sql`.
- Verified the history-regeneration path with focused tests and a passing full suite.

## Day 22: Documentation Re-Baselining

- Rewrote the architecture, strategy, roadmap, and README narrative so the published repo matches the implemented product.
- Documented the current operating model more clearly:
  - Streamlit-first UI shell
  - supervised specialist-agent workflow
  - Supabase-backed auth, quotas, and history
  - saved-payload historical regeneration instead of blob storage
- Cleaned up stale product-copy references that still described persistence and history as future work.
