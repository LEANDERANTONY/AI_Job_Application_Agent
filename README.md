# AI Job Application Agent

[![CI](https://github.com/LEANDERANTONY/AI_Job_Application_Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/LEANDERANTONY/AI_Job_Application_Agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Live App](https://img.shields.io/badge/Live%20App-Vercel-2563eb?logo=vercel&logoColor=white)](https://job-application-copilot.xyz/)

AI Job Application Agent is a grounded resume-tailoring product: a five-stage agent pipeline that turns a source resume and job description into an evidence-backed tailored resume and cover letter.

The core differentiator is grounded review. The pipeline is designed to detect and correct unsupported claims before export, so tailoring can emphasize the candidate's strongest relevant evidence without inventing skills or experience.

![Agentic workflow](docs/screenshots/agentic_workflow.jpg)

Live landing page: https://job-application-copilot.xyz

Workspace app: https://app.job-application-copilot.xyz

## Agent Pipeline

The workflow runs through `ApplicationOrchestrator` with progress callbacks, per-stage duration logging, JSON-contracted agent outputs, and deterministic fallback if assisted generation is unavailable.

1. `FitAgent` compares the candidate profile against the job description.
2. `TailoringAgent` rewrites the deterministic baseline into role-specific resume guidance.
3. `ReviewAgent` checks grounding, reports unsupported claims, and returns corrected tailoring when repairs are possible.
4. `ResumeGenerationAgent` builds the final tailored resume artifact from the reviewed output.
5. `CoverLetterAgent` runs only after review approval and creates a role-specific cover letter.

Each agent follows the same operating shape: deterministic baseline first, LLM-assisted refinement second, structured JSON output, and grounded fallback behavior when assisted execution is unavailable.

## Grounding And Fallbacks

- Deterministic services build the candidate profile, JD summary, fit analysis, and first-pass tailored draft before the agent layer runs.
- `ReviewAgent` returns `grounding_issues`, `unresolved_issues`, `revision_requests`, and an optional `corrected_tailoring` payload.
- The orchestrator uses `corrected_tailoring` as the downstream source of truth when review repairs the draft.
- Cover-letter generation is gated on review approval.
- The fallback review path checks whether the output references missing hard skills that are not evidenced in the source profile.

## Prompt And Runtime Discipline

- Prompt builders compact large JSON sections through escalating string and list caps before falling back to a section summary.
- Prompt metadata records estimated input size, compacted section count, compacted labels, and budget mode.
- The OpenAI wrapper routes by task, tracks usage, enforces quota checks, records response metadata, and retries incomplete JSON responses with a higher output budget when appropriate.

## Product Surface

1. Sign in with Google through Supabase-backed auth
2. Upload a resume and build a normalized candidate profile
3. Search Greenhouse and Lever boards, import a supported posting, or paste a JD manually
4. Review a structured JD summary
5. Run the grounded agentic workflow
6. Review the tailored resume and cover letter
7. Ask grounded follow-up questions in the workspace assistant
8. Export Markdown or WeasyPrint-backed PDF documents

## Stack

- Next.js frontend in `frontend/`
- FastAPI backend in `backend/`
- Shared Python workflow, agents, builders, and services in `src/`
- Supabase for Google auth, quota tracking, saved workspaces, and saved jobs
- Greenhouse and Lever job-source clients with matching and registry layers
- OpenAI Responses API for assisted generation
- WeasyPrint-backed PDF export pipeline
- Docker Compose + Caddy deployment bundle in `deploy/vps/`

## Engineering Notes

- 37 focused Python test files cover parsing, normalization, fitting, tailoring, orchestration, builders, exports, auth, quotas, persistence, and backend routes.
- 12 ADRs in `docs/adr/` record product and architecture decisions, including the Streamlit-first to Next.js + FastAPI transition.
- Architecture details live in [docs/architecture.md](docs/architecture.md).
- Deployment notes live in [docs/next-fastapi-transition.md](docs/next-fastapi-transition.md).

## Local Development

Run the backend:

```powershell
uv run uvicorn backend.app:app --reload --host 127.0.0.1 --port 8000
```

Run the frontend:

```powershell
cd frontend
npm install
npm run dev
```

Recommended local frontend env:

```env
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000/api
NEXT_PUBLIC_SITE_URL=http://localhost:3000
```

Recommended backend env:

```env
ENABLE_JOB_SEARCH_BACKEND=true
JOB_BACKEND_BASE_URL=http://127.0.0.1:8000
GREENHOUSE_BOARD_TOKENS=narvar,gleanwork,wayve,datadog,moloco,figma,qualtrics,thumbtack,placerlabs,zscaler,coinbase,typeface
LEVER_SITE_NAMES=dnb,plaid,mistral
```

## Core Checks

1. Open `http://127.0.0.1:8000/api/health`
2. Open `http://localhost:3000/workspace`
3. Upload a resume
4. Search or import a job
5. Load or paste a JD
6. Run the agentic analysis
7. Verify resume, cover letter, assistant, and exports

## Deployment Shape

- `app.job-application-copilot.xyz` -> Vercel frontend
- `api.job-application-copilot.xyz` -> VPS FastAPI backend
- `deploy/vps/` -> Docker Compose + Caddy bundle for the backend stack
