# DEVLOG - AI Job Application Agent

This document tracks notable implementation milestones and technical decisions.

Historical note:

- earlier entries reflect the product and architecture assumptions at the time they were written
- later entries supersede earlier history when the product direction changed, especially around LinkedIn import, workflow history, session-level quota UX, and persistence structure

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

## Day 18: Deterministic JD Parsing Re-baseline

- Reverted the experimental resume/JD parser-verifier agent layer and returned intake parsing to the deterministic path.
- Kept the deterministic JD parsing improvements that were useful on their own:
  - broader extraction for `Required Experience:` style phrasing
  - filtering `Location:` lines out of preferred / nice-to-have buckets
  - real fixture coverage for JD PDF and DOCX samples already stored under `static/demo_job_description/`
- Verified the rollback plus retained parser improvements with:
  - `uv run pytest tests/test_profile_service.py tests/test_job_service.py tests/test_jd_parser.py tests/test_resume_parser.py tests/test_orchestrator.py`

## Day 18: Single-Pass Review-Correction Workflow

- Removed the live `ProfileAgent` and `JobAgent` stages from the supervised workflow because they were mostly restating deterministic inputs without adding enough value for the latency cost.
- Simplified the active orchestrator path to:
  - fit
  - tailoring
  - strategy
  - review
  - resume generation
- Removed the bounded rerun loop that previously sent tailoring and strategy back through another full pass after review.
- Changed Review so it can return direct corrections for tailoring and strategy, and the orchestrator now feeds those corrected outputs straight into final resume generation.
- Removed interview-theme style outputs that were adding contract size without being core to the current product output.
- Updated the UI, payload layer, and report rendering so they reflect the smaller workflow and the direct-correction review model.
- Verified the redesign with focused workflow, prompt, builder, and UI test coverage.

## Day 19: Model Routing And Output Budget Tuning

- Rebalanced reasoning effort by task based on real runtime logs instead of keeping one default posture for every agent.
- Changed the active routing defaults to:
  - `fit`: `gpt-5-mini-2025-08-07` with `low` reasoning
  - `tailoring`: `gpt-5-mini-2025-08-07` with `medium` reasoning
  - `strategy`: `gpt-5-mini-2025-08-07` with `low` reasoning
  - `review`: `gpt-5.4` with `medium` reasoning
  - `resume_generation`: `gpt-5.4` with `medium` reasoning
- Increased the Review output budget to start at 4000 tokens so the stage does not immediately fall into retry-on-truncation for corrected JSON payloads.
- Reduced oversized output caps where observed usage made the previous limits unnecessary:
  - `fit`: 1600
  - `strategy`: 1500
  - `resume_generation`: 3000
- Kept `tailoring` at 3200 and `review` at 4000 because they still carry the heaviest grounded payloads in the current flow.
- Verified the new routing and cap defaults with targeted orchestration and OpenAI-service tests.

## Day 20: Review Approval Semantics And Backward Compatibility

- Clarified Review semantics so `approved` now means the final corrected output is safe to use, not that the incoming tailoring or strategy draft was perfect before correction.
- Added `unresolved_issues` to the review contract so the app can distinguish between:
  - issues found in the incoming draft
  - blockers that still remain after correction
- Updated UI and report labels to show `Approved After Corrections` when Review repaired the output successfully.
- Added backward-compatible access patterns so older saved or in-memory `ReviewAgentOutput` objects without `unresolved_issues` do not crash the app.
- Logged PDF-output quality as a follow-up documentation item because export aesthetics still need a dedicated pass even though workflow runtime is now much healthier.
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

## Day 23: Payload Versioning and History UX Tightening

- Wrapped new saved workflow payloads in a versioned JSON envelope while keeping the historical reader backward-compatible with the earlier unversioned payload format.
- Added compatibility inspection so unsupported or malformed saved payloads fail visibly in the History page instead of silently producing incorrect downloads.
- Clarified quota UX by separating account-level daily quota messaging from browser-session safeguards.
- Made the History page more explicit that browsing old runs is read-only and does not retarget new exports away from the current active workflow run.

## Day 24: Pre-Deployment Hardening and Hosting Decision

- Split the remaining large UI workflow and page boundaries behind stable facades while preserving the public entrypoints.
- Extracted duplicated builder helpers into shared utilities and centralized UI-side `AuthService` access.
- Cleaned the remaining pre-launch hygiene items:
  - removed unused helper code
  - consolidated duplicate string-list normalization logic
  - replaced `datetime.utcnow()` with a timezone-aware UTC clock path
  - documented the ReportLab `md5` compatibility patch
- Expanded boundary coverage for fit, job, tailoring, strategy, and logging modules.
- Added `.streamlit/config.toml` and reworked deployment docs so the app can be deployed before Supabase is provisioned.
- Chose **Streamlit Community Cloud** as the first deployment target while keeping the existing Playwright/Chromium-first PDF path and retaining ReportLab as the runtime fallback.

## Day 25: Supabase Auth Stabilization and Local Operator Setup

- Added repo-root `.env` loading for local development while preserving hosted secret-manager compatibility through `os.getenv(...)`.
- Added `docs/supabase-setup-checklist.md` as the canonical fresh-project operator guide for Supabase setup.
- Stabilized Supabase Google sign-in for the Streamlit rerun model by preserving PKCE verifier state across the OAuth redirect and callback exchange.
- Fixed the sidebar navigation handoff so JD-page transitions no longer mutate `current_menu` after the radio widget is instantiated.
- Removed stale fresh-install guidance that still pointed at the earlier workflow-history migration file.
- Verified the auth and navigation changes with focused tests and a passing full suite.

## Day 26: OpenAI Runtime Hardening and Reasoning Routing

- Diagnosed assisted-workflow fallback to a GPT-5 compatibility issue in the Responses API path: routed models were rejecting `temperature`.
- Updated `src/openai_service.py` to retry without `temperature` when the routed model rejects that parameter.
- Added a retry path for incomplete Responses API outputs caused by exhausted `max_output_tokens`.
- Increased the OpenAI client timeout and enabled SDK retries to reduce transient `read operation timed out` failures in the assistant path.
- Added per-task GPT-5 reasoning routing:
  - medium effort for normal workflow tasks
  - high effort for review, resume generation, and grounded application-QA tasks
- Extended `.env.example` and config helpers so reasoning effort can be tuned without editing code.
- Verified the stabilized OpenAI path with targeted service tests, live local probes, and a passing full suite.

## Day 27: Saved Workspace Retention Hardening

- Removed the legacy `workflow_runs` and `artifacts` persistence path so the product now stores only one latest `saved_workspaces` snapshot per user.
- Simplified runtime config, state, exports, and tests around the latest-only saved workspace model.
- Updated the Supabase bootstrap so expired saved workspaces become unreadable exactly at `expires_at` through RLS.
- Added a Supabase scheduled cleanup job that deletes expired saved-workspace rows every 5 minutes, even if the user never returns.
- Kept the app-side save/load purge as a backup cleanup path in case the scheduled job is temporarily unavailable.

## Day 28: Saved Workspace UX Simplification And Doc Re-Baseline

- Removed the dead dedicated saved-workspace page and its unused test path because the product now restores the latest saved snapshot only through the sidebar `Reload Workspace` action.
- Removed history-only helper paths that were left behind from the earlier `workflow_runs` era.
- Updated the assistant and retrieved product knowledge so they describe the current reload flow accurately and no longer mention the removed page or the old live `ProfileAgent` / `JobAgent` path.
- Re-baselined the active docs around the real shipped state:
  - login-first resume intake
  - no separate history tab
  - one latest reloadable saved workspace per user
  - current Render + Docker + Supabase deployment path
- Removed broken README/checklist references to docs that are no longer in the repo.

## Day 29: Render Auth Stabilization And Saved Usage Refresh

- Stabilized Google sign-in on Render across the Supabase callback flow.
- Fixed PKCE callback persistence issues caused by the hosted Streamlit redirect/runtime model.
- Fixed the sign-in button navigation regression after the callback hardening changes.
- Added a server-side fallback path so the auth code exchange no longer depends only on a returned custom query parameter.
- Fixed same-session quota refresh behavior after successful assisted workflow runs so the sidebar reflects updated account state without requiring a fresh login.

## Day 30: Login-Required AI Features And Quota Simplification

- Made the in-app assistant login-required in the active product.
- Simplified quota UX so the product now presents account-level daily quota as the main user-facing assisted limit.
- Removed browser-session assisted budget from the live UI and current product copy.
- Re-aligned assistant fallback behavior, product knowledge, prompt guidance, and README language around the authenticated quota model.

## Day 31: Public Repo Cleanup And README Rebuild

- Rebuilt the public README around the live product:
  - badges
  - Render app link
  - screenshot story
  - sample rendered PDF links
- Added the screenshot and rendered-PDF assets to tracked repo content for GitHub presentation.
- Moved tracked demo resume PDFs under `static/demo_resume/` so demo assets live with the app inputs instead of under old PDF-template docs.
- Re-baselined the roadmap around:
  - finishing the job-application product
  - hardening the current Render-hosted Streamlit stack
  - later FastAPI + Docker backend extraction

## Day 32: FastAPI Job Backend Foundation

- Added an in-repo FastAPI backend skeleton under `backend/` with:
  - `/api/health`
  - `/api/jobs/search`
  - `/api/jobs/resolve`
- Added shared job-search schemas and provider boundaries for backend-owned job discovery.
- Wired the first real provider path through Greenhouse board/job resolution.
- Added deterministic Greenhouse normalization and imported-job review rendering in the JD flow.

## Day 33: Multi-Provider Search And JD Review Expansion

- Added Lever as provider `#2` behind the same adapter contract as Greenhouse.
- Turned `Job Search` into a real backend-powered search surface instead of a placeholder.
- Added recent-first search ordering and stronger role-family matching for technical roles.
- Extended the JD review panel so manual and imported JD flows both render readable summaries before analysis.
- Persisted imported job metadata inside the saved-workspace snapshot so `Reload Workspace` restores the full imported-job context.

## Day 34: Saved Jobs Shortlist And Search UX Polish

- Added a Supabase-backed `saved_jobs` persistence layer for shortlisted jobs.
- Added save/remove actions directly on job-search result cards for authenticated users.
- Added a `Saved Jobs` panel on the Job Search page so shortlisted roles can be revisited and loaded back into the JD workflow later.
- Added deterministic in-card job preview rendering so users can inspect skills, compensation, location, and structured summary before import.
- Polished result-card clarity around remote/location signals and saved-state visibility.
