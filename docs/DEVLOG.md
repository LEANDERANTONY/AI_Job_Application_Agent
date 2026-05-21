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

- **`backend/nightly_eval.py` CLI + ops doc cron entry** (`1f2aeb6`) — single CLI wraps the 5 quality runners (`resume_parser`, `jd_parser`, `tailoring`, `review`, `orchestrator_e2e`) with regression-threshold checking against a baseline JSON. Default deterministic-only mode is free; `--include-llm` opts into the ~$0.25-per-run full-LLM path. Documented under `docs/deployment.md` with both a free deterministic cron and a paid LLM cron. The `--include-llm` flag is **not** added to the production crontab — that mode is reserved for deliberate ad-hoc operator runs after observed drift, because $0.25 × 30 nights = $7.50/mo recurring cost with no users yet to absorb it. See [ADR-026](docs/adr/ADR-026-manual-only-nightly-eval-at-pre-revenue-stage.md).
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

## Day 47: Cross-Surface Hardening — Consent Cookie, Schema Posture, Pricing-Truth Export Gate, Workspace UX

A consolidated correctness pass over the Day-42→46 surface (tiering, schema-strict, observability/consent, prompt registry) plus a pricing-claims audit. Five commit clusters; nothing pushed yet (held behind an explicit deploy decision).

### Consent cookie now spans the apex + `app.` subdomain (`e9a3288`)

The cookie banner persisted consent in `localStorage`, which is origin-scoped — a user who accepted on the marketing apex was re-prompted on `app.job-application-copilot.xyz`. Switched the store to a first-party cookie scoped to `.job-application-copilot.xyz` (host-only on localhost / `*.vercel.app`), with a one-time legacy-`localStorage` migration read and `BroadcastChannel` cross-tab sync. Also fixed `instrumentation-client.ts`, which still read the now-never-written `localStorage` key at boot — left as-is it would have silently withheld Sentry Session Replay from every post-migration consenter (the boot read + the hot-add listener both went through the stale path). It now mirrors the cookie reader (cookie-first, legacy fallback, no React import). Public API unchanged; `tsc` + `eslint` clean.

### `_StrictBase` schema posture: `extra="forbid"` → `extra="ignore"` (`ef2994f`)

The shared LLM-output base rejected any benign extra key the model volunteered, turning the redundant client-side `model_validate` into an `AgentExecutionError` that routes to that agent's deterministic fallback (ADR-018). Honest scoping (verified against `src/openai_service.py`): the real fail-closed guard is OpenAI structured-outputs strict mode (`_build_response_format_schema` → `_enforce_strict_object_constraints` force-sets `additionalProperties:false` with `strict=True`, independent of this `ConfigDict`). `extra="ignore"` only relaxes the redundant re-validation; required-field / type / `Literal` enforcement is unchanged, so genuinely-malformed output (wrong type) still falls back. Scope held to the LLM-output base ONLY — `backend/auth_models.py`, `models.py`, `workspace_models.py` keep `extra="forbid"` (HTTP-boundary models where strict rejection is correct). Stale extra-key test updated (not reverted) + an over-permissiveness (wrong-type) guard + a model-level config-contract test added.

### Pricing-claims audit → tier-gated export entitlement + two copy fixes (`b82e772`)

Every landing pricing bullet was cross-referenced against `backend/tiers.py` + the gating code. All numeric caps were correctly wired; three claims were not: (1) Pro "Unlimited … saved jobs" — `saved_jobs` Pro is wired to 1000, not unlimited → reworded to "Unlimited job searches, 1,000 saved jobs"; (2) Free "PDF export, ATS theme" vs Pro "PDF + DOCX, all themes" — **no tier gate existed** on export format/theme and `/workspace/artifacts/export` had no auth at all → wired the gate so the copy is true (**ADR-027**); (3) Business "SSO, admin dashboard, shared shortlists" — zero wiring → reworded to "SSO & admin controls on request". 14 hermetic tests for the export-entitlement policy + raiser.

### Workspace UX: command-palette `:active` + locked-Premium upgrade CTA (`2211b10`)

A UX-parity audit of 12 workspace surfaces; 10 were already sound, 2 fixed: (a) the command palette set `data-active` only via `onMouseEnter`/Arrow keys, so a tapped row on touch got no press feedback — added `.b-cmd-item:active` mirroring the `[data-active]` treatment; (b) the Free-tier Premium toggle was HTML-`disabled` so its only upgrade hint was a hover `title` (dead on touch) — it now stays interactive when tier-locked and a tap surfaces the same `Notice` + `.b-notice-action` upgrade CTA the 429 path uses (`workspaceQuota.upgrade_url`), while `analysisLoading` / out-of-credits remain real disables.

### Test isolation: hermetic openai-unavailable test (`8e368c8`)

`test_run_structured_prompt_raises_when_openai_unavailable` asserted the no-credentials path but resolved the key via env / `openai_key.txt`, so it failed on any machine with a real key configured (pre-existing flake, unrelated to the schema change — verified by stashing). Now monkeypatches `load_openai_key → None` for a deterministic result regardless of local environment.

### Regression-safety re-verification (Days 42-46)

Re-audited the danger class "an LLM/IO gate that hard-fails the pipeline on drift": tier-aware model routing (defensive, free→standard / premium→gpt-5.5, everyone Free pre-cutover), atomic quota ordering (gate-before-work + best-effort refund), Lemon Squeezy webhook (HMAC `compare_digest`, unknown→200, env-gated), observability (no-op on empty DSN, pytest-skip, additive telemetry), per-agent fallback isolation (ADR-018 — a single agent's failure degrades only that agent), and the prompt registry — confirmed the registry tests assert **genuine full-string byte-identity** against the pre-migration concat (no golden-hash guard needed; `==` is stricter). All confirmed graceful-degrade; no regression from the Days 42-46 work.

### Deploy status

Local + unpushed. The schema + pricing/export-gate changes touch the workflow + entitlement surface, so the batch is held behind an explicit deploy decision rather than auto-shipping.

### ADRs added

- [ADR-027: Tier-gated export entitlement (Free = PDF + ATS theme)](docs/adr/ADR-027-tier-gated-export-entitlement.md)

## Day 48: Post-deploy UX follow-ups — feedback-widget placement, FAB colour, Free theme = Professional

Two user-caught items after the Day-47 batch went live.

### Sentry feedback widget collision + muted assistant FAB (`27e4235`, pushed)

On the Sentry-enabled prod build the auto-injected "Report an issue"
actor button and the workspace assistant FAB both pinned bottom-right;
Sentry's actor (much higher z-index) overlapped and blocked the
assistant chat. Not reproducible locally (Sentry is a no-op without a
DSN, so the widget never renders in dev — which is why the Day-47
visual pass missed it). Fix: `--actor-inset: auto auto 16px 16px` on
`:root` — per the installed `@sentry-internal/feedback` source the
actor is positioned via `inset: var(--actor-inset)`; this cascades
into the widget shadow DOM exactly like the existing `--actor-*` theme
props, moving the trigger to the bottom-LEFT, opposite the FAB.
Separately, the assistant FAB's blue read as muted vs the primary
buttons — an always-on white cursor-highlight radial was washing it
out; dropped the radial so `.rd-fab` renders the exact same
`linear-gradient(--accent-strong → #114be9)` as `.rd-btn-primary`.

### Free export theme = Professional; professional_neutral is now the global default

Product call refining ADR-027: Free's allowed theme is
`professional_neutral` (the cleaner black/white/Arial look), not
`classic_ats`. To avoid a Free user being blocked on their own
*default* export, `professional_neutral` is now the product-wide
default theme — every request model (`workspace_models.py`), the
`artifact_export_service` normaliser, and the frontend theme state
(`useArtifactExport`, `WorkspaceShell`) default to it; `classic_ats`
is the Pro/Business-only alternate. Pricing copy: Free bullet →
"PDF export, Professional theme". Theme pickers (ArtifactViewer,
ResumeIntake) reorder/relabel: Professional first, Classic ATS
second. `tiers.FREE_EXPORT_THEME` flipped; ADR-027 corrected in place
+ a dated Update note (same-session refinement — see the ADR's
governance note).

Tests: `test_export_entitlement.py` themes inverted (14 green). The
export-mechanics tests in `test_backend_workspace.py` pre-date the
gate and were all 429-ing on DOCX / classic_ats — added a
module-scoped autouse fixture resolving the export tier as a paid
user so they keep testing mechanics (DOCX round-trip, snapshot
forwarding); 10 export tests green. `test_exporters.py` unaffected
(28 green — `src/exporters.py` internals deliberately untouched;
`classic_ats` remains a valid, unchanged theme). Frontend tsc +
eslint clean.

### Deploy status

Day-47 batch + the `27e4235` follow-up are already pushed (both
products). This Free-theme/global-default change is committed
locally; push decision deferred to the operator (re-deploys the
backend gate + frontend defaults + pricing copy).

---

## Day 49: Job-search pagination ("Load more") + RPC offset migration

User report: "for whatever job I search only like 12 jobs are being
listed — do we have a cap?" Root cause was **not** an RPC/corpus cap:
`WorkspaceShell` hardcoded `page_size: 12` on the search call (the
"every query returns exactly 12" tell). The corpus is ~14.7k active
jobs across 4 sources; the `search_cached_jobs_ranked` RPC hard-caps
a page at `LEAST(p_limit, 50)`. Decision (operator): bump the page to
50 **and** add Greenhouse-style "Load more" pagination rather than
numbered pages.

### RPC: `p_offset` parameter (applied to prod) + tracked SQL

`search_cached_jobs_ranked` gained `p_offset integer DEFAULT 0` and
an `OFFSET GREATEST(0, COALESCE(p_offset, 0))` after the existing
`LIMIT`. Applied to prod as migrations
`search_cached_jobs_ranked_add_p_offset` then
`search_cached_jobs_ranked_restore_service_role_only` — the DROP+
CREATE re-introduced Postgres's implicit EXECUTE-to-PUBLIC, so a
corrective REVOKE-from-PUBLIC/anon/authenticated + GRANT-to-
service_role restored the ADR-021 posture (caught in post-migration
verification: grants must read `service_role:EXECUTE` only). The RPC
predated the `docs/sql` tracking convention (a governance gap); it's
now the tracked source of truth at
`docs/sql/supabase-cached-jobs-search.sql`, with a row added to the
`docs/README.md` schema-migrations table. `DEFAULT 0` keeps a
named-arg call against an older revision working, so the backend can
ship before/after the migration safely.

### Backend: offset threaded, `has_more` computed both paths

`JobSearchQuery.offset` + `JobSearchResult.has_more` (new optional
fields, safe defaults — every constructor is keyword, verified no
positional breakage). `cached_jobs_store.search()` takes `offset` and
forwards it as `p_offset` (clamped `max(0, …)`). `JobSearchService`:
the cache path sets `has_more = len(page) == page_size` (the RPC has
no cheap COUNT — "full page back" is the pragmatic signal; the next
fetch returning 0 is what finally clears the CTA); the live fan-out
path has the full deduped set in memory so it paginates exactly —
slice `[offset, offset+page_size)`, `has_more = len(deduped) >
offset+page_size`. `JobSearchRequestModel` gained `offset`
(`ge=0, le=100000` sanity bound) + `to_domain`; `JobSearchResponseModel`
gained `has_more` + `from_domain`.

### Frontend: append-not-replace + "Load more" CTA

`api-types.ts`: `JobSearchRequest.offset?`, `JobSearchResponse.has_more?`.
`WorkspaceShell` fresh search sends `page_size: 50, offset: 0` and
replaces; new `handleLoadMore` reuses the **echoed**
`searchResults.query` (not live form state — so editing the search box
after a search can't make the next page paginate a different query),
requests `offset = current results length`, and **appends** (deduped
by `job.id`, defensive against corpus shifts between requests).
Distinct `loadingMore` state so the grid stays visible and only the
button shows a busy state; `total_results` is recomputed to the
running on-screen count (the backend value is per-page). `JobSearch`
renders a soft-variant "Load more roles" button under the grid, gated
on `searchResults.has_more`.

Tests: `test_job_search_service.py` +7 (live first-page/offset-window/
past-end + cached offset-threading/full-final-page); `test_cached_jobs_store.py`
+1 (offset → p_offset, clamp) and the contract test's exact-args dict
updated to include `p_offset: 0`. Hermetic blast-radius green
(test_backend_app + test_job_search_service + test_cached_jobs_store
= 35; broader cached/job/models/snapshot slice = 40). Frontend tsc +
eslint clean. (The full offline suite can't complete here — pre-
existing network-integration tests hang without secrets/network; that
predates and is unrelated to this diff.)

### Deploy status

RPC migration is **already live in prod Supabase** (DB migrations
apply independently of the code push; the `DEFAULT 0` param is
backward-compatible with the not-yet-pushed backend). Backend +
frontend + docs are committed locally; push decision deferred to the
operator (re-deploys the backend offset plumbing + frontend
"Load more").

---

## Day 50: Job-search filter UX — auto-apply on change + 20/page initial

Immediate user feedback on the Day-49 pagination: (1) changing job
type / posted-within / sort did nothing until you clicked Search
again — "usually on sites the filter/sort applies as you click";
(2) a 50-row initial wall is too much, 20 + "Load more" reads better.
Both are frontend-only refinements of `WorkspaceShell` (no backend or
RPC change — Day-49's `581bee5` is live in prod and untouched here).

### Initial page 50 → 20

`SEARCH_PAGE_SIZE = 20` module const drives the fresh-search
`page_size`; "Load more" still pulls one `SEARCH_PAGE_SIZE` window per
click (it spreads the echoed `searchResults.query`, which now carries
20). Backend cap (`LEAST(p_limit, 50)`) unchanged — 20 is well under.

### Auto-apply filters / sort / posted-within

`handleSearch` was refactored into a shared `runSearch(query,
location)` core (offset 0, REPLACE). The form submit passes the live
box value; a new debounced effect re-runs the **executed** query
(`searchResults.query`, not the half-typed box) with the live filter
state whenever `sourceFilters | workModes | employmentTypes | sortBy |
postedWithinDays` changes — but only once a search is already on
screen (nothing to filter before the first search). `400 ms` debounce
(`FILTER_APPLY_DEBOUNCE_MS`) collapses a burst of multi-select chip
toggles into one request. The search box + location still require an
explicit Search submit (they're intentionally NOT effect deps), so
typing doesn't fire searches mid-keystroke.

### Out-of-order safety

Auto-fired searches make stale responses possible (a slow live-path
sort landing after a newer filtered one). Added a monotonic
`searchSeqRef`: `runSearch` bumps it and only applies a response /
owns the busy flag while its token is current; "Load more" *captures*
the token without bumping, so a filter change mid-load supersedes the
stale page instead of appending old-filter rows onto the new set.

Frontend tsc + eslint clean. No test delta (pure frontend
interaction; backend contract unchanged from Day 49).

### Deploy status

Day-49 (`581bee5`) is live in prod (pushed + deployed). This Day-50
refinement is committed locally; push decision deferred to the
operator (frontend-only re-deploy — `deploy.yml` `paths-ignore`
covers docs/md, so only the Vercel frontend rebuilds).

---

## Day 51: Exported résumé lost Projects + Publications — two compounding root causes + an LLM-budget audit

User uploaded a content-rich résumé (`.docx`: 6 projects, 2 roles,
categorised skills, a publication) and the exported tailored PDF had
**no Projects/Publications section**, a garbled Experience block, and
project GitHub URLs leaking into the contact line. "It was good
before — now it regressed." Diagnosed two independent bugs that
compounded.

### Root cause 1 — lossy snapshot rehydration drops projects/publications (the regression)

The parser is fine (proved: it extracts all 6 projects + the
publication + clean contacts). The drop is on the **export path**:
`backend/services/artifact_export_service._hydrate_snapshot` runs the
frontend-sent snapshot through `workflow_payloads._build_candidate_profile`
on *every* export. That rehydrator builds a `CandidateProfile` field
by field — and was **never updated to copy `projects` or
`publications`** when those fields were added to the schema in
`9fed3a6` ("Add Projects + Publications resume sections"). So every
export silently reconstructed the profile with empty
projects/publications → `_build_project_entries` / `_build_publication_entries`
returned `[]` → no sections in the PDF, even when the parse was
perfect. The frontend sends `analysisState` verbatim (TS types are
erased at runtime, so the JSON *does* carry the data) — the loss is
entirely server-side in the rehydrator. Fix: round-trip `projects`
(new `_build_project_entry` helper → `ProjectEntry`) + `publications`,
tolerant of malformed/ bare-string entries. Kept in lockstep with the
`CandidateProfile` schema by comment + tests.

### Root cause 2 — resume LLM parser truncated → garbage deterministic fallback

`ResumeLLMParserService.parse` ran at `max_completion_tokens=2600`
with `allow_output_budget_retry=False`. A rich résumé's JSON snapshot
exceeds 2600 → the model's output truncates mid-string → JSON parse
fails → `build_candidate_profile_from_resume_auto` silently falls back
to the low-fidelity **deterministic** parser (garbled project names,
project URLs in the contact line, mangled experience). Measured: the
LLM parse failed **~2 of 3 times** on the user's résumé. That is the
garbled-content half of the report, and the "regressed" feeling — a
leaner résumé fit under 2600; a richer one doesn't. Fix:
`max_completion_tokens 2600 → 6000` (it's a ceiling, not a
reservation — zero cost for ordinary résumés) and
`allow_output_budget_retry=True` (the established auto-bump-to-6000
safety net, used by every agent call already). Post-fix: 3/3 clean
LLM parses, 6 projects, clean contacts.

### Sibling audit — JD parser had the identical bug

Swept every `run_json_prompt` / `run_structured_prompt` caller.
Findings:

- **JD parser** (`jd_llm_parser_service`): `max_completion_tokens=2200`,
  `allow_output_budget_retry=False`, with the *same*
  silent-deterministic-fallback architecture
  (`build_job_description_from_text_auto`). A long JD (full
  responsibilities + a 40-skill list + must/nice-to-haves) truncates
  and the degraded JD then cascades into fit analysis, tailoring, and
  the cover letter. **Fixed identically** (2200 → 4000 + retry True;
  verified 4/4 clean on the largest sample JD, full 40-skill extract).
- **All workflow agents** (tailoring / review / cover_letter /
  resume_generation) and `resume_builder_structuring` already use the
  default `allow_output_budget_retry=True` — safe, no change.
- **Assistant Q&A + resume-builder conversational turn**: also
  `retry=False`, but these are *interactive* surfaces with a
  *graceful* fallback (`_fallback_unified` / `resume_builder_llm_fallback`),
  and the assistant's no-retry is explicitly pinned by
  `test_assistant_uses_fast_fail_request_shape`. That's a deliberate
  latency-vs-degradation product choice, **not** the
  silent-deliverable-corruption class. Left as-is; added comments
  documenting *why* it's intentional so the next reader doesn't
  "fix" it. Flagged for a product call (esp. `product_help`'s tight
  700-token budget).

### Tests

`test_workflow_payloads.py`: +2 (projects/publications round-trip
through `build_saved_workflow_snapshot_from_data`, incl. malformed
entries; end-to-end `preview_workspace_artifact` renders both
sections). `test_resume_llm_parser_service.py` +1 and new
`test_jd_llm_parser_service.py` +1 (parser asks for a generous budget
AND keeps the retry net — fails if anyone re-tightens it). Targeted
slice 73 green; broader workflow/parser/export slice 205 green (the 2
`resume_builder_export_*` failures are pre-existing + environmental —
reproduced on clean HEAD with changes stashed, they need a live
backend).

### Deploy status

Day-50 (`f400659`) is live in prod. This Day-51 fix set is committed
locally; push decision deferred to the operator (backend re-deploy —
`src/` + `backend/` touched, so the VPS backend rebuilds; no frontend
or DB change).

---

## Day 52: Resilient pipeline — escalating output budget + honest outage surfacing

Follow-up to the Day-51 audit. Goal (operator's words): "make the
whole pipeline resilient so it mostly avoids deterministic fallbacks
except a genuine OpenAI outage — and surface that to the user, blame
OpenAI :)". Truncation should never silently degrade a result; only a
real provider outage should, and the user should be told.

### Escalating output budget (was: one capped bump)

`_retry_with_higher_output_budget` was a SINGLE bump capped at 6000 —
so any payload whose JSON exceeded ~6000 tokens still truncated →
silent deterministic fallback. Rebuilt as an internal escalation
loop: keep doubling `max_output_tokens` (`min(max(n*2, n+400),
ceiling)`) until the response is no longer truncated or the ceiling
is hit. New `OPENAI_MAX_OUTPUT_TOKENS_CEILING` (default **16000**,
env-overridable) — generous headroom for every JSON we emit;
`max_output_tokens` is a ceiling not a reservation so it's free for
ordinary requests. The first escalation step is unchanged
(100 → 500), so the existing budget-retry tests stay green; it just
no longer *stops* there.

### `run_structured_prompt` parity

The two most important agents (tailoring, review) use the structured
path, which only retried on a *fully empty* incomplete response and
hard-failed on a *truncated partial JSON*. Added the same
partial-JSON escalation `run_json_prompt` has — the structured agents
are now as truncation-resilient as the rest, not the least.

### Outage vs content: a real distinction

New `OpenAIUnavailableError(AgentExecutionError)`. Every transport /
availability failure (initial call, escalation re-issue, structured
call, text stream) now raises it instead of a generic
`AgentExecutionError`. Subclass, so every existing
`except AgentExecutionError` keeps catching it — only the orchestrator
needs the `isinstance` check. Content failures (malformed JSON on a
*complete* response, schema drift, fields still missing at the
ceiling) stay `AgentExecutionError`.

### Orchestrator: fail fast + flag the outage

`run_agent_step` catches `OpenAIUnavailableError` *before*
`AgentExecutionError` and re-raises immediately — no 0.4s retry, no
per-agent deterministic (pointless when the provider is down for
every agent; it would also mask the outage as a routine per-agent
fallback). It cascades to `run()`, which sets
`AgentWorkflowResult.service_unavailable=True` and a friendly
`fallback_reason` ("Our AI provider (OpenAI) is having a moment …").
Content failures keep the existing per-agent deterministic isolation
— but with escalation they're now genuinely rare. Net: truncation no
longer causes fallbacks; only a real outage does, and it's flagged.

### Surfaced to the user

`service_unavailable` flows `workspace_service` → `workflow` response
→ `WorkspaceWorkflow` type → an honest amber banner in `AnalysisRunner`
(reuses the existing `b-notice-warning` style). The saved-workspace
restore path hard-codes it `False` — an outage is a point-in-time
signal, a reloaded run must not re-assert "OpenAI is down".

Tests: `test_openai_service.py` +3 (multi-step escalation
[100→500→1000→2000]; transport → `OpenAIUnavailableError` ⊂
`AgentExecutionError`; structured-prompt truncated-JSON now
escalates). `test_orchestrator.py` +2 (outage → deterministic +
`service_unavailable` + "OpenAI" reason; content failure → fallback
but NOT flagged). 27 targeted green; broader 212 green (the lone
failure is the pre-existing environmental `test_workspace_retention`
sweep — reproduced identically on clean HEAD with changes stashed).
Frontend tsc + eslint clean.

### Refinement — classification-based intelligent failing (circuit breaker)

Operator pushback on the first cut: "so one agent fails and you make
the WHOLE pipeline deterministic?" Fair — the a42418e cut fail-fast
tore down the run on the first `OpenAIUnavailableError`, discarding
agents that already succeeded on the LLM and over-degrading on a
transient/partial blip. Reworked into classification + a circuit
breaker.

Key framing: the SDK's 2 retries + our 1 app retry (several seconds,
backoff) ARE the transient filter. Anything that escapes has already
outlived the transient window, so we don't guess "will it recover in
3 s" (unknowable here — the user's re-run is that path); we classify
the *nature* of what persisted and act per cause.

`OpenAIUnavailableError` now carries a `category`, set by
`_classify_openai_exception` at the catch site:

- conn / timeout / 5xx (or anything unrecognised) → `outage`
- 429 that outlived the SDK retry-after → `rate_limited`
- 401 / 403 / 404 → `misconfigured` (our key/model/perms — NOT an
  outage: generic user copy + a loud `orchestrator_openai_misconfigured`
  ERROR log; we don't publicly blame OpenAI for our bug)
- 400 / 422 → returns `None` → raised as a plain content
  `AgentExecutionError`, NOT an outage. A too-long/bad request is
  specific to one agent's payload, so it stays per-agent isolated and
  the rest of the pipeline keeps using the LLM.

Orchestrator is now a **circuit breaker**, not a teardown: the first
provider-level failure trips a per-run breaker; that agent takes its
deterministic fallback, and every *remaining* agent skips the LLM
(no point hammering a down/limited/misconfigured provider — and more
429s only make it worse). Agents that ALREADY succeeded on the LLM
keep their output untouched. If ≥1 agent succeeded the run stays
`mode="openai"` (honest partial) with `service_unavailable=True` and
the cause-accurate banner; if none did it reconciles to
`deterministic_fallback` as before. Net: a one-off bad-request no
longer degrades anything beyond its own agent; only a genuine
provider-wide problem circuit-breaks, fast, with honest copy.

Tests: `test_openai_service.py` +3 (full taxonomy table; 400 →
content not outage; 429 → category `rate_limited`).
`test_orchestrator.py` +1 (mid-run outage: tailoring's LLM output is
KEPT, later agents skip the LLM, `mode` stays `openai`,
`service_unavailable` True). 31 targeted green; broader agent/
workflow/openai slice green.

### Refinement 2 — extend honest-outage surfacing to the non-pipeline parsers

Operator follow-up: "what about the résumé parser, JD parser, and
the other LLM interfaces?" Right call — the escalation + classification
machinery lives in `openai_service`, so those callers already inherit
fewer truncation fallbacks + a typed `OpenAIUnavailableError`. But the
circuit breaker is orchestrator-only (a parser is a single call —
nothing to "break"), and the résumé/JD auto-parsers + `jd_summary`
were still doing `except Exception → deterministic`, *swallowing* the
typed outage exactly like the pipeline used to. So a real OpenAI
outage during résumé upload silently shipped a worse parse with no
notice — the same silent degradation we'd just fixed for the pipeline.

Closed it consistently. New `src/llm_outage.py` is the single source
of cause-accurate, surface-neutral banner copy (`OUTAGE_USER_MESSAGE`,
`message_for_category`, `outage_notice`); the orchestrator now imports
from it instead of its own private map. `build_candidate_profile_from_resume_auto`
and `build_job_description_from_text_auto` take a backward-compatible
keyword `outage_sink`: they STILL return the deterministic result
(never break upload), but when the caught exception is a genuine
`OpenAIUnavailableError` they record `{unavailable, category, message}`
into the sink (`outage_notice` returns None for content failures, so
those stay silent as before). `jd_summary` attaches the same notice
to its deterministic dict.

`workspace_service` surfaces it: the standalone résumé-upload response
gains a `service_notice` (the résumé step shows the existing
`resumeNotice` warning with the cause-accurate copy instead of a
false "ready" success); the analysis path folds résumé-parse +
JD-parse + jd_summary outages into the SAME `workflow.service_unavailable`
+ `fallback_reason` the agent pipeline already uses — so the existing
`AnalysisRunner` banner covers an outage anywhere upstream with zero
new frontend surface there. New `ServiceNotice` type +
`WorkspaceResumeUploadResponse.service_notice?`. Assistant +
résumé-builder chat stay graceful-silent (the earlier deliberate
interactive product call).

Tests: new `test_llm_outage.py` (notice fires only for a real outage,
not content; misconfig copy stays generic); `test_profile_service.py`
+2 and `test_job_service.py` +2 (sink populated on outage, empty on
content, deterministic profile still returned); new
`test_jd_summary_service.py` +2. 50 targeted green; broad
workspace/parser/pipeline slice green. Frontend tsc + eslint clean.

### Deploy status

Day-51 (`ee90373`) is committed locally and still unpushed. The
Day-52 set + both refinements are also committed locally; all await
the operator's push decision (backend re-deploy + a frontend rebuild
for the résumé-step + analysis banners).

---

## Day 53: Premium reasoning tier — ADR-028 D2 validated by A/B, review → gpt-5.5@high

Formalised the LLM-provider / premium-model questions into
**ADR-028** (Decision 1 = Kimi K2 failover, Proposed/gated on
operator spend+outage data + an EU/PII per-task policy; Decision 2 =
premium reasoning tier). Then *validated Decision 2 with data* before
touching the paid product.

### The finding (3-arm A/B, `tests/quality/review_model_ab_runner.py`)

ReviewAgent over the 6-scenario harness (3 clean = over-correction
guard, 3 adversarial = planted-fabrication detection + correction),
18 LLM calls:

| arm | adv detection | adv correction | clean no-false-reject |
|---|---|---|---|
| gpt-5.4 @ medium (free) | 1.0 | 0.958 | 1.0 |
| gpt-5.5 @ medium (premium today) | 1.0 | **0.911** | 1.0 |
| gpt-5.5 @ **high** | 1.0 | **1.0** | 1.0 |

Detection is **perfect at the free model** — gpt-5.5 buys zero
grounding-catch. The shipped premium config (`gpt-5.5@medium`) is
**≤ free gpt-5.4@medium** (a slight correction regression) — i.e.
premium was paying 2× for a tie-to-regression. gpt-5.5's value is
**entirely in high reasoning** (the only perfect arm), the exact
slice ADR-022's model-only override never invoked.

### The change

Reasoning effort is now premium-aware **only for `review`**, exactly
mirroring ADR-022's model-override plumbing:
`OpenAIService._resolve_reasoning_effort` takes an explicit override
(wins over task routing; `None`/`""` → routed default) exposed as a
`reasoning_effort` kwarg on `run_json_prompt` / `run_structured_prompt`;
`backend/model_routing.build_workflow_reasoning_overrides` (gated
identically to the model helper — premium + Pro/Business) maps only
`review → "high"`; threaded `workspace_service` →
`ApplicationOrchestrator(reasoning_overrides=)` → `_run_pipeline` →
`ReviewAgent(reasoning_override=)`. `resume_generation` /
`cover_letter` deliberately untouched (not measured — no evidence to
act on). **Standard / free runs are byte-for-byte unaffected**
(override `None` → routed `medium`). ADR-022 keeps a status note;
ADR-028 D2 flips to Accepted+shipped.

Tests: +5 (`select_workflow_reasoning` / `build_workflow_reasoning_overrides`
shape; orchestrator threads `high` to review only on premium, `None`
on basic; `OpenAIService` override beats task routing). 47 targeted
green; broad 234 green (lone failure = the pre-existing environmental
`test_workspace_retention` sweep, repeatedly reproduced on clean
HEAD, untouched by this diff). The A/B runner is committed as a
durable reusable tool (`tests/quality/*_runner.py` convention).

### Deploy status

Days 51–52 + the two refinements + the CI fixes (`ee90373` …
`c225643`) are **live in prod** (pushed; CI #116/#117 green). This
Day-53 set is committed locally; push decision deferred to the
operator (backend re-deploy — `src/` + `backend/` touched; no
frontend or DB change; premium reasoning only affects opt-in
credit-burning premium runs).

## Day 54: Theme expansion — ThemeSpec single-source + `modern_blue` (Phase 1 + 2a)

Operator asked to widen the résumé/cover-letter theme offering. Ran a
design-research phase first (no code): surveyed ATS-parse evidence +
typography conventions + a battle-tested accent palette, produced an
archetype catalogue + approved build-list, all parked in `report.md`.
Then built **easiest-first, one theme at a time, eyeballing real
WeasyPrint output before wiring** — sample PDFs rendered from
deterministic fixtures, so **zero LLM/API cost** for theme QA.

### Phase 1 — `ThemeSpec` refactor (ADR-029; realises ADR-015's follow-up)

`src/exporters.py` had **three hand-synced palette maps**; two **more**
hardcoded theme sets lived in the backend services (an unknown theme
silently normalised to a default → a missed edit renders the *wrong*
theme with no error). Collapsed all of it to one frozen `ThemeSpec`
registry that derives résumé + cover-letter + DOCX palettes; the
backend gates now import a public `SUPPORTED_THEMES` from it. Adding a
theme = **one registry entry**. Proven output-neutral for the two
existing themes: resolver dicts byte-identical for every theme +
fallback, and the 12-fixture renderer-fidelity runner byte-identical.

Also fixed a latent coupling the operator caught: the cover-letter
renderer **hardcoded Georgia serif** for every theme. It now follows
the theme's *prose* font — `classic_ats` / `professional_neutral` have
Georgia as their prose font so this is **byte-identical** for them
(verified empirically), while a sans theme finally gets a sans letter
that matches its own résumé (the "matched set" is now true at the font
level, not just colour).

### Phase 2a — `modern_blue`

First new theme: single-column (**fully ATS-safe**), all-sans, deep
professional blue accent `#1a56db` (~5.9:1 on white), faint **cool**
off-white paper `#f6f8fd`/`#f8fafe` — the `classic_ats` "designed,
not stark" trick in a cool key (a paint layer; ATS reads the text
layer, so background tint is parse-irrelevant — `classic_ats` itself
is the proof). Operator picked the faint tint over crisp white / a
stronger tint after a 3-way sample comparison.

Wiring touch-set, now minimal post-refactor: `ThemeSpec` entry +
`ArtifactTheme` union + `ArtifactViewer` picker/hint + one
`workspace_models` Literal. **Zero `tiers.py` change** — entitlement is
by-exclusion (Free = `professional_neutral` only; any other theme is
Pro/Business via the existing 429 path, ADR-027), so ATS-safe themes
gate themselves.

87 backend tests green (exporters / export-entitlement / resume-builder
/ workflow-payloads / tier-aware); renderer-fidelity runner now
exercises `modern_blue` and is green; frontend `tsc` + `eslint` clean.

Governance: **ADR-029** added; ADR-015 Follow-Up annotated done; ADR
index + current-state note updated. `creative_warm`, `architect_mono`,
and the gated non-ATS `presentation_twocol` (a new `layout` branch,
reserved in `ThemeSpec` now) follow the same loop in later phases.

Phase 1 + 2a committed locally (`365321d`); push decision deferred to
the operator (touches `src/` + `backend/` + `frontend/` — backend
re-deploy + a Vercel deploy; the new theme is opt-in and the two
existing themes are proven byte-identical).

### Phase 2b — `creative_warm` + a `header_rule_color` two-tone field

Second new theme: modern-editorial — serif NAME (Georgia, h1 only) for
gravitas, clean sans everywhere else (scannable + ATS-safe), emerald
`#00a388` accent, faint near-neutral warm paper. Single-column → fully
ATS-safe; auto Pro/Business via the same by-exclusion gate.

Operator-requested refinement that generalised cleanly: the header
divider (résumé name underline + cover-letter greeting break) was
hardwired to `var(--accent)`. Added a `ThemeSpec.header_rule_color`
field **defaulting to the literal token `var(--accent)`** so every
pre-existing theme renders the rule byte-for-byte as before (re-proven:
`classic_ats` / `professional_neutral` / `modern_blue` dividers still
`solid var(--accent)`; 42 exporter/entitlement tests + fidelity runner
green). `creative_warm` overrides it to a deeper `#0b7c5e` so the
structural divider reads as a deliberate anchor while section headers
keep the brighter `#00a388` — a two-tone the field now makes any
future theme able to opt into without touching the shared template.

Wiring identical-minimal: `ThemeSpec` entry + `ArtifactTheme` union +
`ArtifactViewer` picker/hint + one `workspace_models` Literal +
fidelity-runner loop coverage. Still ADR-029 (same series; no new ADR —
ADR-029 already scoped `creative_warm` as a same-loop follow-on).

Phase 1 + 2a + 2b held local as one stack; push decision still the
operator's. `architect_mono` and the gated `presentation_twocol`
remain.

### Phase 2c — `architect_mono` + Phase 3 — `presentation_twocol`

`architect_mono`: single-column near-monochrome (deep cool ink AND
accent — the "design" is typographic, not colour), one HAIRLINE rule
(`header_border_px=1`), geometric sans, airier `prose_line_height`
1.6, crisp pure white on purpose (deliberate stark contrast to
`modern_blue`'s tint). No renderer change — pure ThemeSpec entry.
ATS-safe; Pro by-exclusion.

`presentation_twocol` — the `ThemeSpec.layout` discriminator is now
LIVE. `_build_resume_html` branches on `spec.layout` as an **early
return BEFORE the single-column path**, so all five single-column
themes' code path is character-for-character untouched (byte-identical
— the now-6-theme fidelity runner confirms every content string still
round-trips, incl. the two-column). New `_build_structured_resume_body_twocol`
reuses the EXACT classic section builders (content identical; only the
shell differs) and authors the DOM header→main→sidebar so the PDF
text layer extracts as a coherent linear read despite the visual
columns (Phase-0 R2 — the realistic non-ATS tolerance ceiling). Deedy-
style asymmetric: wide main (summary/experience/projects/publications)
+ tinted sidebar (skills/education/certifications).

Deliberate v1 scoping (recorded in ADR-029 Update): non-ATS safety =
in-picker ⚠ warning + Pro/Business by-exclusion + opt-in + non-default
(a bespoke entitlement is **deferred**, not forgotten); **PDF-first** —
the DOCX renderer has no `layout` input so a `presentation_twocol`
DOCX renders single-column in-palette (documented in the hint; DOCX
two-column stays deferred per ADR-015/029); cover letters never branch
on layout (prose → always single-column), as designed.

Wiring (both): `ThemeSpec` entries + `ArtifactTheme` union +
`ArtifactViewer` picker/hint (the two-col hint carries the explicit
non-ATS warning) + `workspace_models` Literal + fidelity-runner loop
(now all 6 themes). Verification: fidelity runner OVERALL PASS across
6 themes incl. two-column; 60 backend tests (exporters /
export-entitlement / resume-builder / workflow-payloads /
error-message allowlist) green; frontend tsc + eslint clean. Still
ADR-029 (it scoped the series + reserved `layout`; an Update note
records the Phase 2b/2c/3 deltas without touching the Decision).

The full theme series (Phase 1→3) is now built; entire stack held
local — push decision the operator's.

## Day 55: Résumé/theme presentation polish — ship the single-column set; hold two-column

First production ship of the new themes + a batch of presentation
polish, after operator review of real output against 10 reference
templates.

- **Contact line — count-aware two-line packing.** A long portfolio
  URL was splitting mid-string in the header. New
  `_looks_like_contact_link` (emails stay details; `medium.com/@x`-
  style URLs correctly classify as links — a real bug found+fixed) +
  `_build_resume_contact_inline_html`: 0–1 links one line; 2 links =
  details line + both links line; 3+ = details+first link / rest;
  every item `white-space:nowrap` so a URL never splits. +2 hermetic
  tests.
- **Mode-aware headline line.** Renders `artifact.target_role` (the
  JD-tailored role) between name and contact; OMITS byte-cleanly when
  empty (no-JD/resume-builder path) — never fabricated, never forced.
  No schema change (field already existed). +2 tests, 1 structural
  test updated (it had guarded the dormant `.resume-classic-role`
  staying dormant — the feature deliberately activates it).
- **Theme picker → accessible native `<select>` dropdown.** The
  segmented toggle was data-driven (all 6 already worked) but its
  flex:1-across-one-row CSS cramped/clipped at 6. Replaced with a
  styled select (scales to any count, OS keyboard/mobile a11y for
  free); dead toggle CSS removed.
- **Opt-in header-band ThemeSpec capability** (`header_band_bg`/`fg`,
  default "" → today's plain rule header, byte-identical for any
  non-opting theme). `architect_mono` → solid ink masthead (white
  text); `creative_warm` → soft warm "sand" band (dark text,
  operator-chosen over an emerald variant). Band bleeds full to the
  page top (negates the shell's 13mm top padding) + sides, like the
  reference templates. The 3 ATS-simple themes
  (`professional_neutral`/`classic_ats`/`modern_blue`) opt out and are
  **provably unchanged** (no `--band` class; band CSS gated + inert).
- **Two-column held back.** Operator judged `presentation_twocol`
  not designer-grade yet (gap analysis vs the 10 references parked in
  report.md "Designer-grade theme expansion v2"). The two-column
  **engine stays in the renderer, dormant and still test-covered**
  (fidelity loop + `test_resume_headline_*` exercise it), but the
  theme is **removed from the user surface** — `ArtifactTheme` union,
  `THEME_OPTIONS`/`THEME_HINT`, and the `workspace_models` Literal —
  so it is not offered until its rework ships. Engine-vs-surface split
  recorded so it isn't mistaken for deleted work.

Net shipped: **5 single-column themes** (the 2 originals + the 3 new
designed ones) + the polish. Verification: **121 backend tests**
(exporters / resume-builder / workflow-payloads / error-message
allowlist / export-entitlement / backend-workspace) + the
renderer-fidelity runner (all 6 incl. the dormant two-column engine) +
frontend tsc + eslint — all green. Still the ADR-029 series (Update
note covers the deltas; no Decision change). Operator approved the
push: `src/` + `backend/` + `frontend/` → backend re-deploy + Vercel;
the prior held stack (`365321d`/`e16048e`/`d2c4e82`) ships with it.

## Day 56: Résumé-builder → tool-using agentic loop (Slice 1A) — `fetch_github_readme` + Responses-API native function calling

QA had a clean reproduction of the symptom: the conversational
resume-builder told a user "Yes — if you share the GitHub project
links, I can extract the skills and tools from them," then captured
the URLs verbatim into `projects_notes` with no tech stack and no
project description. The agent had **no tool wired** — it was a
form-filler dressed up as an agent, and the LLM was happy to claim a
capability it didn't have.

Slice 1A is the parked "résumé-builder → tool-using agentic loop"
plan (`report.md`, parked 2026-05-20) cashed in — the smallest piece
that turns the form-filler into a tool-using agent, demonstrable end-
to-end. **Native Responses-API function calling**, not LangGraph —
the platform is already Responses-native and the agent is single-
provider single-tool; a LangChain/LangGraph layer would add weight
without value at this scope.

What landed:

- **New tool module** `backend/services/resume_builder_tools.py` with
  `fetch_github_readme(url)` — github.com hostname allowlist
  (no github.io / gist / api / IP literals); fetches
  `raw.githubusercontent.com/{owner}/{repo}/HEAD/README.md` so the
  default branch resolves regardless of `main` vs `master`;
  200 KB size cap + 6 s timeout (hard ceilings on conversational-turn
  latency and prompt budget); `text/plain` or `text/markdown` content-
  type gate; stable error codes (`invalid_url` / `timeout` /
  `network_error` / `http_status` / `wrong_content_type` / `oversize`
  / `empty_body` / `decode_error`) — never raises across the tool
  boundary, every failure is a first-class output the model can
  reason about. Plus a dispatcher (`execute_tool(name, args_json)`)
  that wraps unknown-tool / bad-JSON / wrong-shape cases in the same
  JSON envelope.

- **Agentic-loop driver** as a new `OpenAIService.run_tool_loop`
  method — mirrors `run_json_prompt` (same instructions / user-prompt
  / expected-keys / cost-trace contract) but loops on Responses-API
  `function_call` items: model emits a call → server executes via the
  passed-in `tool_executor` → both the `function_call` echo AND the
  `function_call_output` get appended to the next iteration's input
  list → loop. Final response (text, no function calls) is parsed as
  the JSON envelope and returned as `(payload, trace)`. Iteration cap
  = 5 (one URL → one fetch → one answer + headroom). Each iteration
  hits `_enforce_budget` + records usage via the new
  `_track_usage_from_response` helper, so a runaway loop trips the
  budget guard instead of silently burning credits. On cap-hit the
  loop raises `AgentExecutionError` — the resume-builder service
  already catches that and drops to the regex/step-machine fallback.

- **Wired into `_run_llm_turn`** in
  `backend/services/resume_builder_service.py` — when the service
  exposes `run_tool_loop`, the turn routes through it with the
  resume-builder tool registry; otherwise falls back to
  `run_json_prompt` (keeps old test stubs and provider mocks working
  without an interface bump). Tool events get summarized
  (`fetch_github_readme(...) → ok: read owner/repo README`) and
  appended to `conversation_history` between the user and assistant
  entries, so a later turn's "Recent Conversation" block reads as a
  three-part chain (`user → tool → assistant`) and the model
  remembers what it already fetched without re-reading the README.

- **Prompt v1 evolved in place** (`prompts/resume_builder/v1.json`,
  byte-mirror in `tests/test_prompts.py`): added a "Tools you can
  call" block telling the model `fetch_github_readme(url)` exists and
  how to use it ("Call the tool BEFORE describing the project — never
  invent details"), plus an explicit **Honesty rule**: "Never promise
  a capability you don't have. If the user asks you to browse the
  web, open a PDF, read a private link, run code, scrape LinkedIn,
  etc., say so plainly in one sentence and offer the closest thing
  you CAN do." Both edits land together — the byte-equivalence test
  catches drift between the JSON and the expected-prompt builder.

- **Hermetic tests** (`tests/backend/test_resume_builder_tools.py`,
  31 cases): URL parsing (canonical shapes, `.git` suffix, scheme
  inference, all the rejected hosts including github.io / gist /
  api.github.com / IP literals); fetch success + every failure mode
  (timeout, oversize, 404, wrong content-type) via a monkeypatched
  `_fetch_text` so no real network call goes out; dispatcher
  contract (unknown tool, malformed JSON, non-object args, wrong
  shape → all return a JSON error envelope, never raise); tool-spec
  shape (`additionalProperties: False`, required = `["url"]`).

Verification: **168 tests** across `tests/test_prompts.py` +
`tests/test_resume_builder.py` + `tests/backend/test_resume_builder_tools.py`
+ `tests/backend/test_prompt_registry.py` +
`tests/backend/test_cost_tracking.py` +
`tests/backend/test_structured_outputs.py` +
`tests/test_backend_workspace.py` — all green. The cost-tracking
suite specifically exercises the new `_track_usage_from_response`
extraction; that path is the most fragile part of the
`run_json_prompt` → `run_tool_loop` refactor and it stays clean.

What this changes for users:
- Paste a github.com link mid-conversation → the agent fetches the
  README, infers the tech stack and outcome, captures both into
  `projects_notes` in the user's voice, and asks one targeted
  follow-up. No more "I'll extract that — but actually I can't."
- Out-of-scope requests (LinkedIn scraping, PDF reading, web search)
  get a one-sentence honest refusal + the nearest available
  alternative, instead of a confident-sounding hallucinated promise.

What's still parked (`report.md`, Phase 2/3 of the agentic-upgrade
plan):
- A `web_search` tool (provider TBD — Tavily / Brave / OpenAI built-in)
- Proactive-inference channel (model offers "want me to draft a summary
  from your projects?" without being asked)
- Promise tracking via `pending_followups[]` session state
- Conversational eval fixture set + ADR-031 for the agentic shape

Slice 1A demo path: paste a public GitHub URL into the resume builder
and watch the agent read it. The honesty patch + tool dispatch fall
out for free.

## Day 57: Résumé-builder Slice 1B — full conversation history + `proactive_offer` chip

Slice 1A made the agent capable; Slice 1B makes it FEEL intelligent.
The two user complaints behind this slice:

1. "Is each new question going to a fresh gpt instance?" — the agent
   was forgetting mid-conversation. Why: `build_resume_builder_prompt`
   hard-sliced history at `[-12:]` (the last 6 user/assistant pairs).
   Past that point the model saw nothing — no context, no callbacks,
   no "as I said earlier." Felt like a fresh instance because, prompt-
   wise, it nearly was.
2. "I want it to suggest things — like draft a summary based on the
   projects I shared, the way you do." — the agent never volunteered.
   It asked questions and saved answers; it never said "given what
   we have, want me to draft your professional summary?"

Slice 1B addresses both, end-to-end (backend + UI):

**(1) Full conversation history with a character-budget guard.**

- Dropped the hard `history[-12:]` slice in `build_resume_builder_prompt`.
- New `_slice_history_for_budget(history, max_chars=...)` helper
  (default 30 000 chars ≈ ~7 500 tokens) walks newest-first,
  accumulating serialized entries until adding the next would exceed
  budget. Returns a contiguous SUFFIX of the history in chronological
  order. ALWAYS keeps at least the most recent entry so an over-budget
  newest message doesn't silently break the chat.
- The in-memory `conversation_history` cap bumped from 48 to 200
  (~100 turn pairs + interleaved tool events) — the soft prompt-time
  guard is what defends per-turn token budget; the hard cap is a
  pathological-session memory safety valve.
- New unit tests for the slicer (4 cases: under-budget passthrough;
  over-budget keeps a suffix; single-entry-over-budget still returned;
  empty/None input).

**(2) `proactive_offer` JSON channel + UI chip.**

- Added `proactive_offer: str | None` as a 5th key to the resume-
  builder LLM contract. Documented in
  `prompts/resume_builder/v1.json` with concrete examples of GOOD
  offers ("Draft my professional summary"; "Group my skills into
  Languages / Frameworks / Tools") and BAD ones ("Help me with my
  resume" — too vague; "Continue" — not an action; "Are you done?"
  — that's a question, not an offer). The prompt also tells the
  model the CTA is rendered FROM THE USER'S point of view (first-
  person imperative), so the user clicks the chip to say "yes, do
  that." Mirrored byte-for-byte in `tests/test_prompts.py` and added
  to the `expected_keys` assertion so a typo in the JSON fails at
  parse time. Slice 1B also caps the offer at 200 chars at the
  backend boundary — defense against a model that returns a full
  paragraph instead of a CTA.
- `_run_llm_turn` returns a `(assistant_message, proactive_offer)`
  tuple; the caller (`answer_resume_builder_message`) threads the
  offer through to `_serialize_session`, which adds it to the
  response payload alongside `assistant_message`.
- Frontend: added `proactive_offer?: string | null` to
  `ResumeBuilderSessionResponse`. In `ResumeIntake.tsx`, when the
  field is populated, render a single pill-shaped chip below the
  assistant message ("✨ Draft my professional summary"). The chip
  calls a new `onBuilderProactiveOfferAccept(offer)` callback —
  `handleResumeBuilderAnswer` in `WorkspaceShell` now accepts an
  optional `overrideText` parameter, so the chip submits the offer
  text directly without round-tripping through the textarea state
  (avoiding the React setState async window where a Continue click
  fires before the prefilled value commits).

What this changes for users:

- The agent remembers across the whole session — you can correct a
  field you mentioned 15 turns ago and the model knows what you're
  referring to. Within prompt-budget anyway (30k chars ≈ ~25 dense
  turn pairs; for typical sessions, the whole thing fits).
- The agent volunteers. Once you've shared a few projects and
  experience entries, you'll see a "✨ Draft my professional summary"
  chip pop up — one click and the model goes off and writes it from
  what you've already told it. No more typing "yes, do that" by hand.

What's still parked (`report.md` Phase 2/3):

- Promise tracking (`pending_followups[]` session state, so the agent
  remembers things it said it would do later)
- `web_search` tool for company / role / domain context
- Full conversational eval (15–20 hand-curated transcript fixtures
  + rubric) — important quality infra; the smaller 5–8 fixture
  minimal eval is also still parked. Slice 1B intentionally doesn't
  block on eval; the changes are additive (existing behavior
  preserved when `proactive_offer` is null and full history fits
  under budget) and locally tested.
- ADR-031 for the agentic shape (draft during Slice 1C, accept when
  the rest of Phase 2 lands).

Verification: **172 tests** across `tests/test_prompts.py` +
`tests/test_resume_builder.py` + the Slice 1A tool tests +
`test_prompt_registry` + `test_cost_tracking` +
`test_structured_outputs` + `test_backend_workspace` — all green
(168 → 172, the 4 added are the budget-slicer unit tests). Frontend
`tsc --noEmit` clean (exit 0). Frontend `eslint src` clean (exit 0).

Demo path: open the resume builder, give the agent a couple of
projects + an experience entry, watch the "✨ Draft my professional
summary" chip appear below its next reply. Click it — the agent
writes the summary from what you've told it so far. No retyping, no
restating.

## Day 58: Two silent-fallback bugs (structuring schema + theme registry) + agentic eval

QA replay of the user's original 10-turn transcript surfaced TWO bugs
that had been hiding in production for weeks. Both followed the same
pattern: two configs that should match drifted apart, downstream code
silently substituted a "safe default" instead of erroring, and the
quality regression went unnoticed because the fallback output looked
plausible.

### Bug 1: structuring LLM silently 400-erroring on a `dict[K, V]` field

The resume-builder structuring schema's
``skill_categories: dict[str, list[str]]`` translated to a JSON
Schema with ``{"type": "object", "additionalProperties": <schema>}``.
OpenAI's strict-mode validator rejects this shape when the field is
in ``required`` — error: "Extra required key 'skill_categories'
supplied". The exception was caught by a broad ``except`` in
``_structure_via_llm``, the regex fallback ran, and the visible
output was the regex parser's best-effort — empty bullets, link
field grabbed the first tech-stack token, single-paragraph projects.
The structuring LLM had been failing **every single call** since the
schema landed.

Fix: refactored ``skill_categories`` from ``dict[K, V]`` to
``list[ResumeBuilderStructuringSkillBucket]`` where each bucket is
``{label: str, skills: list[str]}``. List-of-typed-objects is OpenAI-
strict-mode friendly. Boundary conversion in
``_sanitize_skill_categories`` reshapes back to ``dict[str, list[str]]``
so the artifact renderer (downstream consumer) stays unchanged. Bonus
prompt overhaul that finally got to RUN: worked BEFORE/AFTER examples
for projects + education, strict link-URL rule, third-person-voice
rule across all fields, multi-turn education merge example. Commit
``bcd64d5``.

### Bug 2: 4 of 6 themes rendering as classic_ats

``src.exporters._THEME_SPECS`` (the canonical theme registry, surfaced
via ``SUPPORTED_THEMES``) lists six themes. But
``src.resume_builder.RESUME_THEMES`` only listed two
(``classic_ats`` + ``professional_neutral``). Every consumer of
``build_tailored_resume_artifact`` runs the picked theme through
``_resolve_resume_theme(theme, ...)`` which checks
``if theme in RESUME_THEMES:`` — and silently substitutes
``classic_ats`` for any non-matching name. So ``modern_blue``,
``creative_warm``, ``architect_mono``, and ``presentation_twocol``
all rendered as classic_ats. Confirmed by md5-comparing the rendered
PDFs: ``classic_ats.pdf`` and ``modern_blue.pdf`` were byte-identical.

Blast radius: the workspace export flow (``artifact_export_service``),
the workspace tailoring run (``workspace_service``),
the persistence pipeline (``workspace_persistence_service``), and the
resume builder export. Every user who picked one of the 4 newer themes
in any of these flows since the Phase 2 theme expansion (Day 54)
silently got classic_ats output. ~4 weeks of degraded UX.

Fix: ``RESUME_THEMES`` now lists all 6 themes with per-theme label +
tagline. Two new pact-tests in ``tests/test_resume_builder.py``
(``test_resume_themes_registry_matches_supported_themes`` +
``test_resolve_resume_theme_round_trips_every_supported_theme``) lock
the two registries together so the same drift cannot recur. Commit
``23ec230``.

### Slice 1D: minimal conversational eval

The fact that BOTH of the above bugs lived for weeks without anyone
noticing is exactly what the parked plan flagged when it said
"conversational quality IS the product, eval is load-bearing."
Building it now.

Two complementary pieces landed:

**1. Hermetic schema strictness tests**
(`tests/backend/test_llm_schema_strictness.py`, 18 tests):

Walks the JSON Schema produced by ``_build_response_format_schema``
for every Pydantic model that's wired to ``run_structured_prompt`` in
production (9 models — TailoringOutput, ReviewOutput,
ResumeGenerationOutput, CoverLetterOutput, JDSummaryOutput,
ResumeBuilderStructuringOutput, ResumeParserOutput, JDParserOutput,
ResumeBuilderTurnOutput) and asserts:
  - No node has ``additionalProperties`` set to a schema dict (the
    ``dict[K, V]`` trap that broke the structuring call).
  - No node uses ``anyOf`` with more than one non-null branch (the
    multi-type-union trap).

These tests are **static** — they don't hit the API, so they run on
every CI build in ~1.5s. If anyone introduces a new ``dict[K, V]``
field or a multi-branch union in any production schema, this fails
at CI before the change can ship and start silently 400-erroring in
production. Critical to keeping the bug we just caught from coming
back in a new place.

**2. LLM-driven agentic-behavior eval**
(`tests/quality/resume_builder_agentic_runner.py`, 7 scenarios):

Complements the existing 13-scenario `resume_builder_quality_runner`
by focusing only on the Slice 1A + 1B behaviors:

  - `github_url_fires_tool`: user shares a github.com URL →
    `fetch_github_readme` called → `projects_notes` populated.
  - `non_github_url_no_fetch`: non-github URL → tool NOT called →
    agent honestly says it can't fetch.
  - `honesty_on_linkedin_scrape`: user asks to scrape LinkedIn →
    agent refuses honestly without promising the capability.
  - `proactive_offer_after_enough_signal`: after role + projects
    (with tool fetches) + skills are shared → agent fires a
    `proactive_offer` OR drafts the summary inline (behavior
    matcher accepts either).
  - `proactive_offer_silent_mid_basics`: first turn → no proactive
    offer (the agent shouldn't fire one mid-collection).
  - `multi_turn_correction_preserved`: user corrects target role
    across turns → final draft holds the corrected value.
  - `structured_payload_runs_after_generate`: after generate,
    `structured_projects_payload` must be non-empty. THIS IS THE
    CANARY for the silent-fallback bug — if the structuring schema
    gets a 400 and falls back to regex, this scenario fails because
    the regex parser doesn't populate `structured_*_payload` (it
    builds entries directly from raw notes).

Scoring is behavior-level, not vocabulary-level: matchers accept any
of several markers ("read" / "captured" / "saw" / "README" / etc.)
to absorb LLM phrasing variance. Vocabulary-strict matchers were
calibrated wrong on first run — caught + broadened during the build.

Cost: ~7 scenarios × ~3-4 turns × gpt-5.4 ≈ $0.05 per run. Runs
on-demand (manual trigger), not on every CI build. Wire into nightly
or pre-release runs.

VERIFICATION: full eval ran 7/7 green against the live API.
``test_llm_schema_strictness`` ran 18/18 green. The complete affected
test surface (172+18+14 = 204 tests across the impacted suites) all
green.

What's still parked (`report.md` Phase 2/3):
- `web_search` tool for company/role/domain context
- Promise tracking via `pending_followups[]` session state
- Conversational eval expansion to the full 15-20 fixture set
- ADR-031 for the agentic shape

This session, end-to-end:
  - Slice 1A (agentic loop + fetch_github_readme, `055fd60`)
  - Slice 1B (full history + proactive_offer chip, `78184fe`)
  - Iteration cap + list coercion fixes (`ff2c93a`)
  - Structuring schema + prompt overhaul (`bcd64d5`)
  - Theme registry drift fix (`23ec230`)
  - Schema strictness pact + agentic eval (this commit)

Six commits. The user's original "the projects sections couldn't
generate the data" complaint and the modern_blue-looks-like-classic_ats
complaint both resolved, with regression tests pinning each fix down.

## Day 59: Phase 2 of the agentic upgrade — promise tracking, web_search, ADR-031

Slices 1E and 1F close out Phase 2 from `report.md`. ADR-031 documents
the whole arc (1A through 1F).

### Slice 1E: `pending_followups[]` promise tracking

The agent today acknowledges deferrals ("we can do the summary later
based on the projects") and then evaporates them. Slice 1E gives the
agent a memory across turns:

- New session field: `pending_followups: list[str]` — each entry a
  short topic string the LLM owns end-to-end.
- New JSON channels on the intake turn: `add_followups: list[str]`
  (new commitments captured this turn) + `resolved_followups:
  list[str]` (items addressed this turn). The service applies
  resolutions first (substring + case-insensitive match — the model
  sometimes paraphrases its own wording), then adds new commitments
  (dedupe by case-insensitive equality), then caps at 12 outstanding.
- Prompt receives an `Outstanding Follow-ups` block each turn so the
  agent can see what's open.
- TRIGGER PRIORITY rule made the behavior reliable: when the user
  asks an open-ended question (`"what else?"` / `"what's next?"` /
  `"anything missing?"`), the agent surfaces the OLDEST outstanding
  follow-up before asking for a new field. Without this rule,
  gpt-5.4@medium preferred new collection questions and the eval
  flagged it on the first calibrated run.
- Session persistence (export/restore JSON) carries the field through
  with a backward-compatible default of `[]` for older saves.
- `_serialize_session` exposes `pending_followups` so an optional UI
  surface can render an "outstanding items" panel later (v1 relies on
  the agent's natural assistant_message + proactive_offer behavior).

Verification:
- 3 hermetic unit tests for the apply logic (add → resolve via
  paraphrased substring; 14 items + dedupe + cap-at-12; export →
  restore round-trip preserves the list).
- 1 new conversational eval scenario
  (`promise_tracking_remembers_deferred_publication`): user defers a
  publication on turn 3, gives skills on turn 4, asks "what else do
  you need from me?" on turn 5 → agent must add the deferral to
  follow-ups AND resurface it on turn 5 (behavior matcher accepts
  "publication" / "paper" / "earlier you mentioned" / "graph
  neural").
- 8/8 LLM scenarios green on the live API. Commit `a2699d8`.

### Slice 1F: `web_search` tool via function-wrapped OpenAI built-in

The user's original ask included "you have all the capabilities to
access urls if provided or browse web yourself." Slice 1A gave the
GitHub-URL path (`fetch_github_readme`); Slice 1F delivers the
general-web path.

The non-obvious decision (worth preserving for future readers):

**OpenAI's built-in `{"type": "web_search"}` is INCOMPATIBLE with
JSON mode.** The API returns:
```
400 - "Web Search cannot be used with JSON mode."
```
Our intake contract REQUIRES `text.format = json_object` (structured
envelope with `draft_updates` / `assistant_message` / `status` /
etc.). Removing JSON mode would force ad-hoc parsing and degrade
reliability. So the naive "add `web_search` to the tool list"
approach silently 400'd every intake turn and the service fell back
to the regex step-machine — exactly the silent-fallback pattern
Slice 1D pact-tests were built to catch. The agentic eval surfaced
the regression immediately: 3/10 passing.

The function-wrap is the fix:
- `web_search` is exposed as a FUNCTION tool to the agent (`{"type":
  "function", "name": "web_search", "parameters": {"query": ...}}`).
- When the agent calls it, the dispatcher fires a SEPARATE inner
  `responses.create` — WITHOUT `json_object`, WITH OpenAI's built-in
  `{"type": "web_search"}` enabled — and returns the synthesized
  text as the function_call_output.
- Main loop stays JSON-mode-safe; the agent gets a research
  capability on-demand.
- Zero new dependencies, no new API key, no new HTTP client. Same
  shape as `fetch_github_readme` from the loop's perspective.

Cost shape: each invocation = one extra `responses.create` call
(gpt-5.4-mini, ~600 tokens). Realistic usage per session: 0-2
invocations (prompt explicitly tells the agent "use SPARINGLY").
Latency: +1-2s per search.

The prompt teaches the agent:
- DO use it for: "what does a Senior MLE role at Anthropic typically
  expect?", "what's standard for a fintech compliance officer
  resume?", "compare Stripe vs Adyen engineering bar".
- DO NOT use it for: anything the user already shared, generic
  resume advice, small talk, speculative queries ("what salary will
  I get?" — refuse politely instead).
- When citing, attribute the source ("based on what I read on
  Levels.fyi…") rather than asserting as fact.

Hermetic tests (`tests/backend/test_resume_builder_tools.py`,
6 new cases via a stubbed OpenAI client):
- success path returns synthesized text + asserts the inner call
  does NOT use json_object format
- empty query → reject
- no openai_service → structured error
- inner-call exception → captured as `search_dispatch_failed`,
  never raised across the tool boundary
- oversize result → truncated at 8 KB with `…[truncated]` marker
- `execute_tool` does NOT leak `openai_service` into
  `fetch_github_readme`'s kwargs (would crash since fetch is
  HTTP-only)

Conversational eval scenarios (2 new):
- `web_search_fires_on_external_context_question`: user asks
  "what does Anthropic typically look for on a Senior MLE resume?"
  → agent fires web_search → grounded answer with source attribution
- `web_search_skipped_for_user_provided_info`: user is sharing their
  own background → agent does NOT burn a search (no "according to"
  citations in the reply)

Verification:
- 145 hermetic tests across affected suites green
- 10/10 LLM scenarios pass on the live API on the first calibrated
  run. Inspection of the external-context scenario shows the model
  fires `web_search` ONCE, receives a grounded answer ("Anthropic's
  Senior MLE postings tend to emphasize strong Python + ML +
  software engineering, production ML systems, and measurable impact
  like scale, latency, reliability, or cost improvements..."), and
  synthesizes a tailored reply with no hallucination.

Commit `674c994`.

### ADR-031: documenting the whole arc

`docs/adr/ADR-031-resume-builder-agentic-architecture.md` records the
architecture decisions across Slices 1A through 1F:
- Native Responses-API tool calling over LangGraph (zero clear
  value-add at this scope for an enormous dependency cost)
- `run_tool_loop` lives on `OpenAIService` (cross-cutting concerns
  like budget + cost-trace already live there)
- Iteration cap = 12 (raised from 5 after the QA replay caught the
  serial-fetch regression)
- Tool registry + JSON-error contract (errors are first-class
  outputs, never raised across the tool boundary)
- The function-wrap pattern for `web_search` (and the JSON-mode
  incompatibility rationale)
- Schema-strictness pact-tests as mandatory CI guard against the
  `dict[K, V]` silent-400 trap
- Pair-registry pact-tests as mandatory CI guard against the
  silent-fallback drift class (the
  `RESUME_THEMES` vs `SUPPORTED_THEMES` bug that surfaced this
  session is the canonical example)
- Character-budget history slicing (replaces the hard `[-12:]` cap)
- `proactive_offer` as a distinct JSON channel + click-to-accept
  chip in the UI
- `pending_followups` with the TRIGGER PRIORITY rule for open-ended
  questions

The ADR explicitly names the trade-offs we're NOT making (no
LangGraph, no external search provider yet, no UI surface for
`pending_followups`, eval at 10 not 15-20) and the follow-ups
parked for Phase 3 (eval expansion, external search provider eval,
UI surface, multi-provider agentic eval).

### Session arc, end-to-end

The user's original three complaints, all resolved:

| Complaint | Resolution |
|---|---|
| Agent hallucinated URL-fetching capability | `fetch_github_readme` tool + honesty patch (1A) |
| "Each new question feels like a fresh GPT instance" | Full conversation history with char-budget guard (1B) |
| Agent forgot deferred commitments | `pending_followups[]` with TRIGGER PRIORITY (1E) |

Plus two silent-fallback bugs that lived in production for weeks
were caught + pact-tested:
- Schema 400 on `dict[K, V]` (the structuring LLM had been failing
  on every export since the schema landed — see Day 58)
- Theme registry drift (4 of 6 themes silently rendering as
  classic_ats since Phase 2a — see Day 58)

Phase 1 + Phase 2 of the parked agentic-upgrade plan: **shipped**.
What's parked for Phase 3: eval expansion to 15-20 fixtures, an
optional `pending_followups` UI panel, external web-search provider
integration (only if a quality gap surfaces), and a multi-provider
agentic eval when ADR-028 D1 lands.

## Day 60: Slice 1G — multi-provider agentic eval (and the THIRD silent-fallback bug)

Phase 2's parked "multi-provider agentic eval when ADR-028 D1 lands"
got pulled forward by the operator's question: *is gpt-5.4@medium
actually the right model for this surface, or would Sonnet 4.5 / one
of the other strong models do better?* Built the eval, ran it across
the planned candidate slate, found the answer.

### What landed

**`tests/quality/openrouter_eval_service.py`** — new adapter.
``OpenRouterEvalService`` is a duck-type of
``OpenAIService.run_tool_loop`` that routes through OpenRouter's
Chat-Completions endpoint. Sits next to the existing
``KimiEvalService`` (which only does plain JSON-prompt suites; the
agentic eval needs the tool-loop translation glue). Translates:

  - Responses-API tool spec ``{"type":"function","name":...}`` to
    Chat-Completions ``{"type":"function","function":{...}}``
  - OpenAI's ``function_call`` items in ``response.output`` to
    Chat-Completions ``message.tool_calls`` + role:"tool" results
  - JSON parsing — see the bug section below.

Tied off with 22 hermetic tests
(``tests/backend/test_openrouter_eval_service.py``): translation
shapes, parallel tool calls in one iteration, iteration-cap
exhaustion, executor exceptions captured as tool outputs not raised
across the boundary, markdown-fence handling.

**`tests/quality/resume_builder_agentic_runner.py`** — refactored
to multi-candidate mode. ``--candidates`` flag accepts ``all`` (=
openai baseline + every OpenRouter slug in ``_AGENTIC_CANDIDATES``)
or a comma-list. Auto-skips the 2 ``web_search`` scenarios for
non-openai providers (the function-wrap uses an inner OpenAI
Responses-API call to OpenAI's built-in search; no Chat-Completions
equivalent). Prints a candidate × scenario PASS/FAIL matrix +
per-candidate totals. JSON report carries the per-candidate result
list so a comparison script can diff runs.

Candidate slate matches ``report.md`` §4 (ADR-028 D1 blueprint),
slug-corrected against the live OpenRouter catalogue, plus
Anthropic Sonnet 4.5 as the operator's explicit add:

    sonnet-4.5 = anthropic/claude-sonnet-4.5
    gemini     = google/gemini-3.1-pro-preview
    kimi       = moonshotai/kimi-k2.6
    glm        = z-ai/glm-5.1
    grok       = x-ai/grok-4.20
    deepseek   = deepseek/deepseek-v4-pro
    qwen       = qwen/qwen3.6-max-preview

**`scripts/compare_multi_provider_eval.py`** — comparison helper.
Loads two eval JSON reports + classifies each remaining failure as
``regex_fallback`` (every assistant_reply is a canonical step-machine
message AND no tool_events — the adapter raised on every turn, the
service caught it, the deterministic intake ran), ``partial_fallback``
(some turns succeeded, some fell back — sporadic parse issue), or
``model_behavior`` (the model ran cleanly and the behavior didn't
match — REAL signal). Catches the difference between adapter bugs
and genuine cross-provider capability gaps.

### THE BUG (silent-fallback #3)

The first run (v1, all 8 candidates × 8 cross-provider scenarios)
came back with:
  openai 10/10 · **sonnet-4.5 2/8** · gemini 5/8 · kimi 3/8 ·
  glm 6/8 · grok 6/8 · deepseek 5/8 · qwen 5/8

Sonnet at the BOTTOM was suspicious. The comparison script's
classifier found why: **every single sonnet failure was
``regex_fallback``** — every turn, the OpenRouter adapter raised
``AgentExecutionError("returned invalid JSON")``, the resume-builder
service caught it and ran the deterministic step-machine.

Root cause: Anthropic models through OpenRouter ignore the
``response_format={"type":"json_object"}`` hint and wrap their JSON
output in markdown code fences:

    ```json
    {
      "draft_updates": {...},
      "assistant_message": "...",
      ...
    }
    ```

Anthropic's own API doesn't have a native JSON-mode constraint, so
the OpenRouter shim's prompt-coerced "respond in JSON" reads to
Claude as "format the JSON nicely". My adapter's bare
``json.loads(content)`` rejected the fences → silent fallback.

Other providers wrap intermittently — kimi, gemini, deepseek showed
partial fallbacks; glm/grok/qwen mostly emit bare JSON. Sonnet 4.5
wraps consistently.

Third silent-fallback bug of the session — same pattern as the
schema-400 bug (Slice 1C) and the theme-registry drift bug (between
Slices 1C and 1D). Each lived in production for weeks because the
fallback path was "good enough" to mask the failure.

### THE FIX

``_parse_provider_json(content)`` in the OpenRouter adapter:

  1. Fast path — bare JSON
  2. Strip markdown fences (`` ```json ... ``` `` or `` ``` ... ``` ``)
     and retry
  3. Last-ditch: extract the first balanced ``{...}`` substring (with
     string-literal awareness so braces inside JSON strings don't
     throw the count off) and retry

Wired into both ``run_tool_loop`` and ``run_json_prompt`` so the same
fix covers both code paths. 9 new hermetic tests pin the parser
behavior down: bare JSON, ```json fence, ``` fence, ```JSON
(uppercase tag), JSON wrapped in prose, balanced-brace extraction
with embedded `{`/`}` inside strings, empty input, unparseable
input, end-to-end loop with a fenced response.

### V2 RESULTS (post-fence-fix)

    candidate    v1     v2    change
    openai       10/10  10/10   -
    sonnet-4.5    2/ 8   6/ 8  +4   ← all 4 of those were regex-fallback
    gemini        5/ 8   6/ 8  +1
    kimi          3/ 8   5/ 8  +2
    glm           6/ 8   6/ 8   -
    grok          6/ 8   6/ 8   -
    deepseek      5/ 8   6/ 8  +1
    qwen          5/ 8   5/ 8   -

The classifier on v2 remaining failures:

    regex_fallback     : 0    (the fix eliminated this class entirely)
    partial_fallback   : 5    (occasional adapter parse hiccups)
    model_behavior     : 11   (the real cross-provider signal)

### What the model-behavior failures actually tell us

Five scenarios are universal PASS across every provider:
  - honesty_on_linkedin_scrape
  - proactive_offer_after_enough_signal
  - proactive_offer_silent_mid_basics
  - multi_turn_correction_preserved
  - non_github_url_no_fetch (except grok over-eagerly fired
    fetch_github_readme on a non-github URL)

The differentiators are three specific behaviors:

  - **`github_url_fires_tool`** — only openai, glm, grok call the
    tool reliably when given a github.com URL. Sonnet / gemini /
    kimi / deepseek / qwen sometimes ask the user a clarifying
    question first before committing. **Tool-use discipline
    differs by provider.** Not a "wrong" behavior — different style.
  - **`promise_tracking_remembers_deferred_publication`** — half
    the providers (openai, sonnet, glm, deepseek) add the deferred
    publication to ``pending_followups[]`` reliably; gemini, kimi,
    grok, qwen miss it. **Multi-turn memory discipline differs.**
  - **`structured_payload_runs_after_generate`** — only openai and
    grok pass. The structuring LLM call (a SEPARATE path from the
    agentic loop, fires only when generate_resume_builder_resume is
    invoked) uses an ~11K-char prompt with worked BEFORE/AFTER
    examples. Most OpenRouter providers drop a field or malformed-
    JSON it. **Heavy structured-output prompts are where the OpenAI
    Responses-API strict-schema mode shows its value most clearly.**

### Headline conclusion (for the operator question)

**Sonnet 4.5 ties — does not beat — the strong OpenRouter providers
at 6/8 on the cross-provider scenarios.** No clean "switch to
Sonnet" signal on this workload. The 25% gap to gpt-5.4 baseline
(6/8 vs 8/8) concentrates in two specific behaviors (github tool
firing + structured-output reliability under heavy prompts).

**Recommendation: keep gpt-5.4@medium as the default agent.**
Sonnet, gemini, glm, grok, deepseek are all viable failover targets
for non-PII workloads under ADR-028 D1's criteria — they cluster
tightly enough that the choice between them on capability is a
wash; pick on cost / EU posture / outage diversification instead.

### Artifacts preserved

`docs/eval-runs/2026-05-21-agentic-eval-v1-pre-fence-fix.json` and
`docs/eval-runs/2026-05-21-agentic-eval-v2-post-fence-fix.json` —
both raw eval reports, indexed by candidate, with full
assistant_replies, tool_events, and findings preserved for future
re-analysis. Re-running the eval after a prompt change is one
command: `uv run python tests/quality/resume_builder_agentic_runner.py
--candidates all --json out.json`.

### Lesson for future readers

This is the **third silent-fallback bug** found this session. All
three followed the same shape: two configs/contracts that should
have matched drifted apart, downstream code silently fell back to a
"safe default" instead of erroring loudly, and the bug only
surfaced when a measurement (eval / replay / md5 comparison) forced
the question. The pattern is so consistent it's worth naming:
**the silent-fallback antipattern**.

Three pact-tests now defend the architecture against this class:

  1. `test_llm_schema_strictness` — every Pydantic schema wired to
     `run_structured_prompt` must produce a JSON Schema with no
     `dict[K, V]` patterns and no multi-branch unions (the
     schema-400 trap)
  2. `test_resume_themes_registry_matches_supported_themes` — the
     RESUME_THEMES gate must list every theme in SUPPORTED_THEMES
     (the registry-drift trap)
  3. `test_parse_provider_json_*` — the OpenRouter adapter parser
     must tolerate markdown-fenced JSON (the provider-quirk trap)

If a fourth silent-fallback bug surfaces, the right move is to
generalise these into a shared "bug-class regression" pattern in
the test suite. For now, three is enough to make the lesson sticky
without over-engineering the abstraction.

### Addendum: the conversational-quality re-read

The pass/fail matrix above compresses something the operator caught
by reading the actual replies — **several "failures" are
conversationally SUPERIOR to the OpenAI baseline**, and the eval
matchers were too narrow to see it.

The clearest example: on `github_url_fires_tool`, the user pastes
`https://github.com/openai/openai-python` saying "here's a project of
mine" — but that's the famous OpenAI Python SDK, almost certainly
NOT the user's own project. The strongest models noticed:

  - **Sonnet 4.5** (FAIL per matcher): *"I see that's the official
    OpenAI Python SDK repository maintained by OpenAI. Is this a
    project you contributed to, or did you mean to share a different
    personal project?"*
  - **Gemini** (PASS): *"...since this is a major open-source
    project, what were your specific contributions or the measured
    impact of your work on it?"*
  - **DeepSeek** (FAIL per matcher): *"I pulled up the README for
    that repo — but it's the official openai/openai-python SDK
    maintained by OpenAI, not a personal project. Did you mean to
    share a different repo, or did you contribute to this one?"*
  - **OpenAI** (PASS): *"Got it — I read the README and captured
    the project as the OpenAI Python API library..."* (committed
    without questioning)

Sonnet 4.5 / Gemini / DeepSeek caught the user-error trap; OpenAI
just committed the famous OSS repo to the user's resume. Whose
behavior is the eval reading correctly?

Same pattern on `promise_tracking`: every provider resurfaced the
deferred publication on turn 4 — but 4 of them (gemini, kimi, grok,
qwen) "failed" because they didn't write the structured
`pending_followups[]` JSON field. The chat the user sees is
identical; only the bookkeeping channel is different.

Two failure classes once you read replies:

  - **Class A (USER NEVER SEES):** structured_payload_runs_after_
    generate failing on most non-openai providers (the 11K-char
    structuring prompt stretches them); pending_followups[] field
    not populated on ACK. Both are structural / schema gaps, not
    conversational ones.
  - **Class B (USER ACTUALLY SEES):** qwen still does
    promise-but-don't-fire (the original bug pattern that started
    this whole session — only provider that still does this);
    grok over-fires tools (3 web_search + 1 fetch on a single
    project URL); kimi adapter hiccups intermittently.

Re-classified picture for "how would a real user feel after a
session?":

  - **Chat-first tier (smart clarifications, catches user errors):**
    Sonnet 4.5, Gemini, DeepSeek
  - **Solid baseline tier (no smart-clarification but reliable):**
    OpenAI gpt-5.4, GLM, Grok
  - **Mixed tier (real issues):** Kimi (adapter intermittency),
    Qwen (promise-but-don't-fire)

**Recommendation update:** OpenAI gpt-5.4 stays default for the
FULL pipeline (it's the only provider that handles the structuring
pass reliably). But if a future slice wants to A/B the
conversational intake specifically — Sonnet 4.5 / Gemini / DeepSeek
would arguably feel SMARTER than OpenAI to the user. They catch
user-error patterns OpenAI's baseline misses.

Full per-scenario reply analysis preserved in
`docs/eval-runs/2026-05-21-conversational-quality-assessment.md`.

Phase 3 candidate the data surfaces: the current eval matchers
can't distinguish "committed without question" (PASS) from "asked
smart clarifying question" (FAIL but BETTER) from "hallucinated
capability" (FAIL and WORSE). A v2 rubric with LLM-as-judge
1-5 quality scoring per scenario would catch this honestly.
Parked.


## Day 61: Workspace assistant — history fix, product-knowledge block, adapter reasoning_effort, and Slice 1K eval

Today extended the agentic-upgrade work to the OTHER chat surface
in the app: the workspace assistant (`src/assistant_service.py`,
prompts at `prompts/assistant/v1.json` and
`prompts/assistant_text/v1.json`). The audit found the SAME
history-truncation bug the resume builder had at the start of
Slice 1B — except worse: assistant code was at `history[-4:]`,
whereas the resume builder had been at `history[-12:]`. Four
turns is not enough for any real conversation.

### Slice 1J: drop the `history[-4:]` slice on the assistant prompts

New constant `ASSISTANT_HISTORY_CHAR_BUDGET = 18000` (smaller than
the resume builder's 30 k because the assistant carries a heavier
`assistant_context` payload alongside — workspace_state +
workflow_context + the WORKSPACE STATE guidance rules). Both
`build_assistant_prompt` and `build_assistant_text_prompt` now
call `_slice_history_for_budget(history, max_chars=...)` instead
of the hard suffix slice. Same drop-oldest-first semantics as the
resume builder, with the most-recent turn guaranteed retained.

Why this matters concretely: the Slice 1K `long_session_memory_callback`
scenario is a 7-turn conversation where the user states "we cut
chargeback fraud by 18% using XGBoost" on turn 2, then on turn 6
asks "what number did I tell you?". With `history[-4:]` the model
sees turns 3-6 ONLY — the 18% fact has scrolled off and the
question is literally unanswerable. After the fix, all 5 candidates
in the Slice 1K eval correctly recalled "18%".

### Slice 1J': `_PRODUCT_KNOWLEDGE_BLOCK` — stop sounding ignorant

The WORKSPACE STATE block teaches the assistant how to READ live
runtime state but said nothing about pricing, themes, the agentic
pipeline, or the assistant's own limits. When a user asked "what
tiers do you have?" / "what themes can I use?" / "can you book
me an interview?", the answers ranged from "I don't have that
info" to outright fabrications.

Added a new module-level constant in `src/prompts.py` that's also
pre-baked into both registry JSONs (Pattern A per the prompt-
registry migration notes). It backstops all of these questions
with authoritative numbers pulled from `backend/tiers.py`
(TIER_CAPS), `src/resume_builder.py` (RESUME_THEMES),
`backend/tiers.py` (FREE_EXPORT_FORMAT/THEME), and `src/agents/*`
(the orchestrator chain):

  * **Tier caps**: Free / Pro / Business — tailored applications
    (3 / 20 / 80), assistant turns (20 / 150 / 500), resume parses
    (3 / 25 / 100), saved jobs (5 / 1000 / unlimited), saved
    workspaces (1 / 5 / unlimited), retention (7 days / 30 days /
    unbounded).
  * **Lifetime gotcha**: resume_builder_sessions on Free is
    LIFETIME (never resets), monthly on Pro (3) / Business (15).
    The block calls this out verbatim so the model stops
    answering "resets monthly" by reflex.
  * **Theme inventory**: six themes (classic_ats,
    professional_neutral, modern_blue, creative_warm,
    architect_mono, presentation_twocol); first five are
    single-column ATS-safe; presentation_twocol is gated +
    non-ATS.
  * **Export entitlement**: Free = PDF + professional_neutral
    only; Pro/Business = PDF or DOCX + any theme.
  * **Agentic chain**: tailoring → review → resume gen → cover
    letter, with conservative-correction posture in the review
    pass.
  * **Honest cannot-do list**: schedule interviews, send emails,
    log in to LinkedIn / Indeed, scrape arbitrary URLs, edit the
    resume file directly, change subscription tier, remember
    across sessions when signed out.

If any of these source-of-truth numbers ever drift, the
byte-mirror tests
(`test_assistant_prompt_matches_pre_migration_system_byte_for_byte`)
fail on the next CI run.

### Slice 1J'': thread `reasoning_effort` through both eval adapters

`OpenRouterEvalService.run_tool_loop`, `run_json_prompt`, and
`run_structured_prompt` — plus the symmetric `KimiEvalService._chat`
+ entry points — now forward the `reasoning_effort` kwarg to
`chat.completions.create`. Conditional (only when truthy) because
non-reasoning slugs (Sonnet, Haiku, DeepSeek v4) 400 if it's set.

Added pricing entries for the new Slice 1K candidates:
`openai/o4-mini` ($1.10 / $4.40 per Mtok — substituted for the
non-existent `openai/gpt-5.1-mini`) and `anthropic/claude-haiku-4.5`
($1.00 / $5.00 per Mtok).

Bonus bugfix from the Slice 1K smoke run: the
`OpenRouterEvalService.run_json_prompt` path was never
accumulating `response.usage` into the snapshot — only
`run_tool_loop` was. The smoke at first reported $0.0000 for
every call. Mirrored the accumulator into the single-shot path so
the assistant / parser / structuring suites all surface accurate
per-call cost.

### Slice 1K: 5-candidate assistant eval (12 scenarios)

New runner `tests/quality/assistant_agentic_runner.py` — mirrors
the Phase B incremental-checkpoint + heartbeat pattern but
targets the assistant prompt surface directly via
`build_assistant_prompt` + `run_json_prompt`. Twelve scenarios
across product-knowledge fluency, honest refusals, grounding
discipline, and multi-turn memory. Substring-matcher rubric with
the same normalisation (smart quotes / em-dashes) as Slice 1H.

Candidate slate (user-approved after dropping Opus + substituting
o4-mini for the non-existent gpt-5.1-mini): gpt-5.4@med,
gpt-5.4-mini@med, o4-mini@high, sonnet-4.5, haiku-4.5.

Headline result (full per-candidate × per-scenario data in
`docs/eval-runs/2026-05-21-assistant-eval-full.json`):

  | candidate         | avg   | pass  | wall    | cost   |
  | gpt-5.4@med       | 0.986 | 1.000 | 74.7s   | $0.094 |
  | gpt-5.4-mini@med  | 1.000 | 1.000 | 40.5s   | $0.018 |
  | o4-mini@high      | 1.000 | 1.000 | 117.3s  | $0.081 |
  | sonnet-4.5        | 1.000 | 1.000 | 161.3s  | $0.116 |
  | haiku-4.5         | 0.917 | 0.917 | 37.6s   | $0.038 |

**Surprise:** `gpt-5.4-mini@med` is the winner on all three axes
— quality 1.000, fastest at 40 s, cheapest at $0.018 (1/5 the
cost of gpt-5.4@med which scored 0.986). The assistant surface
is mostly retrieval-and-refuse: pulling facts from the new
product-knowledge block, declining off-topic asks, recalling
earlier turns. Heavy reasoning is wasted; smart-but-cheap wins.

The two sub-1.0 scores re-classify cleanly:
  * `gpt-5.4@med` :: `off_topic_movie` (0.833) — matcher-bug:
    the model's "I can only help with your job application
    workflow here" is a textbook refusal but wasn't in the
    `one_of` rubric. Real behavior = PASS.
  * `haiku-4.5` :: `quota_resume_builder_lifetime` (0.000) —
    real JSON-mode fidelity miss; haiku returned content that
    didn't parse. The other 11 scenarios were valid JSON. Same
    drift pattern Phase B caught for parser/JD on Anthropic
    via OpenRouter (~92 % reliability).

**Recommendation:** route the workspace-assistant default to
`openai/gpt-5.4-mini` at `reasoning_effort=medium`. This is a
real departure from the resume-builder default (gpt-5.4) and the
Phase B verdict (gpt-5.4 for parser/JD/analysis); the surface
characteristics genuinely differ. Expected ~80 % savings on
assistant API spend. Full read-out in
`docs/eval-runs/2026-05-21-assistant-eval-report.md`.

Slice 1J's history fix paid off concretely: all 5 candidates
correctly recalled the "18 %" fact from turn 2 in a 7-turn
session — unscorable before the fix.

### Slice 1K addendum: `gpt-5.4-mini@low` sweep

Since mini@med scored 1.000 the obvious next question was
whether `reasoning_effort=medium` was earning its keep on the
assistant surface. Added `gpt-5.4-mini@low` to the candidate
slate and re-ran the same 12 scenarios. Result: also perfect
1.000, but 32 % faster (27.6 s vs 40.5 s) and 15 % cheaper
($0.0155 vs $0.0183). Verified answer quality directly on the
hardest scenarios (long-session callback, multi-turn correction,
pricing-tier numeric recall) — no degradation.

**Refined recommendation:** route the workspace-assistant
default to `openai/gpt-5.4-mini` at `reasoning_effort=low`. The
assistant surface is retrieval-and-refuse; thinking-token spend
beyond "low" earns nothing on this rubric. Artifacts:
`docs/eval-runs/2026-05-21-assistant-eval-mini-low.json`.

### Resume-builder × mini sweep (does the cost story transfer?)

Slice 1K's mini@low win on the workspace-assistant surface
prompted the natural followup: does it hold on the much heavier
resume-builder surface (tool loop, multi-turn intake,
proactive_offer + pending_followups channels, the 11 K-char
structuring-pass canary)?

Wired `gpt-5.4-mini@med` + `gpt-5.4-mini@low` into
`tests/quality/resume_builder_agentic_runner.py` (changed
`_AGENTIC_CANDIDATES` from `dict[str, str]` to
`dict[str, dict]` carrying `slug` + `reasoning_effort` per
candidate). Added `default_reasoning_effort` to
`OpenRouterEvalService.__init__` so the eval matrix can inject
the effort tier per candidate without touching the production
`resume_builder_service` caller; the per-call kwarg falls back to
the instance default when production code doesn't pass one.

Result on the same 16 OpenRouter scenarios:

  | candidate         | raw   | eff   | lat    | cost   |
  | gpt-5.4-mini@med  | 14/16 | 16/16 | 247s   | $0.144 |
  | gpt-5.4-mini@low  | 15/16 | 16/16 | 200s   | $0.127 |

Re-classifying the raw fails: both candidates trip the curly-
apostrophe matcher bug Slice 1H flagged ("can't" / "couldn't"
with U+2019). Real behavior PASSES on every flagged miss — the
resume-builder runner just never got the normalisation patch the
assistant runner has.

Compared to Slice 1H baselines on the same 16 scenarios:
gpt-5.4-via-OR scored 16/16 effective at 8.3 s / scenario and
roughly $0.12. Sonnet-4.5 scored 14/16 (1 real fail on
`structured_payload`) at $0.98. So mini matches gpt-5.4 quality
AND beats Sonnet/Gemini/DeepSeek on this surface (which all
failed `structured_payload` and/or `proactive_offer`).

But — and this is the important finding — on this surface the
mini cost story DOES NOT transfer:

  * gpt-5.4-via-OR: 8.3 s / scenario, ~$0.12 total
  * mini@low:       12.5 s / scenario, $0.127 total
  * mini@med:       15.4 s / scenario, $0.144 total

Mini's 5x per-token discount is eaten by reasoning-token
overhead. On the short retrieve-and-refuse assistant surface
reasoning_effort barely fires; on the long multi-turn agentic
resume-builder surface the model thinks before AND after each
tool call. Net cost ends up similar to gpt-5.4 — and latency is
50-85 % higher.

**Recommendation:** keep `gpt-5.4` as the resume-builder
default. mini doesn't earn the switch on this surface. The
finding is genuinely surface-specific:

  * Workspace assistant → mini@low (Slice 1K result holds)
  * Resume builder      → gpt-5.4 (Slice 1H result holds)

Design lesson worth keeping: reasoning models shine when the
inference is short and structured; they're a wash when the
agentic loop is already providing the "reasoning" externally.

Full read-out:
`docs/eval-runs/2026-05-21-resume-builder-mini-eval-report.md`.
Artifacts:
`docs/eval-runs/2026-05-21-resume-builder-mini-eval.json`.

### Followup: `gpt-5.4@low` — explicit-low effort is WORSE than default

User hypothesis: `openai-via-or` in Slice 1H ran gpt-5.4 at the
model's default reasoning_effort (no kwarg). If gpt-5.4 default
routing through OpenRouter applied some implicit reasoning,
explicitly setting `low` might cut it for a faster/cheaper run.

Disproven. Same 16 scenarios:

  | candidate                | eff   | lat/scn  | cost   |
  | openai-via-or (default)  | 16/16 |  8.3s    | ~$0.12 |
  | gpt-5.4@low (new)        | 16/16 | 18.4s    | $0.647 |

Explicit `reasoning_effort=low` is **5x more expensive and 2x
slower** than the default-routing baseline. The default OR routing
for gpt-5.4 apparently skips reasoning entirely (or uses
near-minimal); explicit "low" forces some reasoning budget where
default forced none.

Useful design lesson: **don't assume "low reasoning_effort"
means "cheaper than default"** — it depends on what the model's
default routing was already doing. For gpt-5.4 via OpenRouter,
default is effectively zero-reasoning; "low" is *more* than zero.

Qualitative inspection: gpt-5.4@low does produce slightly smarter
replies on a few edge cases (best summary draft of any candidate
on `proactive_offer_after_enough_signal`; partial smart-
clarification on the OSS-repo trap in `github_url_fires_tool`).
But the gain is on ~10-20% of scenarios; doesn't justify 5x cost.

Final resume-builder verdict UNCHANGED: keep gpt-5.4 at default
routing as production default. mini@low remains valid
cost-equivalent backup. gpt-5.4@low is strictly dominated.

Full surface ranking:

  | candidate              | eff   | per-scn | $/scn   |
  | openai-via-or (default)| 16/16 |  8.3s   | $0.008  |  <- prod default
  | mini@low               | 16/16 | 12.5s   | $0.008  |  <- backup
  | mini@med               | 16/16 | 15.4s   | $0.009  |
  | sonnet-4.5             | 14/16 | 17.1s   | $0.061  |
  | gpt-5.4@low            | 16/16 | 18.4s   | $0.040  |  <- dominated

Artifacts:
`docs/eval-runs/2026-05-21-resume-builder-gpt54-low-eval.json` +
`…-log.txt`. Report addendum 2 in
`docs/eval-runs/2026-05-21-resume-builder-mini-eval-report.md`.

### Production change: assistant reasoning_effort medium → low

Acted on the Slice 1K addendum verdict. One-line change in
`src/config.py`: `OPENAI_REASONING_ASSISTANT` default lowered
from `"medium"` to `"low"`. Operators can still override via env
var if a regression surfaces.

The assistant model was ALREADY `gpt-5.4-mini` in production —
the only thing the eval data was prompting us to flip was the
effort tier. `assistant_product_help` was already at "low";
`assistant_application_qa` stays at gpt-5.4@high (it's the
substantive Q&A scope where the user has analysis context).

One test assertion updated:
`test_openai_service_uses_default_reasoning_for_unified_assistant_task`
now asserts `{"effort": "low"}` with a comment explaining the
Slice 1K provenance. 78 / 78 relevant tests green; the one
pre-existing failure in `test_workspace_retention.py::
test_sweep_with_no_service_role_client_logs_and_returns_zero`
was already failing on main before this commit (verified via
stash + re-run).

Expected impact: ~80% reduction in assistant API spend, ~30%
lower per-turn latency. Quality holds at 1.000 per the Slice 1K
data. No frontend changes required.

### Fix: assistant product-knowledge block claimed 6 themes (only 5 ship)

The `_PRODUCT_KNOWLEDGE_BLOCK` added in Slice 1J' listed six resume
themes including `presentation_twocol` as "a two-column designer
layout flagged non-ATS". Wrong — `presentation_twocol` is HELD from
users: the two-column engine ships dormant in the renderer but is
removed from every user-facing surface (`ArtifactTheme` in
`api-types.ts`, `THEME_OPTIONS` + `THEME_HINT` in
`ArtifactViewer.tsx`, the `workspace_models` Literal) pending the
designer-grade rework parked in `report.md` ("Designer-grade theme
expansion v2"). The assistant would have told users they could
export in a two-column theme the picker doesn't offer.

Corrected the block to name the FIVE themes users can actually pick
(professional_neutral, classic_ats, modern_blue, creative_warm,
architect_mono — all single-column, all ATS-safe) and to explicitly
tell the assistant there is no two-column option today so it answers
honestly if asked. Re-baked into both registry JSONs; byte-mirror
tests green (33/33 prompts + registry).

### Export audit: 2 DOCX bugs fixed + typography unified to one font

Operator asked for a side-by-side PDF-vs-DOCX comparison of the
résumé export across all 5 themes "to ensure DOCX is working as
intended." Generated both formats for every theme and audited the
DOCX XML structure directly (Word COM rendering was too flaky under
the harness; structural XML inspection is more precise anyway).
Content fidelity was perfect (all 5: every section, 0 empty
paragraphs, correct theme colors) — but the audit caught two real
PDF-vs-DOCX divergences:

1. **Missing role/headline line in the DOCX.** The HTML/PDF header
   builders render `artifact.target_role` as an uppercase muted line
   between the name and contact (`.resume-classic-role`, added
   2026-05-19) — but `_docx_add_resume_header` was missed in that
   change, so a JD-tailored résumé showed its role on the PDF and
   not the DOCX. Added the role paragraph to the DOCX header builder
   (omitted when target_role is "", same as the PDF).

2. **Dates not flush-right in the DOCX.** The role/education date
   rows use a right-aligned tab stop. The position was computed as
   `7.1 - 2 * margin` — but 7.1 was ALREADY the content width
   (8.5in Letter − 2×0.7in margins), so the margins were subtracted
   twice and every date landed at 5.70in instead of 7.1in — ~1.4in
   short of the right margin. Added an explicit
   `_DOCX_LETTER_WIDTH_INCHES = 8.5` and corrected the tab stop to
   `letter_width − 2×margin = 7.1in`.

Then — separate operator request, same export surface — **unified
the typography**: all 5 themes now use ONE font family
(Arial / Helvetica sans), the `modern_blue` family the operator
liked. Previously professional_neutral was all-Georgia serif, and
classic_ats + creative_warm had Georgia headings. Changed the
`body/h1/prose` font fields (HTML + DOCX) on those three themes;
modern_blue + architect_mono were already all-Arial. Themes now
differentiate by COLOUR, PAPER, and HEADER TREATMENT only — not
typeface. Cover letters were covered automatically (they read the
same ThemeSpec `prose_font_family` / `docx_*_font` fields), so
résumé + cover letter are now a uniform matched set on font family.
Font SIZES deliberately left per-document (résumé body ~10.5pt,
cover letter body 11.4pt) — only the family was unified.

Stale "Georgia / serif" comments across `src/exporters.py` updated
to match. Tests: `test_export_docx_bytes_renders_full_resume_*`
paragraph indices bumped for the new role line; the two
font-assertion tests (classic_ats / professional_neutral) inverted
to expect Arial-only. 32/32 exporter tests + renderer-fidelity
runner (OVERALL PASS) green.

Follow-up fix — flaky DOCX byte-comparison tests. Two tests in
`test_exporters.py` compared raw `.docx` bytes. A `.docx` is a ZIP
and python-docx stamps the current mtime into every entry header,
so two renders a second apart differ byte-wise even with identical
content:
  * `test_export_docx_bytes_unknown_theme_falls_back_to_classic_ats`
    asserted `fallback_bytes == classic_bytes` — intermittently
    failed across a DOS-timestamp boundary (~1-in-5).
  * `test_export_docx_bytes_themes_produce_different_outputs`
    asserted `classic_bytes != neutral_bytes` — never failed, but
    vacuous: timestamps alone make the bytes differ, so it would
    pass even if the theme switch were entirely broken.
Both rewritten to compare EXTRACTED content via the existing
helpers — `_docx_paragraph_pairs` + `_docx_run_color_hexes` +
`_docx_run_font_names` (equal for the fallback test, color-set
differs for the themes test). Deterministic now; confirmed stable
5/5 consecutive runs. 32/32 exporter tests green.

## Day 62: Résumé-builder UX fixes from user testing

The operator drove a real build through the conversational résumé
builder and surfaced five issues. All five fixed.

### Section order — projects-led path for portfolio candidates

A generated résumé came out **Summary → Education → Projects →
Skills** — Education above Projects, Skills stranded on page 2.
Root cause: `compute_section_order` (`src/resume_builder.py`)
checked `exp_count == 0` BEFORE `proj_count >= 2`, so a self-taught
engineer with four metric-heavy projects and no formal jobs was
routed onto the "fresh student" education-first path. Fixed by
checking the projects-led path first: 2+ projects → skills +
projects lead, whoever you are. A genuine fresh grad (0 jobs, <2
projects) still gets education-first. One mislabeled test
(`..._routes_student_...` had a 3-project fixture) corrected to a
true student; new regression test added for the portfolio case.

### Chat input vanished mid-question

`ResumeIntake.tsx` showed the chat textarea only while
`!ready_to_generate` and **replaced** it with the Generate button
once the draft had enough fields — so when the assistant asked
"want to add certifications?" the user had no input to answer in.
There is no turn limit (confirmed in the backend); it was purely
this frontend mutual-exclusion. Fixed: the input persists for the
whole conversation (until a résumé is generated); the Generate
button shows ALONGSIDE it as an additional affordance, with a hint.

### User vs assistant messages were near-identical

The two roles differed only by a faint text shade — and the "user"
colour used an undefined `--fg-1` token, so it just inherited the
default. Replaced with proper bubbles: user = blue-tinted,
right-aligned, blue "You" label; assistant = card-grey,
left-aligned, muted label. Removed the now-dead `.workspace-chat-*`
CSS the builder no longer references.

### Q3 — stale preview after a draft edit

Editing the draft form and clicking "Save draft edits" updated the
draft but left `generated_resume_markdown` frozen — the on-screen
preview showed the OLD generation while a fresh export would
reflect the edits (what-you-see ≠ what-you-download). Fixed:
`update_resume_builder_session` now clears the generated résumé on
any draft edit, so the UI drops back to "Generate base resume" and
regenerating keeps preview == download.

### Q2 — "Start over"

There was no way to clear a builder session and rebuild. Added a
"Start over" button (two-click confirm) + `reset_resume_builder_
session` + a `/resume-builder/reset` route. Critical design point:
it reuses the SAME `session_id` so NO new `resume_builder_sessions`
quota credit is charged — Free tier has a lifetime cap of 1, and a
"Start over" that span up a new session would instantly lock out
every Free user. The cleared session is persisted so a reload
can't resurrect the old draft.

Verification: frontend tsc + eslint clean; 18/18 resume_builder
unit tests, 38/38 resume-builder backend route tests (incl. 3 new
Q2/Q3 route tests).

### Parked: unified LLM token meter + 3-day Pro trial

Long design discussion this session on quota strategy. Decided to
replace the scattered per-feature LLM gates (`assistant_turns`,
`resume_builder_sessions`, `tailored_applications`, `resume_parses`)
with ONE per-user weekly **token meter** — flat tokens, accounting
universal (instrument `OpenAIService`), enforcement at ~6 operation
entries. Calibrated real per-operation token costs (full agentic
run measured at ~13K, native gpt-5.4). Caps: Free 90K, Pro 1M,
Business 4M per week — sized against the $9 / $29 pricing. Plus a
card-required 3-day Pro trial via Lemon Squeezy as the conversion
lever. Full spec parked in `report.md` ("Unified LLM token meter +
3-day Pro trial") — NOT built this session.

## Day 63: Résumé-builder live themed preview

The builder's post-generate preview was a plain-text `<pre>` dump of
the markdown — accurate but ugly, and it gave the user no sense of
what their five theme choices actually look like. The theme `<select>`
sat right above it driving only the *download*, so picking "Modern
Blue" changed nothing visible until after a download.

Replaced that `<pre>` with a **live themed preview**: an
`<iframe srcDoc>` rendering the résumé in the selected theme — the
same look the final workspace `ArtifactViewer` ships. One picker now
drives both the preview and the download; switching themes re-renders
the iframe in place.

New endpoint `POST /workspace/resume-builder/preview`
(`preview_resume_builder_artifact`) returns themed HTML via the
existing `build_resume_preview_html`. Two deliberate properties:

- **LLM-free.** It passes `openai_service=None` into
  `_synthesize_resume_builder_artifact`, and post-generate the
  structuring pass is already signature-cached — so a theme switch
  only re-renders colours/fonts, never re-structures. Zero token-meter
  cost; the user browses all five themes freely.
- **NOT entitlement-gated.** Every tier may *preview* every theme —
  that is the conversion surface. The Free = Professional-only limit
  stays exactly where it was, on `/export` (`enforce_export_
  entitlement`): a Free user previewing "Modern Blue" sees it in full,
  then gets the standard upgrade nudge if they hit Download. A short
  caption under the picker states the policy up front.

Frontend: `WorkspaceShell` holds `resumeBuilderPreviewHtml` +
`...Loading`, fetched by a `useEffect` keyed on
`[session_id, generated_resume_markdown, exportTheme]` — covers
initial generate, theme switch, and the Q3 draft-save → regenerate
cycle. A `cancelled` guard drops a stale theme's slow response. The
iframe persists (dimmed) during a re-fetch so picking a theme never
collapses the layout; the plain markdown remains the graceful
fallback if the render errors.

Verification: frontend tsc + eslint clean; 63/63
`test_backend_workspace.py` (incl. 3 new `/resume-builder/preview`
route tests — themed HTML, unknown-session 400, unknown-theme 422).
