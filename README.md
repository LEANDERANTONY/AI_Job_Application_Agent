# AI Job Application Agent

[License: MIT](LICENSE)

AI Job Application Agent is a Streamlit app for preparing stronger job applications through resume parsing, job-description analysis, grounded fit review, tailored resume generation, application-package assembly, assisted Q&A, and export.

The repository now follows the same product-style structure as the GitHub Portfolio Reviewer Agent:

- `app.py` as the Streamlit entrypoint
- `src/` for application logic
- `tests/` for parser, service, orchestration, UI, and persistence coverage
- `docs/` for architecture and ADRs

## Current Features

- Sign in with Google via Supabase from the sidebar account panel
- Upload and parse resumes from PDF, DOCX, or TXT
- Upload or paste a job description
- Clean job-description text and extract simple signals:
  - title
  - location
  - experience requirement
  - hard skills
  - soft skills
  - must-have and nice-to-have requirement lines
- Handle more real-world JD phrasing deterministically, including `Required Experience:` variants, while avoiding obvious requirement-bucket pollution from location lines
- Generate a deterministic fit snapshot against the active job description
- Produce first-pass resume-tailoring guidance from grounded profile and JD signals
- Run a supervised specialist-agent workflow on demand:
  - fit
  - tailoring
  - strategy
  - review
  - resume generation
  - cover letter
- Let the review stage directly correct tailoring and strategy outputs before final resume generation instead of rerunning the full workflow loop
- Use OpenAI when configured, with deterministic fallback when it is not
- Route different assisted tasks to different model tiers instead of relying on one global model
- Route GPT-5 reasoning effort by task, with low effort on fit and strategy, medium effort on tailoring, review, and final resume generation, and higher-trust routing kept for the final grounding stages
- Use the OpenAI Responses API for assisted JSON generation and usage tracking
- Build a tailored resume artifact from the current workflow state
- Build a grounded cover letter artifact from the current workflow state
- Preview the tailored resume directly in the app before export
- Build an application package / strategy report from the current workflow state
- Download the tailored resume, cover letter, and report as Markdown or PDF
- Save one reloadable authenticated workspace snapshot per user for 24 hours and restore it through the sidebar `Reload Workspace` action into `Manual JD Input`
- Ask one unified grounded assistant about product behavior, your resume, or the current outputs
- Keep resume intake login-first so saved-workspace reloads, quotas, and assisted usage stay tied to the same account state
- Show remaining assisted session capacity in the UI without exposing cost
- Persist parsed and normalized inputs across Streamlit navigation with session state
- Run on a modular structure with UI, parser, and service layers already separated

## Current Status

The app is still an MVP, but it is now a coherent authenticated workflow product rather than only a deterministic prototype. Resume parsing, JD structuring, deterministic fit analysis, supervised specialist-agent orchestration, direct review-driven correction, tailored resume generation, report generation, preview-before-download flows, export packaging, model-aware assisted routing, grounded in-app assistance, Google sign-in, persisted usage tracking, daily quotas, and 24-hour saved workspace reloads are all working.

The active product scope is intentionally focused:

- resume plus JD in
- grounded tailored resume plus application package out

Recent deterministic parser hardening kept in the current baseline:

- resume parsing remains hardened against real PDF fixtures from the demo set
- JD parsing is validated against real TXT, PDF, and DOCX sample descriptions in `static/demo_job_description/`

Google sign-in is integrated alongside persisted per-user usage tracking, plan-based daily quotas, and a single reloadable saved workspace backed by Supabase Postgres. Each successful workflow run overwrites the prior saved workspace for that user, and the saved workspace expires after 24 hours by default. The current UX intentionally keeps this as a sidebar reload action only; there is no separate saved-workspace or history page.

## Strategy

The current architecture and delivery strategy are documented in [docs/project_strategy.md](docs/project_strategy.md).

That document captures:

- why we are keeping Streamlit first
- why this app keeps a sidebar unlike the GitHub agent
- how the current supervised workflow, auth, quotas, and saved-workspace layers fit together
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

Related operator docs:

- [docs/supabase-setup-checklist.md](docs/supabase-setup-checklist.md)
- [deployment-plan.md](deployment-plan.md)

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

### 3. Install the local WeasyPrint runtime

PDF export uses WeasyPrint first and falls back to ReportLab only when the HTML-to-PDF runtime is unavailable.

For local Windows development, install the GTK/Pango runtime libraries WeasyPrint needs. If those native libraries are missing, local PDF export will fall back to ReportLab until they are installed.

For hosted deployment, the chosen path is to package the WeasyPrint runtime inside the Render Docker image so the PDF stack is controlled rather than host-dependent.

### 4. Optional configuration

Environment variables can be stored in [`.env.example`](.env.example):

For local development, create a private `.env` file in the repo root and copy the keys you need from `.env.example`.
That file is already ignored by git.

Required for the active authenticated workflow:

- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_AUTH_REDIRECT_URL`

Required only for AI-assisted features:

- `OPENAI_API_KEY`

Optional runtime and routing settings:

- `OPENAI_API_KEY`
- `OPENAI_MODEL_DEFAULT`
- `OPENAI_MODEL_HIGH_TRUST`
- `OPENAI_MODEL_MID_TIER`
- `OPENAI_MODEL_PRODUCT_HELP`
- `OPENAI_MODEL_APPLICATION_QA`
- `OPENAI_REASONING_DEFAULT`
- `OPENAI_REASONING_HIGH_TRUST`
- `OPENAI_REASONING_PROFILE`
- `OPENAI_REASONING_JOB`
- `OPENAI_REASONING_FIT`
- `OPENAI_REASONING_TAILORING`
- `OPENAI_REASONING_STRATEGY`
- `OPENAI_REASONING_REVIEW`
- `OPENAI_REASONING_RESUME_GENERATION`
- `OPENAI_REASONING_PRODUCT_HELP`
- `OPENAI_REASONING_APPLICATION_QA`
- `OPENAI_MAX_CALLS_PER_SESSION`
- `OPENAI_MAX_TOKENS_PER_SESSION`
- `APP_BASE_URL`
- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_AUTH_REDIRECT_URL`
- `SUPABASE_APP_USERS_TABLE`
- `SUPABASE_USAGE_EVENTS_TABLE`
- `SUPABASE_SAVED_WORKSPACES_TABLE`
- `SAVED_WORKSPACE_TTL_HOURS`
- `AUTH_REQUIRED_FOR_ASSISTED_WORKFLOW`
- `AUTH_DEFAULT_PLAN_TIER`
- `AUTH_DEFAULT_ACCOUNT_STATUS`
- `AUTH_INTERNAL_USER_EMAILS`
- `FREE_TIER_MAX_CALLS_PER_DAY`
- `FREE_TIER_MAX_TOKENS_PER_DAY`
- `PAID_TIER_MAX_CALLS_PER_DAY`
- `PAID_TIER_MAX_TOKENS_PER_DAY`

The current app does not require OpenAI for parsing or deterministic analysis. If `OPENAI_API_KEY` is present, assisted workflow and assistant features will use the configured routed models. If not, they will fall back to deterministic behavior where supported.

The current OpenAI Responses API integration also includes runtime safeguards for GPT-5 routed models:

- retry without `temperature` if the routed model rejects that parameter
- per-task reasoning-effort routing for GPT-5 models
- one retry with a higher output-token budget when a response is incomplete because the original output budget was exhausted
- longer client timeouts plus SDK retries to reduce transient read-timeout failures

Current default assisted routing is intentionally asymmetric:

- `fit`: GPT-5 Mini with `low` reasoning
- `tailoring`: GPT-5 Mini with `medium` reasoning
- `strategy`: GPT-5 Mini with `low` reasoning
- `review`: GPT-5.4 with `medium` reasoning
- `resume_generation`: GPT-5.4 with `medium` reasoning

Current default output-token caps are also tuned by task rather than kept uniform:

- `fit`: 1600
- `tailoring`: 3200
- `strategy`: 1500
- `review`: 4000
- `resume_generation`: 3000

The current UI keeps resume intake behind authenticated account state. That means Supabase is effectively required for the active resume-led workflow, even though the Streamlit shell itself can still boot without it. Once Supabase is configured, Google sign-in, saved-workspace reload, and account-level quotas all run through the same account model.

To enable Google sign-in, configure Supabase Auth with the Google provider and set:

- `SUPABASE_URL`
- `SUPABASE_ANON_KEY`
- `SUPABASE_AUTH_REDIRECT_URL` to the Streamlit app URL allowed in your Supabase redirect settings, for example `http://localhost:8501`

The local sign-in flow now preserves Supabase PKCE verifier state across the redirect and Streamlit rerun cycle. If that state expires, the app fails closed with a clean retry message instead of silently leaving the sidebar in a broken signed-out state.

Local runs now load a private repo-root `.env` file automatically. On Render, put the same values into the Render environment configuration; those variables are still read through the same `os.getenv(...)` path.

For the concrete operator checklist, see [docs/supabase-setup-checklist.md](docs/supabase-setup-checklist.md).

To enable the full authenticated persistence path in one step, apply [docs/supabase-bootstrap.sql](docs/supabase-bootstrap.sql) in the Supabase SQL Editor. That bootstrap script creates `app_users`, `usage_events`, and `saved_workspaces` for the active product path.

The app now enforces authenticated daily assisted limits from persisted usage. Free-tier defaults and paid-tier defaults are configured through environment variables, and admin/internal plan tiers remain unrestricted.

For product testing, keep internal accounts and quota-test accounts separate:

- put only unrestricted internal emails in `AUTH_INTERNAL_USER_EMAILS`
- use a second Google account that is not allowlisted when you want to validate normal free-tier quota exhaustion, reset timing, and fallback messaging
- do not add that quota-test account to `AUTH_INTERNAL_USER_EMAILS`, or it will bypass the very limits you are trying to test

Authenticated assisted runs now persist one reloadable workspace payload in Supabase. The sidebar account panel exposes a `Reload Workspace` action that restores the latest saved snapshot directly into `Manual JD Input`; there is no separate saved-workspace page.

The saved workspace is overwritten by each new successful workflow run for the same user. By default it is retained for 24 hours. After `expires_at`, Supabase Row Level Security stops serving it immediately, and a scheduled cleanup job removes expired rows from the table every 5 minutes. The app also purges expired rows on save/load as a backup cleanup path.

New saved workflow payloads are written through a versioned JSON envelope, while the reader remains backward-compatible with the earlier unversioned payload format.

This keeps storage cheap: the app stores one structured workspace payload per user in Postgres, regenerates PDFs on demand, and avoids storing large binary artifacts unless that tradeoff becomes necessary later.

If `AUTH_REQUIRED_FOR_ASSISTED_WORKFLOW` is left at its default value of `true`, the AI-assisted workflow button is disabled until the user signs in. In the current UI, resume upload is also login-first.

## Deployment Notes

- [`.streamlit/config.toml`](.streamlit/config.toml) remains the Streamlit app baseline, but the chosen first hosted target is now Render.
- Chosen first deployment target: Render Docker web service.
- Chosen persistence and auth target: Supabase free tier.
- Hosted PDF generation should be treated as WeasyPrint-required, with the native runtime bundled in the Docker image.
- ReportLab remains in the codebase only as resilience fallback, not as the intended hosted renderer.
- Hosted AI-assisted flows use the stabilized Responses API path with task-level reasoning routing, GPT-5 parameter fallback handling, and incomplete-response retries.
- The concrete deployment sequence is documented in [deployment-plan.md](deployment-plan.md).

## Run the App

```powershell
uv run streamlit run app.py
```

Then:

1. Sign in with Google from the sidebar
2. Upload a resume
3. Open `Manual JD Input`
4. Upload or paste a job description
5. Run the supervised workflow for agent-refined output, review notes, strategy guidance, tailored resume generation, and cover letter generation
6. Preview the tailored resume, cover letter, and application package in-page
7. Use the assistant panel for product help or grounded output questions
8. Download the resume, cover letter, or report as needed
9. Use `Reload Workspace` from the sidebar when you want to restore the latest saved run into the JD flow

## Testing

```powershell
uv run pytest
```
