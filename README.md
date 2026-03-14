# AI Job Application Agent

[License: MIT](LICENSE)

AI Job Application Agent is a Streamlit app for preparing stronger job applications through resume parsing, job-description analysis, grounded fit review, tailored resume generation, application-package assembly, assisted Q&A, and export.

The repository now follows the same product-style structure as the GitHub Portfolio Reviewer Agent:

- `app.py` as the Streamlit entrypoint
- `src/` for application logic
- `tests/` for parser, service, orchestration, UI, and persistence coverage
- `docs/` for architecture and ADRs

## Current Features

- Upload and parse resumes from PDF, DOCX, or TXT
- Upload, sample-load, or paste a job description
- Clean job-description text and extract simple signals:
  - title
  - location
  - experience requirement
  - hard skills
  - soft skills
  - must-have and nice-to-have requirement lines
- Generate a deterministic fit snapshot against the active job description
- Produce first-pass resume-tailoring guidance from grounded profile and JD signals
- Run a supervised specialist-agent workflow on demand:
  - profile
  - job
  - fit
  - tailoring
  - strategy
  - review
  - resume generation
- Run a bounded review-revision loop before the final resume artifact is generated
- Use OpenAI when configured, with deterministic fallback when it is not
- Route different assisted tasks to different model tiers instead of relying on one global model
- Use the OpenAI Responses API for assisted JSON generation and usage tracking
- Build a tailored resume artifact from the current workflow state
- Preview the tailored resume directly in the app before export
- Compare the original resume text against the tailored resume with a unified diff and similarity metrics
- Build an application package / strategy report from the current workflow state
- Download the tailored resume and the report as Markdown or PDF
- Download both artifacts together as a ZIP bundle
- Save authenticated workflow history and regenerate historical downloads from saved run payloads without re-running OpenAI
- Ask a built-in two-mode assistant for:
  - product help (`Using the App`)
  - grounded application Q&A (`About My Resume`)
- Sign in with Google via Supabase from the sidebar account panel
- Gate the AI-assisted workflow behind authenticated account state while keeping deterministic exploration available without login
- Show remaining assisted session capacity in the UI without exposing cost
- Persist parsed and normalized inputs across Streamlit navigation with session state
- Run on a modular structure with UI, parser, and service layers already separated

## Current Status

The app is still an MVP, but it is now a coherent authenticated workflow product rather than only a deterministic prototype. Resume parsing, JD structuring, deterministic fit analysis, supervised specialist-agent orchestration, bounded review-driven revision, tailored resume generation, report generation, preview-before-download flows, export packaging, model-aware assisted routing, grounded in-app assistance, Google sign-in, persisted usage tracking, daily quotas, and workflow history are all working.

The active product scope is intentionally focused:

- resume plus JD in
- grounded tailored resume plus application package out

Google sign-in is integrated alongside persisted per-user usage tracking, plan-based daily quotas, and saved workflow and artifact history backed by Supabase Postgres. Historical resume and report downloads are regenerated from the saved run payloads, while any new resume or JD input produces a new workflow run instead of reusing stale artifacts.

## Strategy

The current architecture and delivery strategy are documented in [docs/project_strategy.md](docs/project_strategy.md).

That document captures:

- why we are keeping Streamlit first
- why this app keeps a sidebar unlike the GitHub agent
- how the current supervised workflow, auth, quotas, and history layers fit together
- where the real architecture boundaries are today and where backend extraction becomes worth it later
- the re-baselined implementation roadmap from the current product state

## Architecture

```text
AI_Job_Application_Agent/
|- app.py
|- src/
|  |- config.py
|  |- errors.py
|  |- exporters.py
|  |- openai_service.py
|  |- prompts.py
|  |- report_builder.py
|  |- schemas.py
|  |- taxonomy.py
|  |- utils.py
|  |- agents/
|  |- parsers/
|  |- services/
|  |- ui/
|  |- jd_parser.py
|  `- resume_parser.py
|- tests/
|  |- parser tests
|  |- service tests
|  `- orchestrator tests
`- docs/
   |- architecture.md
   `- adr/
```

See [docs/architecture.md](docs/architecture.md) for the runtime overview.

## Decision Records

Architectural decisions are tracked in [docs/adr/README.md](docs/adr/README.md).

Related planning and sizing docs:

- [docs/model-latency-and-cost-estimates.md](docs/model-latency-and-cost-estimates.md)
- [docs/google-signin-implementation-plan.md](docs/google-signin-implementation-plan.md)

## Roadmap

The phase-based roadmap is documented in [ROADMAP.md](ROADMAP.md).

## Setup

### 1. Create and sync the uv environment

```powershell
uv sync --group dev
```

### 2. Activate the environment

```powershell
.venv\Scripts\activate
```

### 3. Install Chromium for polished PDF export

```powershell
uv run python -m playwright install chromium
```

PDF export uses Playwright/Chromium first and falls back to ReportLab if the browser backend is unavailable.

### 4. Optional configuration

Environment variables can be stored in [`.env.example`](.env.example):

- `OPENAI_API_KEY`
- `OPENAI_MODEL_DEFAULT`
- `OPENAI_MODEL_HIGH_TRUST`
- `OPENAI_MODEL_MID_TIER`
- `OPENAI_MODEL_PRODUCT_HELP`
- `OPENAI_MODEL_APPLICATION_QA`
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_AUTH_REDIRECT_URL`
- `SUPABASE_APP_USERS_TABLE`
- `SUPABASE_USAGE_EVENTS_TABLE`
- `SUPABASE_WORKFLOW_RUNS_TABLE`
- `SUPABASE_ARTIFACTS_TABLE`
- `AUTH_REQUIRED_FOR_ASSISTED_WORKFLOW`
- `AUTH_DEFAULT_PLAN_TIER`
- `AUTH_DEFAULT_ACCOUNT_STATUS`
- `FREE_TIER_MAX_CALLS_PER_DAY`
- `FREE_TIER_MAX_TOKENS_PER_DAY`
- `PAID_TIER_MAX_CALLS_PER_DAY`
- `PAID_TIER_MAX_TOKENS_PER_DAY`

The current app does not require OpenAI for parsing or deterministic analysis. If `OPENAI_API_KEY` is present, assisted workflow and assistant features will use the configured routed models. If not, they will fall back to deterministic behavior where supported.

To enable Google sign-in, configure Supabase Auth with the Google provider and set:

- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_AUTH_REDIRECT_URL` to the Streamlit app URL allowed in your Supabase redirect settings, for example `http://localhost:8501`

To enable the full authenticated persistence path in one step, apply [docs/supabase-bootstrap.sql](docs/supabase-bootstrap.sql) in the Supabase SQL Editor. That bootstrap script creates `app_users`, `usage_events`, `workflow_runs`, and `artifacts` with the required indexes and RLS policies.

If your Supabase project already has the earlier `workflow_runs` table, apply [docs/supabase-workflow-history-payloads-migration.sql](docs/supabase-workflow-history-payloads-migration.sql) to add the saved-run regeneration columns without rerunning the full bootstrap.

If you prefer incremental setup, the same schema is still split across:

- [docs/supabase-app-users.sql](docs/supabase-app-users.sql)
- [docs/supabase-usage-events.sql](docs/supabase-usage-events.sql)
- [docs/supabase-workflow-history.sql](docs/supabase-workflow-history.sql)

To enable persistent account sync after login, create the `app_users` table in Supabase and keep `SUPABASE_APP_USERS_TABLE` aligned with its name. The authenticated user now syncs a lightweight app-level account record on sign-in and session restore.

To persist assisted usage in the external database, also create the `usage_events` table from [docs/supabase-usage-events.sql](docs/supabase-usage-events.sql). The app writes insert-only usage records for authenticated assisted requests, which is the right foundation for later daily rollups and quota enforcement.

The app now enforces authenticated daily assisted limits from persisted usage. Free-tier defaults and paid-tier defaults are configured through environment variables, and admin/internal plan tiers remain unrestricted.

Authenticated assisted runs now also persist lightweight history metadata plus saved run payloads in Supabase. The sidebar account panel surfaces a recent snapshot, and the dedicated History page lets the user inspect saved runs, inspect linked artifacts, and regenerate historical downloads from the saved run content instead of the current in-session inputs.

New saved workflow payloads are written through a versioned JSON envelope, while the reader remains backward-compatible with the earlier unversioned payload format.

This keeps storage cheap: the app stores structured workflow payloads and metadata in Postgres, regenerates PDFs on demand, and avoids storing large binary artifacts unless that tradeoff becomes necessary later.

If `AUTH_REQUIRED_FOR_ASSISTED_WORKFLOW` is left at its default value of `true`, the AI-assisted workflow button is disabled until the user signs in. Resume parsing and deterministic JD analysis remain available without login.

## Run the App

```powershell
uv run streamlit run app.py
```

Then:

1. Upload a resume
2. Open `Manual JD Input`
3. Upload or paste a job description
4. Review the extracted signals, fit snapshot, and tailoring guidance
5. Sign in with Google from the sidebar if assisted workflow is enabled
6. Run the supervised workflow for agent-refined output, review notes, strategy guidance, and final tailored resume generation
7. Preview the tailored resume and the application package in-page
8. Compare the original resume against the tailored output if needed
9. Use the assistant panel for product help or grounded application Q&A
10. Download the resume, the report, or the combined export bundle
11. Open `History` to revisit authenticated workflow runs and regenerate saved downloads

## Testing

```powershell
uv run pytest
```
