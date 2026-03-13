# AI Job Application Agent

[License: MIT](LICENSE)

AI Job Application Agent is a Streamlit app for preparing stronger job applications through resume parsing, job-description analysis, and LinkedIn export ingestion.

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
- Upload a LinkedIn data export ZIP and normalize it into candidate-profile data
- Persist parsed and normalized inputs across Streamlit navigation with session state
- Run on a modular structure with UI, parser, and service layers already separated

## Current Status

The app is still in MVP form. The parsing and intake flows are working; the tailoring and job-application automation layers are the next implementation step.

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
|  |- schemas.py
|  |- parsers/
|  |- services/
|  |- ui/
|  |- jd_parser.py
|  |- linkedin_parser.py
|  `- resume_parser.py
|- tests/
|  |- test_jd_parser.py
|  |- test_linkedin_parser.py
|  `- test_resume_parser.py
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

### 1. Create and activate a virtual environment

```powershell
python -m venv venv
venv\Scripts\activate
```

### 2. Install dependencies

```powershell
pip install -r requirements.txt
```

### 3. Optional configuration

Environment variables can be stored in [`.env.example`](.env.example):

- `OPENAI_API_KEY`
- `OPENAI_MODEL`

The current app does not yet require OpenAI to run the parsing flows, but these settings are reserved for upcoming tailoring features.

## Run the App

```powershell
streamlit run app.py
```

Then:

1. Upload a resume or import LinkedIn data
2. Open `Manual JD Input`
3. Upload or paste a job description
4. Review the extracted signals

## Testing

```powershell
python -m pytest
```
