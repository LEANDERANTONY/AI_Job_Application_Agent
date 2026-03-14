# AI Job Application Agent

[License: MIT](LICENSE)

AI Job Application Agent is a Streamlit app for preparing stronger job applications through resume parsing, job-description analysis, fit review, tailored output, and export.

The repository now follows the same product-style structure as the GitHub Portfolio Reviewer Agent:

- `app.py` as the Streamlit entrypoint
- `src/` for application logic
- `tests/` for parser coverage
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
- Use OpenAI when configured, with deterministic fallback when it is not
- Build a deterministic application package from the current workflow state
- Download the package as Markdown or PDF
- Persist parsed and normalized inputs across Streamlit navigation with session state
- Run on a modular structure with UI, parser, and service layers already separated

## Current Status

The app is still in MVP form, but the first usable application pipeline now exists. Resume parsing, JD structuring, deterministic fit analysis, first-pass tailoring guidance, supervised specialist-agent orchestration, bounded review-driven revision, and package export are working. The current product scope is intentionally narrower: resume plus JD in, grounded application package out.

## Strategy

The current architecture and delivery strategy are documented in [docs/project_strategy.md](docs/project_strategy.md).

That document captures:

- why we are keeping Streamlit first
- why this app keeps a sidebar unlike the GitHub agent
- the planned multi-agent architecture
- how the code should evolve toward FastAPI and Next.js later
- the phased implementation timeline

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
- `OPENAI_MODEL`

The current app does not require OpenAI for parsing or deterministic analysis. If `OPENAI_API_KEY` is present, the supervised workflow will use the configured model. If not, it will fall back to deterministic output.

## Run the App

```powershell
uv run streamlit run app.py
```

Then:

1. Upload a resume
2. Open `Manual JD Input`
3. Upload or paste a job description
4. Review the extracted signals, fit snapshot, and tailoring guidance
5. Run the supervised workflow for agent-refined output, review notes, and strategy guidance
6. Download the assembled application package as Markdown or PDF

## Testing

```powershell
uv run pytest
```
