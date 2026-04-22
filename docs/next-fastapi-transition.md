# Next.js + FastAPI Transition

`feature/jd-summary` now carries the architecture transition work for migrating the `main` product from a Streamlit-first shell to a `Next.js + FastAPI` split deployment:

- `frontend/` is the new Vercel-facing shell
- `backend/` is the Dockerized FastAPI boundary for the VPS
- `src/` remains the reusable Python workflow core
- `deploy/vps/` mirrors the HelpMate deployment pattern with Docker Compose plus Caddy

## Branch Basis

This skeleton was first prototyped in a separate transition branch, then folded into `feature/jd-summary` so the team can keep one active integration branch instead of juggling three long-lived branches.

That means this branch now combines:

- the existing JD-summary and job-application expansion work
- the current FastAPI backend improvements already living here
- the new `frontend/` and `deploy/vps/` scaffolding needed for the Next.js + VPS rollout

## Current Surface Mapping

- Resume intake: `src/ui/pages.py`, `src/ui/workflow.py`
- Manual JD intake and agentic analysis: `src/ui/pages.py`, `src/ui/workflow.py`
- Assistant panel: `src/ui/page_assistant.py`, `src/assistant_service.py`
- Artifact rendering: `src/ui/page_artifacts.py`, `src/report_builder.py`, `src/resume_builder.py`, `src/cover_letter_builder.py`
- Job search foundation: `backend/`, `src/services/job_service.py`, `src/job_sources/`

## What This Branch Adds

- A standalone `frontend/` Next.js app-router workspace with:
  - a Vercel-ready rewrite-based API client
  - a collapsible sidebar with account state and assistant chat
  - resume upload, JD upload/editing, job search/import, workflow runs, shortlist persistence, saved workspace reload, artifact previews, and exports
- VPS deployment assets in `deploy/vps/`
- Backend CORS settings for a separate frontend origin
- A backend-first Docker image at the repo root
- `Dockerfile.streamlit` so the legacy Render path remains available while parity work continues

## Current Migration Status

The main product lanes are now wired in the Next.js workspace:

1. Auth and session restore
2. Resume intake
3. Job search and import
4. Manual JD intake
5. Deterministic preview and agentic workflow execution
6. Saved workspace reload and shortlist persistence
7. Assistant chat grounded to the current workspace
8. Artifact preview plus Markdown, PDF, and ZIP exports

## Remaining Work

The remaining work is now mostly product polish and hosted validation:

1. Extend saved-workspace history beyond the latest snapshot if we want multi-entry restore.
2. Add richer in-app artifact interaction and polish beyond the current HTML preview and exports.
3. Run hosted QA across the real Vercel and VPS environments, including Supabase redirect URLs, CORS, and end-to-end auth checks.
