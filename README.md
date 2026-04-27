# AI Job Application Agent

[![CI](https://github.com/LEANDERANTONY/AI_Job_Application_Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/LEANDERANTONY/AI_Job_Application_Agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Live App](https://img.shields.io/badge/Live%20App-Vercel-2563eb?logo=vercel&logoColor=white)](https://job-application-copilot.xyz/)

AI Job Application Agent is a Vercel-hosted Next.js workspace with a FastAPI backend for resume parsing, JD review, grounded agentic tailoring, and exportable job application documents.

## Product Flow

1. Sign in with Google
2. Upload a resume
3. Search jobs, import a supported posting, or paste a JD manually
4. Review the JD summary
5. Run the agentic analysis
6. Review the tailored resume and cover letter
7. Ask grounded follow-up questions in the workspace assistant
8. Export Markdown or PDF documents

## Stack

- Next.js frontend in `frontend/`
- FastAPI backend in `backend/`
- Shared Python workflow and builders in `src/`
- Supabase for Google auth, quota tracking, saved workspaces, and saved jobs
- OpenAI Responses API for assisted generation
- WeasyPrint-backed PDF export pipeline
- Docker Compose + Caddy deployment bundle in `deploy/vps/`

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

Transition notes and deployment details live in [docs/next-fastapi-transition.md](docs/next-fastapi-transition.md).
