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

## Day 18 (parallel track): Single-Pass Review-Correction Workflow

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

## Day 18 (parallel track 2): Daily Quotas From Persisted Usage

- Added `src/quota_service.py` to compute per-user daily assisted limits from persisted `usage_events`.
- Extended `src/usage_store.py` with daily usage aggregation for the current UTC day.
- Wired quota checks into `src/openai_service.py` as a preflight hook so assisted requests stop cleanly when the daily cap is exhausted.
- Updated the JD workflow UI to show daily remaining assisted capacity alongside the existing session-level view.
- Added plan-tier daily quota configuration through environment variables for free and paid tiers.

## Day 19 (parallel track 2): Workflow History and Artifact Metadata

- Added `src/history_store.py` to persist authenticated workflow runs and artifact metadata in Supabase Postgres.
- Wired supervised workflow completion to create `workflow_runs` records.
- Wired export preparation to create `artifacts` records for generated PDFs and ZIP bundles.
- Added recent workflow and artifact history to the sidebar account panel.
- Added Supabase schema and RLS setup in `docs/supabase-workflow-history.sql`.

## Day 20 (parallel track 2): History Page and Supabase Bootstrap

- Added a dedicated `History` page in the Streamlit navigation.
- Centralized authenticated history refresh so sign-in and session restore load the same recent workflow and artifact state.
- Added `docs/supabase-bootstrap.sql` as a one-shot setup path for `app_users`, `usage_events`, `workflow_runs`, and `artifacts`.
- Updated README setup guidance to reflect the working Supabase-backed auth, quota, and history path.

## Day 21: Saved-Run Regeneration and History-State Separation

- Extended `workflow_runs` to persist saved reconstruction payloads:
  - `workflow_signature` - `workflow_snapshot_json`
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

## Day 35: Assistant Session Memory And Latency Reduction

- Kept one visible in-app assistant chat while splitting the internal task routing between:
  - lighter product-help questions
  - stronger grounded application-QA questions
- Reduced assistant prompt weight by replacing oversized workflow payloads with a compact package-context summary for application questions.
- Added short-lived assistant session memory on top of the OpenAI Responses API:
  - prewarm assistant context when the panel opens
  - store the latest `response_id`
  - reuse that conversation state for follow-up questions during the same session
- Added assistant session signatures so the app clears stale assistant memory automatically when the relevant workflow context changes.
- Kept the behavior defensive:
  - single chat UX remains unchanged
  - deterministic fallback still works when assisted execution is unavailable
  - clearing chat also clears the short-lived assistant session memory
- Verified the assistant pass with focused assistant-service and assistant-panel tests.

## Day 36: Next.js + FastAPI Re-Baseline

- Completed the architecture migration from the old Streamlit runtime to the live Next.js + FastAPI split stack.
- Removed the retired Streamlit shell, deployment files, and Streamlit-only tests from the active repo.
- Moved the product onto the Vercel frontend plus VPS backend deployment shape.
- Reworked the workspace UI around the real product flow:
  - upload profile
  - search job
  - review job description
  - run the workflow
- Simplified the visible outputs so the workspace now centers on:
  - tailored resume
  - cover letter
- Removed the visible application report from the workspace.
- Removed the strategy stage from the active agentic workflow.
- Simplified resume export to one standard ATS-friendly format and removed the old modern resume theme path from the active backend and frontend.
- Re-baselined the README and architecture docs so they reflect the shipped Vercel + FastAPI product rather than the earlier Streamlit stages.

## Day 37: Workspace "Workbench" Redesign

- Rebuilt the workspace UI as Direction B "Workbench":
  - top bar with brand + ⌘K command-palette trigger + account popover
  - four-step rail (Resume → Job Search → Job Detail → Analysis) with explicit gating and done/active visual states
  - hero band with dynamic per-tab title, sub, and status pill
  - vertical canvas of regions instead of the previous left-sidebar split
  - floating assistant FAB replacing the side-mounted assistant column
- Added a ⌘K command palette overlay for fast navigation between workspace surfaces.
- Pulled all three resume-builder review steps into auto-growing textareas inside collapsible sections so editing long responses no longer scrolls inside a tiny box.
- Reset the resume-builder intake mode on commit and added name-pending fallbacks so the first auto-summary doesn't crash when the LLM hasn't extracted a full name yet.
- Lifted workspace base font sizes and chip / button metrics for readability on standard 1080p displays.
- Capped canvas width and restructured the analysis pipeline grid so the workspace stays comfortable on wide screens; collapsed the resume intake card on parse so the next step gets the focus.
- Tightened the assistant FAB surface (deeper black-blue background + full-width replies) so the chat panel stops fighting the underlying canvas.
- Polished the "honest hero" copy, vertical skills/experience layout, friendlier pipeline labels, empty-state hints, and a next-step pulse.
- Fixed two regressions caught during the redesign:
  - workflow-completion notice no longer leaves the analysis card stuck on "Running"
  - landing "Sign out" button no longer flips to "Signing out…" when the user clicks "Enter workspace"

## Day 38: Atmospheric Polish, Mobile Responsive Pass, And Parser Quality Lift

- De-boxified the editorial document treatment for the Draft profile + JD body: tighter type pairing, removed the per-section card chrome, treated the canvas like one document.
- Atmospheric polish across the workspace — page grain texture, layered surfaces, richer hover and focus states.
- Motion + delight pass: per-region entrance animations, subtle micro-interactions, count-up animations on quota and saved-job stats.
- Replaced the four-button rail with a unified pill nav that ships a progress connector and per-step lock-reason tooltips.
- Single 540px-breakpoint mobile responsive pass covering the topbar, hero, rail, regions, account popover, intake mode toggle, pipeline cards, and chip wrap. Brand text reflows correctly on narrow screens.
- Resume rendering robustness:
  - drop empty resume sections cleanly (Experience can drop for student / early-career profiles, only Certifications drops in the standard case)
  - added Projects + Publications as first-class resume sections; un-clipped page-2 overflow on the PDF render
  - matched the resume PDF + parsed-view typography to the cover-letter family
  - added a switchable `professional_neutral` theme alongside `classic_ats` (Georgia body, neutral grays — pure black/white aesthetic for editorial-leaning profiles)
- Resume parser quality lift:
  - hardened the deterministic resume parser; routed TXT through the LLM hybrid
  - expanded the parser-quality test set from 6 → 15 fixtures across unseen formats
  - simplified the hybrid to a pure LLM source-of-truth with a full deterministic fallback when the LLM is unavailable or schema-fails
  - deterministic polish lifted average from 0.81 → 0.92 across the 15 fixtures
- Added a Tier-2 renderer-fidelity quality runner; fixed a double-escape on experience meta lines along the way.
- JD parser quality lift:
  - Tier-1 baseline: 15 fixtures, deterministic 0.78 average
  - LLM JD parser: 0.78 → 0.99 across the same fixture set
- Added skill canonicalization so Postgres / PostgreSQL synonyms collapse during fit matching — stops the false-negative skill gaps users were seeing.
- Workflow narrowing:
  - removed FitAgent, the application-package report, and the bundle endpoint from the active workflow
  - TailoringAgent battle-test: 0.99 average across 6 (resume, JD) pairs
  - ReviewAgent battle-test: 1.00 LLM, 0.69 deterministic across 6 scenarios
- Per-profile resume section ordering: students lead with Education, academics with Publications, seniors with Experience after Skills. Drives both the HTML and the PDF templates.
- Fixed a resume-builder review-progress bug where a re-uploaded basics block over-captured roles + dropped review progress.

## Day 39: DOCX Export, Conversational Resume Builder, And Cached-Jobs Foundation

- Workspace auth gate: signed-out visitors hitting `/workspace` are now redirected to the landing page; cross-origin host strip mirrors the existing app-subdomain middleware (no new env var).
- Resume-builder durability:
  - 7-day TTL on `resume_builder_sessions` with active-user refresh, mirroring the `saved_workspaces` TTL pattern; cron + RLS expires-at filter both wired
  - tri-state persistence indicator (saved / skipped / unauthenticated) in the field-completeness rail so the user knows whether their progress will survive a reload
- DOCX-first artifact export pipeline (six phases):
  - Phase 1: `python-docx`-based exporter for the `classic_ats` theme; mirrors the existing structured PDF render (header, summary, skills, experience, projects, education, publications, certifications) and honours `artifact.section_order`
  - Phase 2: artifact-export route now dispatches on `pdf | docx`; the markdown branch is removed from `backend/services/artifact_export_service.py`
  - Phase 3: frontend cleanup sweep — removed every Markdown export button, hook, and type; download buttons now offer PDF and DOCX side-by-side
  - Phase 4: `professional_neutral` DOCX theme with a shared palette resolver across PDF and DOCX so both themes read consistently in Word, Google Docs, and the PDF preview
  - Phase 5: `POST /workspace/resume-builder/export` synthesizes a `TailoredResumeArtifact` from the builder session's draft profile (no JD, empty `target_role`, `section_order` from `compute_section_order(candidate_profile)`); auth-gated like the other resume-builder routes
  - Phase 6: download row UI under "Generate base resume" — theme picker + Download PDF / Download DOCX
- Conversational LLM resume builder:
  - shipped the 14-item punch list (DB migrations, lazy-load, thread-bound state, all three battle tests, adversarial coverage, signature hash, dead-code cleanup)
  - end-to-end LLM chat: 5/8 fields extracted in one turn, backtracking works, 100% completion on the smoke fixture; "Generate base resume" produces clean DOCX/PDF
  - workspace chat-bubble experiment shipped + reverted; transcript style retained as the chosen direction
- Resume-builder content quality:
  - LLM-first structuring pass with a deterministic regex fallback, plus header alignment so the rendered name matches the structured schema
  - skills are bucketed into named categories (`Languages & Tools`, `ML/DL Frameworks`, etc.) so the rendered resume groups skills by family instead of a flat pipe-separated list
  - structuring output cached across exports + persistence so re-rendering doesn't re-run the LLM
  - recovers a full name when the LLM intake drops a surname mid-conversation
  - thin one-liner summaries get expanded to full paragraphs by the structuring pass; bumped the structuring model + token budget for the expanded contract
  - Projects + Publications sections rendered through the same Draft profile / DOCX / PDF path as Experience
  - Tier-3 quality runner for the resume-builder structuring pass
- ResumeGenerationAgent battle-test: LLM 1.00, deterministic 0.94 across 6 (resume, JD) pairs.
- CoverLetterAgent battle-test: LLM 0.97, deterministic 0.95 across 6 pairs.
- Cached-jobs foundation (Phases 2 + 3 of the seven-phase plan):
  - Phase 2: `cached_jobs` Supabase table + `refresh_cached_jobs` worker; `POST /admin/refresh-cache` endpoint protected by a constant-time bearer compare. Worker bulk-upserts every Greenhouse + Lever posting and runs the smart cleanup (tombstone if a user has saved the listing, hard-delete otherwise) per source — only sources whose refresh actually succeeded are eligible for cleanup.
  - Phase 3: `/jobs/search` defaults to the cached path through `JobSearchService.search_cached(...)`; `?live=true` keeps a live-fan-out escape hatch for diagnostics. Surfaces `cache: ok | not_configured | error` in `source_status` so monitoring can see when the cache misses.

## Day 40: Multi-ATS Coverage, Postgres-RPC Ranked Search, And Dropdown Filters

- Phase 4: bumped the source pool to ~117 Greenhouse boards + 30 Lever sites and validated the slug list against the live APIs. First refresh after deploy hits the cache rather than every user paying the live fan-out cost.
- Phase 5: enabled `pg_net` in the Supabase project + documented the cron schedule that POSTs to `/admin/refresh-cache` every ~30 min (committed under `docs/job_cache_cron_setup.sql`). Frontend gets an "Expired" badge on saved-job cards whose listings the cleanup pass has tombstoned.
- Phase 5b: relevance-ranked cache search via a new Supabase RPC (`search_cached_jobs_ranked`):
  - PostgREST's `text_search()` chain returns a terminating builder that doesn't compose with `.order()`, so a single round-trip ranked search needs a function. The RPC owns the FTS + filter + sort logic and `CachedJobsStore.search()` calls it with a stable kwarg dict.
  - Warm cache: ~360 ms; cold: ~5.5 s; vs ~25 s for the live fan-out — the cache layer paid for itself on the first user query.
  - Post-flight fixes for cleanup eligibility and the report shape.
- Phase 6: re-validated and expanded the source list — final Greenhouse pool of 79 verified boards + Ashby adapter (36 boards). Composite job IDs (`source:tenant:job_id`) avoid cross-tenant collisions when one company runs multiple Ashby boards.
- Phase 7: Workday adapter for 11 Fortune 500 tenants (NVIDIA, Adobe, Walmart, Disney, HP, HPE, Boeing, Citi, Micron, BlackRock, Workday itself). Per-board page delay + reduced concurrency to stay under the anti-bot threshold; production cadence (one refresh per ~30 min) sits well below the rate limit. Fixed a status-reporting bug along the way: an all-failed provider used to land in the report as `status: ok` because the only path that set status away from `ok` assumed `boards_succeeded > 0`.
- Phase 8: dropdown filters + sort for job search:
  - schema: `work_mode` and `employment_type_norm` GENERATED STORED columns on `cached_jobs` (with partial indexes on `removed_at IS NULL`); intern detection uses Postgres word-boundary regex (`\mintern(s|ship|ships)?\M`) so "Internal" / "International" don't false-match
  - RPC v2: extends `search_cached_jobs_ranked` with `p_work_modes`, `p_employment_types`, `p_sort_by`; ORDER BY branches on the sort key (`relevance` → `ts_rank` when there's a query else recency, `newest` → `posted_at DESC`, `oldest` → `posted_at ASC`, `company_az` → `LOWER(company)`)
  - Python plumbing: `JobSearchQuery` + `JobSearchRequestModel` + `CachedJobsStore.search()` extended with the new args; Pydantic validators normalize input + coerce unknown sort values to `relevance`
  - Frontend: replaced the lone "Remote only" checkbox with five dropdowns — Source / Work mode / Type (multi-select), Posted within (single-select, retained), Sort (single-select, new). Multi-select chips built on native `<details>`/`<summary>` for keyboard accessibility plus an extra `mousedown` outside-click + `Escape` dismiss handler so the popover behaves like a native menu.
  - Verified end-to-end against the live cache: filtering by Source = greenhouse + lever, Work mode = remote, Sort = company A → Z returned 12 alphabetically-sorted Pinterest-then-Affirm matches, all remote-friendly.
- Total active cache after Day 40: ~11,877 jobs across four ATS providers.

## Day 41: Landing Polish, Independent Step Navigation, Assistant State-Awareness, And Multi-Layer LLM Retry

### Landing redesign — final polish pass

- Workbench scroll narrative iteration: shrunk the sticky visual stage from a stretched 480 × 853 to a square 480 × 480 (aspect-ratio 1/1) with center-pinning so empty space inside the stage stops at ~60–100 px instead of the previous 300+ px.
- Each of the four mock cards now mirrors the real workspace page rather than a generic data card:
  - Step 01 Resume: parsed-profile hero (Aria Patel · Staff ML Engineer · San Francisco) + 3-up stats grid (12 roles · 27 skills · 9 yrs) + skills chip cluster + filename pill with a green `PARSED` tag.
  - Step 02 Job Search: search bar with location, four filter chips, "47 MATCHES · BY RELEVANCE" header, three result cards with a gold "★ TOP MATCH" badge on the leader.
  - Step 03 JD: three big metric tiles (Match score 87%, Hard skills 12, Years 5+) with a blue-tinted accent on the match-score card, plus hard/soft skills chip rows.
  - Step 04 Analysis: four agent pipeline cards (Matchmaker ✓, Forge ✓, Gatekeeper running 62% with progress bar, Cover letter agent ○ standby).
- Step text is now `justify-content: center` inside each 48vh block so step 01 reads at viewport center on first scroll-in, aligning with the centered visual stage.
- Bento carousel tiles + workbench mock card surface dropped the previous blue corner-glow radial in favor of a flat `rgba(0, 0, 0, 0.40)` overlay that matches the workspace's `.b-jd-block` treatment — landing and workspace now read as one surface family.
- Topbar consolidated to `Workflow · Features · [Auth]` — dropped the third GitHub link (already covered by the hero CTA + footer link).
- Extracted the landing page into a design-system reference at `frontend_redesign/redesign/landing/` (README + 5 specs covering chrome, hero, workbench, bento, final CTA) — peer to the existing workspace `handoff/` so future passes have a same-shape context bundle.

### Independent step navigation in the workspace

- Removed the resume-parse gate on Job Search and Job Detail. A user can now paste a JD they're curious about before they have a resume, or browse listings without uploading anything. The "Upload a resume to unlock" tooltips on the rail are gone.
- Only Analysis stays gated (it can't run without both inputs). The page-level "Upload a resume to proceed" affordance inside `AnalysisRunner.tsx` already enforces this honestly.
- Cleaned up the now-dead "Upload a resume first" fallback `sub` text on the `nav-jobs` and `nav-jd` command-palette entries.

### Assistant chat — ungated and state-aware

- Removed the analysis-required gate that locked the assistant chat until a workspace had been analyzed. Users can now ask product-help questions ("how do I use this?", "what's step 03 for?") from the very first visit.
  - Three gates lifted in one pass: the panel's footer "Assistant unlocks after your first workspace run" lockup, the `submitAssistantQuestion` early-return + warning notice, and the `assistantUnlocked` prop on the command palette (now always true).
  - Renamed the cosmetic prop from `requiresWorkspaceRun` → `hasWorkspaceContext` so the panel adapts copy (header sub, empty state, textarea placeholder) based on whether a workspace exists, not whether the chat is locked.
- Added a `WorkspaceStateContext` projection that rides on every assistant query — `current_step`, `has_resume`, small `resume_summary`, `has_jd`, small `jd_summary`, `has_analysis`, `saved_jobs_count`, `last_search_query`. Counts only, no raw resume text. Backend's `WorkspaceStateContextModel` validates it; service layer folds it into the `app_context` dict that reaches `AssistantService`.
- Added a 9-rule `_WORKSPACE_STATE_GUIDANCE` block to both the JSON-contract (`build_assistant_prompt`) and the streaming prose (`build_assistant_text_prompt`) system prompts so the LLM knows the shape of the new field, the step-number mapping (01=Resume, 02=Job Search, 03=Job Detail, 04=Analysis), the auth contract (signed-out users get redirected to landing — there's no "use feature X without signing in" answer), and the field semantics (e.g. `experience_entries_count` is the count of jobs held, NOT years).
- Battle-tested across three personas (cold start / mid-flow / ready-to-run) over three rounds:
  - Round 1: 22/24 passes; surfaced two bugs (entry-count read as years, step-03 mismatch).
  - Round 2: 13/15 passes after the first two fixes; surfaced a product-knowledge gap (the "assistant builder" mode wasn't in the retrieval index) and a "yes you can analyze signed-out" mistake.
  - Round 3: 12/12 passes after refreshing `src/product_knowledge.py` to ground truth (12 documents covering auth, the 4-step flow, resume intake modes, all four ATS sources, supervised pipeline agents, exports, saved workspace, command palette, the assistant FAB, cover letter, quotas).
  - Combined: 47/51 (92%) with 0 outstanding correctness failures.

### LLM resilience — three-layer retry stack + per-agent fallback isolation

The orchestrator's previous behavior was all-or-nothing: any single agent failure (after the SDK's built-in retries) cascaded to "downgrade the WHOLE pipeline to deterministic." A single bad packet during the Forge agent meant Gatekeeper, Builder, and Cover letter all ran deterministic too. Reworked the resilience layer:

- **Layer 1 (existing):** OpenAI Python SDK retries up to 2 times on transient HTTP / 5xx / 429-with-Retry-After (we set `max_retries=2` on the client).
- **Layer 2 (new):** App-level retry on top of the SDK. After the SDK exhausts its 2, we try ONE more time on a tight allow-list — `APIConnectionError`, `APITimeoutError`, `InternalServerError`. NOT for 4xx / auth / persistent rate-limit / content-policy (deterministic problems). 400 ms delay between attempts. New `openai_request_app_retry` log event for production observability.
- **Layer 3 (new):** Per-agent retry inside the orchestrator. If an agent's `.run(...)` raises `AgentExecutionError` (e.g. all OpenAI-call retries exhausted, or the response was semantically broken even after the existing budget retry), we wait 400 ms and retry that agent's full run once. Only fires in `mode="openai"`; no-op in deterministic.
- **Per-agent fallback isolation (new):** When an agent's two LLM attempts both fail, the orchestrator runs that agent's deterministic fallback (via `AgentClass(None).run(...)`) for THAT agent only — downstream agents still try the LLM path. Forge failing no longer affects Gatekeeper.
  - Each call site now passes a `deterministic_fallback_runner` lambda alongside the assisted runner.
  - The whole-pipeline fallback is now a safety net that fires only if a per-agent deterministic fallback ITSELF errors out (very unusual — would mean our own deterministic code is broken).
  - Added a mode-reconciliation pass: if a pipeline started as `mode="openai"` but every agent ended up falling back per-agent (zero LLM successes), `result.mode` flips honestly to `deterministic_fallback` and the first LLM error's user_message becomes the `fallback_reason`.

Worst-case retry budget for a transient failure: SDK 2 + app 1 + per-agent 1 = up to 4 effective LLM attempts before an agent gives up. After that, that agent's deterministic fallback runs and the rest of the pipeline keeps using the LLM.

Coverage check: every `responses.create` call in the codebase routes through the new `_create_response_with_app_retry` helper now (`run_json_prompt`, `run_text_stream`, and the existing output-budget retry helper). By extension, the resume parser, JD parser, JD summary, all four workflow agents, AND the assistant chat all inherit the new retry layer for free.

Tests: 17 new resilience tests pin the contracts —
- 9 in `tests/test_openai_app_retry.py`: retries on the 3 allow-listed types, does NOT retry on 4xx/auth, returns success after retry, raises on double-failure.
- 8 in `tests/test_orchestrator.py` (5 existing + 3 new): per-agent retry recovers, per-agent fallback isolates a single failing agent, full-pipeline mode flips to deterministic when no agent succeeded with LLM.

### ADRs added

- [ADR-017: Workspace assistant — ungated + state-aware context](docs/adr/ADR-017-workspace-assistant-state-aware-context.md)
- [ADR-018: Three-layer LLM retry + per-agent fallback isolation](docs/adr/ADR-018-three-layer-llm-retry-and-per-agent-fallback-isolation.md)
- [ADR-019: Independent step navigation in the workspace](docs/adr/ADR-019-independent-step-navigation.md)

## Day 42: Tier Enforcement — Quota Counters, Caps, And Premium Model Routing

Eight-step series shipped across `feat/tier-enforcement` and merged + deployed (commits `ff2fe2d` through `0ede6ea`). Until now the product had a single `usage_events` daily-quota path inherited from the Streamlit era — a per-day cap on assisted requests with no notion of subscription tiers, no per-action gating, and no separate premium pathway. Day 42 lands the full tier-enforcement matrix end-to-end. Today every quota gate routes through one cap table; payments will land in a separate week (see Day 43) and flip a single function body.

### Eight logical steps

1. **Tier shim + cap matrix** (`ff2fe2d`) — `backend/tiers.py` introduces `resolve_user_tier(app_user) -> Literal["free", "pro", "business"]` (returns `"free"` for everyone today, the single function body to swap once subscriptions go live) and the `TIER_CAPS` table covering eight counters: `tailored_applications`, `premium_applications`, `resume_builder_sessions`, `assistant_turns`, `resume_parses`, `job_searches`, `saved_jobs`, `saved_workspaces`. `UNLIMITED = -1` is the no-cap sentinel.
2. **Atomic check-and-increment** (`b2a4947`) — `aijobagent_quota_counters` table + `increment_aijobagent_counter` RPC in `docs/sql/supabase-quota-counters.sql`. The RPC does INSERT-ON-CONFLICT inside `FOR UPDATE`, raises SQLSTATE `P0001` with detail `aijobagent_quota_exceeded` on overrun. `backend/quota.py::check_and_increment` translates the P0001 into `QuotaExceededError`, surfaced as a uniform 429 via the single global handler in `backend/app.py`. Concurrent workspace runs from the same user produce N+1 and N+2 — never both N+1. Refund-on-failure (`backend.quota.refund`) decrements by 1 (floored at zero) from the workflow-failure path so a transient orchestrator error doesn't burn a credit.
3. **Workspace gates: tailored + premium applications** (`6e893e6`) — both counters wired at `/workspace/analyze`. Free-tier premium=True is rejected with a tier-specific message ("Premium applications are a Pro+ feature.") before any agent runs.
4. **Workspace gates: assistant turns + resume parses + resume-builder sessions** (`2dc76cd`) — three more gates with a special case: `assistant_turns` is gated on the streaming SSE path *and* the non-streaming JSON path separately so SSE clients can't sneak past by reconnecting mid-flight. `resume_builder_sessions` uses the new `lifetime=True` kwarg on Free (lifetime period_key, cap 1) and the standard monthly partition on Pro/Business (cap 3 / 15).
5. **Search + saved gates with persistent row-count counters** (`d249b28`) — `job_searches` (monthly) plus `saved_jobs` and `saved_workspaces` (persistent caps backed by the corresponding store's row count, not the counter table). The persistent counters bypass `check_and_increment` entirely on the read path; `/workspace/quota` reads row counts directly from `SavedJobsStore` / `SavedWorkspaceStore`.
6. **Tier-aware model routing** (`68be1d5`) — `backend/model_routing.py::select_workflow_model` returns `gpt-5.5` for `review` / `resume_generation` / `cover_letter` when `(premium=True, tier in {pro, business})` and `None` (= use the standard `OPENAI_MODEL_ROUTING[task]`) otherwise. Tailoring stays on `gpt-5.4-mini` regardless — COGS analysis pinned the upgrade to the three "high-trust" agents only, and keeping tailoring on mini is the difference between premium being sustainable and not.
7. **`/workspace/quota` endpoint + frontend Premium toggle** (`24a1840`) — read-only snapshot for the eight counters plus an `upgrade_url` field driven by `AIJOBAGENT_UPGRADE_URL`. Frontend renders a Premium toggle that's disabled+tooltip on Free without a second lookup (`premium_available` is True only on tiers with `premium_applications > 0`).
8. **Tier-aware saved-workspace retention sweeper** (`c57d658`, `0ede6ea`) — `backend/maintenance.py::sweep_expired_workspaces` deletes rows older than `retention_days_for_tier(tier)` (Free 7, Pro 30, Business None = unbounded). Replaces the legacy unconditional 24-hour sweeper that Supabase pg_cron had been calling. The supabase migration drops the legacy SQL function and hardens RPC grants so only `service_role` can call `increment_aijobagent_counter` (granting EXECUTE to `authenticated` would have let any signed-in user burn another user's quota by passing their UUID).

### Tests

99 new tier-enforcement tests across `tests/backend/test_tiers.py`, `test_quota.py`, `test_workspace_quota_enforcement.py`, `test_assistant_quota_enforcement.py`, `test_resume_quota_enforcement.py`, `test_search_and_saved_quota_enforcement.py`, `test_tier_aware_workflow_model.py`, `test_workspace_quota_snapshot.py`, `test_workspace_retention.py`. Includes refund-on-failure recovery, atomic concurrency under thread races, lifetime-vs-monthly period switching, P0001 → 429 translation, and Business `None`-retention skip behaviour.

### Deploy status

Merged to `main` and deployed end-to-end. Quota gates are live; every user currently resolves to `free` until the payment cutover.

### ADRs added

- [ADR-020: Tier resolution via a single shim function](docs/adr/ADR-020-tier-resolution-via-single-shim-function.md)
- [ADR-021: Atomic quota with refund-on-failure](docs/adr/ADR-021-atomic-quota-with-refund-on-failure.md)
- [ADR-022: Tier-aware model selection via constructor injection](docs/adr/ADR-022-tier-aware-model-selection-via-constructor-injection.md)

## Day 43: Lemon Squeezy Payment Scaffold (Awaiting Variant IDs)

Four commits on `feat/lemonsqueezy-integration` wire the end-to-end paid-tier path on top of the Day 42 enforcement layer. Ready to ship — only waiting on the LS dashboard's final Pro / Business variant IDs to flip live. Until then, every code path stays env-gated behind a "Coming soon" fallback so the production frontend keeps shipping without holding the LS account hostage.

### Four commits

1. **Subscriptions table + tier resolution swap** (`1b8cf95`) — `aijobagent_subscriptions` table holds one row per active or past subscription (`user_id`, `processor`, `processor_subscription_id`, `tier`, `status`, `current_period_end`, `created_at`, `updated_at`) with a partial unique index on `(user_id) WHERE status = 'active'` so a user has at most one active sub. `backend/subscriptions.py` is the thin store wrapper. Crucially, the body of `backend/tiers.py::resolve_user_tier` is updated to consult this store: if an active subscription exists whose `current_period_end > now()`, return its `tier`; else return `"free"`. **This is the one-function change that ADR-020 promised.** Every existing quota gate flips from gating Free to gating the user's real tier with zero call-site churn.
2. **HMAC-verified webhook endpoint** (`c3c3348`) — `POST /api/webhooks/lemonsqueezy` parses the LS event, verifies the HMAC-SHA256 signature from the `X-Signature` header against `LEMONSQUEEZY_WEBHOOK_SECRET` using `hmac.compare_digest`, and routes by `meta.event_name` to the subscription store: `subscription_created` / `subscription_updated` upsert by `processor_subscription_id`, `subscription_payment_success` bumps `current_period_end`, `subscription_cancelled` / `subscription_expired` mark `status = 'cancelled'` or `'expired'`. The variant_id → tier mapping reads from `LEMONSQUEEZY_VARIANT_PRO` / `LEMONSQUEEZY_VARIANT_BUSINESS`; unknown variants log a warning and 200-OK (LS retries 4xx, so silent ack on unknown variants prevents stuck retry loops on misconfiguration).
3. **Frontend Upgrade CTA + customer portal link** (`c3a80ea`) — the Premium toggle's "Upgrade" CTA now opens the LS hosted checkout for the relevant variant when `NEXT_PUBLIC_LEMONSQUEEZY_*` env vars are set; falls back to a "Coming soon" disabled-button-plus-tooltip when they're not. Customer portal link in the account popover routes to `customer.lemonsqueezy.com/billing/{customer_id}` for active subscribers (read from `aijobagent_subscriptions.processor_customer_id`).
4. **Env vars + setup walkthrough** (`a236c81`) — `.env.example` entries for `LEMONSQUEEZY_WEBHOOK_SECRET`, `LEMONSQUEEZY_STORE_ID`, `LEMONSQUEEZY_VARIANT_PRO`, `LEMONSQUEEZY_VARIANT_BUSINESS`, `NEXT_PUBLIC_LEMONSQUEEZY_STORE_ID`, `NEXT_PUBLIC_LEMONSQUEEZY_VARIANT_PRO`, `NEXT_PUBLIC_LEMONSQUEEZY_VARIANT_BUSINESS`. `docs/lemon-squeezy.md` walks through the LS dashboard setup (store creation, two variant rows, webhook URL pointed at `api.job-application-copilot.xyz/api/webhooks/lemonsqueezy`, secret rotation procedure) plus the Supabase migration step.

### Architectural neutrality

`aijobagent_subscriptions.processor` is a text column, not a Lemon Squeezy-specific enum. When a future Stripe + Razorpay path lands (see ADR-023), the same store handles both — each processor writes its own row, `resolve_user_tier` picks the row with the highest active tier. No table migration needed at processor #2.

### Deploy status

Branch is local; commits not yet pushed. Going live needs three things — the two LS dashboard variant IDs, the webhook secret pasted into the VPS env, and the `aijobagent_subscriptions` migration applied to the prod Supabase project. After that, removing the env-gated fallback in the frontend is a one-line change.

### ADRs added

- [ADR-023: Lemon Squeezy as Merchant of Record for v1](docs/adr/ADR-023-lemon-squeezy-merchant-of-record-for-v1.md)

## Day 44: Schema-Strict Outputs, Nightly Eval CLI, Cost Tracking, And Codex Review Fixes

A pre-PR batch of 10 commits landed straight to `main` on 2026-05-15 to harden the LLM-output contract layer, wire a production-grade nightly quality eval, attribute per-call OpenAI cost to a persistent table, and resolve the P1/P2 findings from Codex's review of the Day 42-43 chain.

### Schema-strict LLM outputs

- **Pydantic output models for all 9 LLM-producing agents** (`ce92097`) — every agent that produces structured output now defines a `*Output` Pydantic model in `src/schemas.py`. The 9 agents: resume parser, JD parser, JD summary, tailoring, review, resume generation, cover letter, resume builder, assistant grounded-mode. Schemas are reused as the JSON-mode contract argument and as the parsed return type.
- **`run_structured_prompt` + 6 agent migrations** (`4cad3d7`) — new helper in `src/openai_service.py` that wraps `run_json_prompt` with a typed parse step. Returns `(parsed_pydantic_object, usage_metadata)` instead of a free-form dict. Six agents migrated: resume parser, JD parser, JD summary, tailoring, review, resume generation. The other 3 (cover letter, resume builder, assistant) already had their own custom parse paths and stayed on `run_json_prompt`.

### Nightly eval CLI

- **`backend/nightly_eval.py` CLI + ops doc cron entry** (`1f2aeb6`) — single CLI wraps the 5 quality runners (`resume_parser`, `jd_parser`, `tailoring`, `review`, `orchestrator_e2e`) with regression-threshold checking against a baseline JSON. Default deterministic-only mode is free; `--include-llm` opts into the ~$0.25-per-run full-LLM path. Documented under `docs/operations.md` with both a free deterministic cron and a paid LLM cron. The `--include-llm` flag is **not** added to the production crontab — that mode is reserved for deliberate ad-hoc operator runs after observed drift, because $0.25 × 30 nights = $7.50/mo recurring cost with no users yet to absorb it. See [ADR-026](docs/adr/ADR-026-manual-only-nightly-eval-at-pre-revenue-stage.md).
- **Runner signature fixup** (`9e83cf8`) — `openai_service.run_text_stream` had a kwarg-only `_progress_callback` that didn't match the position of the call site after the schema-strict refactor. Two-line patch to the runner shim.

### Cost tracking

- **`aijobagent_run_traces` table + `record_trace` helper** (`043304b`) — append-only table holds one row per LLM call: `user_id`, `model`, `task`, `prompt_tokens`, `completion_tokens`, `cost_usd`, `created_at`. Best-effort writes — runtime tolerates a missing table or a write-path error so the user-facing path never blocks on observability.
- **`openai_service` cost computation + trace integration** (`3977af6`) — every `responses.create` in the codebase now computes a USD cost from `_MODEL_PRICING_USD_PER_MILLION` and emits a `record_trace(...)` call. Pricing map covers GPT-5-mini, GPT-5.4-mini, GPT-5.5, transcribe-mini. When OpenAI changes a price, both the map and the README pricing reference need updating.

### Codex review fixes

Three security/correctness P1+P2 findings from the Codex review on the Day 42-43 chain:

1. **Free saved_workspace upsert allowed** (`48a6f6b`) — Codex P1. The Day 42 retention sweeper was correctly Free-7d-aware, but `/workspace/save` was returning 429 on the very first save for a Free user because the persistent-row-count check ran before the retention sweep had cleaned the prior row. Reordered: sweep first, then check count.
2. **Access cookie lifetime aligned to refresh cookie** (`5494630`) — Codex P1. The access cookie was being set with a shorter `Max-Age` than the refresh cookie, so on browsers with strict cookie pruning the access cookie could die before the refresh cookie did, breaking the refresh flow. Aligned to the same TTL.
3. **Removed cross-user PKCE flow fallback** (`b8fb594`) — Codex P2. A defensive fallback in the PKCE flow was searching for *any* matching code_verifier when the per-user one failed lookup. That was always paranoid and Codex flagged it as a privilege-escalation footgun — removed.

Also: **`f23b273` Fix LS hosted checkout URL path** — the LS checkout URL builder was emitting `/buy/<variant>` but the actual LS path is `/checkout/buy/<variant>`. One-line fix; caught in manual smoke before any user hit it.

### Deploy status

All 10 commits merged + deployed end-to-end. Nightly eval cron is documented but **intentionally not installed** in production yet (see [ADR-026](docs/adr/ADR-026-manual-only-nightly-eval-at-pre-revenue-stage.md)).

### ADRs added

- [ADR-026: Manual-only nightly eval at pre-revenue stage](docs/adr/ADR-026-manual-only-nightly-eval-at-pre-revenue-stage.md)

## Day 45: UX Pack Wave 2 — Voice, Feedback, And The Prompt Registry Migration

Two PRs (#3 + #4) shipped on 2026-05-15, completing the second wave of workspace UX polish kicked off at Day 41. The headline additions are voice input on every text field, a thumbs-up/down + free-form feedback widget on every workflow artifact, and a full migration of every LLM prompt builder into a versioned JSON registry.

### PR #3: voice + feedback + first 4 prompt builders (`e8cd3e5`)

28 files changed, 3786 / 72 (insert/delete) lines. Six review rounds, 597 / 597 tests pass.

- **Voice input** — `POST /workspace/transcribe` proxies a multipart audio upload through OpenAI's `gpt-5-mini-transcribe`, returns text only. The `VoiceInputButton` React component records via the browser's `MediaRecorder` API (16kHz mono webm/opus by default), shows a recording indicator + live level meter, and pipes the transcribed text back into whatever input field it's mounted on. Wired into the JD textarea, the resume-builder chat input, and the assistant input. Caps at 60 seconds per recording (frontend-enforced + backend-rejected on overrun).
- **Artifact feedback** — `POST /workspace/feedback` and `aijobagent_feedback` Supabase table (`user_id`, `workspace_id`, `artifact_kind`, `rating`, `comment`, `created_at`). The `FeedbackButtons` component renders thumbs-up/thumbs-down next to every tailored-resume / cover-letter / assistant-reply artifact. Thumbs-down opens an optional comment textarea. RLS is `user_id = auth.uid()` on both read and write; admin queries go through service-role.
- **Prompt registry (4 of 10 builders migrated)** — `backend/prompt_registry.py` introduces `load_prompt(name, version="v1") -> PromptDefinition` reading from `prompts/<name>/<version>.json`. Each JSON file holds `template`, `variables` (Pydantic schema for the inputs), `description`, and optional `examples`. Four builders migrated in this PR: `tailoring`, `review`, `resume_generation`, `cover_letter`. Each migration ships with a byte-identity test in `tests/test_prompts.py` that asserts the registry-built string is bit-exact to the original Python concat.

### PR #4: prompt registry batch 2 — remaining 7 builders (`17afdfb`)

Migrated the final 7 builders: `assistant`, `assistant_followup`, `assistant_text`, `resume_builder`, `resume_builder_structuring`, and the two parser prompts. After this PR every LLM call in the codebase loads its prompt from `prompts/<name>/v1.json`. `src/prompts.py` is now a thin pass-through registering each name with the registry; the actual templates live in `prompts/`.

14 byte-identity tests in `tests/test_prompts.py` guard each migrated JSON against drift from the original Python concat. CodeRabbit had no actionable comments on the migration PR.

### Why the registry

The registry pays for itself in three places, all imminent:

1. **A/B testing prompts.** With the prompt being a JSON file rather than a Python string concat, swapping `v1` → `v2` is a config change. The current product can already pick the version via env (`AIJOBAGENT_PROMPT_VERSION_TAILORING=v2`), even though no v2's are in flight yet.
2. **Versioning across model upgrades.** When the codebase moves from GPT-5.4-mini to GPT-6 (or any other model with different prompt-engineering best-practices), the old `v1.json` stays pinned to the old model while `v2.json` ships for the new one. No big-bang flip.
3. **Prompt review by non-coders.** A `.json` template is reviewable by anyone who can read JSON — the prompts no longer hide inside `src/prompts.py` as f-strings nested in helper functions.

### Hotfix: `python-multipart` + CI lockfile guard

The `/workspace/transcribe` route relies on FastAPI's `File(...)` parameter, which needs `python-multipart` as a runtime dep. The PR #3 merge missed adding it to `pyproject.toml`, the test suite passed (FastAPI's `TestClient` has its own multipart handling), and the production deploy crashed on the first multipart request.

- **Hotfix: regenerate uv.lock to include python-multipart** (`618bf58`) — added the missing dep and regenerated `uv.lock`.
- **CI: fail fast when uv.lock drifts from pyproject.toml** (`05e987e`) — added a `uv lock --locked` check to the CI workflow. If `uv.lock` doesn't match `pyproject.toml`, CI fails before deploy. Catches this class of mistake before it reaches production.

### Deploy status

Both PRs merged + deployed. 597 → 611 backend tests; frontend lint green.

## Day 46: Observability Stack — Sentry + PostHog + EU Cookie Consent Banner

PR #5 (`4e29b5a`) — 22 files changed, 4791 / 69 lines. Mirrors the HelpmateAI observability stack (which landed the same day for the sibling product). One Sentry org `leander-antony-a` now owns four projects: `helpmate-backend`, `helpmate-frontend`, `jobagent-backend`, `jobagent-frontend`. PostHog stays on the Developer free plan with a single project shared across both products, distinguished by a `product: "jobagent"` super-property on every event.

### Sentry: jobagent-backend + jobagent-frontend

- **`backend/observability.py`** is the single bootstrap module called from `backend/app.py` before `FastAPI()` is constructed (so the Sentry ASGI middleware wraps the app at startup, not as a late add-on). Backend integrations: `FastApiIntegration`, `StarletteIntegration`, `LoggingIntegration`, `OpenAIIntegration(include_prompts=False)` for AI Agents Monitoring without PII exposure. The `_running_under_pytest()` guard skips Sentry init entirely during the test suite. The `before_send` hook drops intentional `HTTPException` 4xx flow-control and the "service not configured / temporarily unavailable" 5xx guards so the issue feed stays focused on real bugs.
- **Frontend wiring** — `instrumentation-client.ts`, `instrumentation.ts`, `sentry.server.config.ts`, `sentry.edge.config.ts`. The client-side `buildIntegrations(consent)` helper returns the always-on integrations (`feedbackIntegration` — legitimate interest) when consent is anything other than `"accepted"`, and adds `replayIntegration({maskAllText: false, blockAllMedia: true})` only when consent is `"accepted"`. The `Sentry.addIntegration(...)` API lets a user who later flips consent get Replay added without a page reload.
- **Free-tier-maxed configuration** — `tracesSampleRate=0.1`, `profilesSampleRate=0.05`, `replaysSessionSampleRate=0`, `replaysOnErrorSampleRate=1.0`, `enableLogs=true`. The 0% ambient replay sampling avoids competing with PostHog's session replay (PostHog handles ambient sampling; Sentry handles errored-session-only coverage).
- **Source-map upload** — `withSentryConfig(...)` in `next.config.ts` reads `SENTRY_AUTH_TOKEN`. The Sentry-Vercel marketplace integration's env-var-upsert step failed mid-install (it found a previously-set `NEXT_PUBLIC_SENTRY_DSN` and refused to upsert), so the manual env-var path was used instead. Both achieve the same source-map upload behavior; only the auto-created release markers per Vercel deploy are missing from the manual path (those can be backfilled via `VERCEL_GIT_COMMIT_SHA` if needed later).
- **Code mappings** — both `jobagent-backend` and `jobagent-frontend` have stack-trace-to-GitHub-source-line deep links configured via the Sentry GitHub integration (paths `backend/` + `src/` for backend, `frontend/src/` for frontend, branch `main`).

### PostHog: shared project + `product: "jobagent"` tag

The Developer free plan caps at 1 project per org. The HelpmateAI integration landed its `posthog-provider.tsx` first; this PR shares the same project and distinguishes by tagging every event with `product: "jobagent"` via `posthog.register({product: "jobagent"})` at init. Backend events go through `backend/observability.py::capture_event(...)` which merges the same tag in. Dashboards filter on `where properties.product = 'jobagent'` to stay cleanly product-scoped.

PostHog config: autocapture on, `maskAllInputs: true` for replay, heatmaps on, surveys on, **exception capture off** (Sentry is the source of truth for errors — letting both vendors collect them double-bills the free-tier quotas).

### EU cookie consent banner

The single banner in `frontend/src/components/cookie-consent.tsx` is the GDPR-compliance surface. localStorage key `jobagent-cookie-consent` is the source of truth with three states: `"pending"` (first visit), `"accepted"`, `"declined"`. A custom event `jobagent-cookie-consent-change` re-evaluates consent-gated integrations on flip without a page reload. CSS class prefix `.ja-cookie-banner` so it can't visually collide with the sibling HelpmateAI banner if a developer runs both products against the same `localhost`.

Legal split: **always-on** = Sentry errors + traces + Feedback widget (legitimate interest under GDPR Art. 6(1)(f) — operationally necessary). **Consent-gated** = PostHog product analytics + PostHog session replay + Sentry Session Replay (require explicit opt-in per ePrivacy Art. 5(3)).

### Uptime monitor

Sentry's Uptime monitor pings `https://api.job-application-copilot.xyz/health` every 5 minutes from the EU region. The same monitor pattern the HelpmateAI deploy uses.

### Tests

8 lines moved in `tests/test_error_messages.py` — a leaky-detail allowlist needed a small line-drift adjustment after `backend/observability.py` was inserted between earlier modules. The `_running_under_pytest()` skip means Sentry never fires during the test run, so this was the only test churn.

### Deploy status

Merged + deployed. Backend container restarted on the VPS; Vercel auto-rebuilt the frontend. Source-maps uploading on every Vercel deploy. Uptime monitor returning green within 2 minutes of deploy.

### ADRs added

- [ADR-024: Observability stack — Sentry + PostHog with consent-gated analytics](docs/adr/ADR-024-observability-stack-sentry-and-posthog.md)
- [ADR-025: EU cookie consent banner + GDPR-aligned analytics gating](docs/adr/ADR-025-eu-cookie-consent-banner-and-gdpr-analytics-gating.md)
