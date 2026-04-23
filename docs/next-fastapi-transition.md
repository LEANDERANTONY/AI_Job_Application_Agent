# Next.js + FastAPI Transition

This document records the completed architecture move from the old Streamlit shell to the current `Next.js + FastAPI` product.

## Final Shape

- `frontend/` is the Vercel-hosted Next.js workspace
- `backend/` is the Dockerized FastAPI service running on the VPS
- `src/` remains the reusable Python workflow core
- `deploy/vps/` contains the Docker Compose + Caddy deployment bundle

## What Changed

The migration replaced the old Streamlit runtime with:

- a dedicated Next.js workspace UI
- FastAPI endpoints for auth, workspace actions, job search, assistant answers, exports, and persistence
- separate frontend and backend hosting targets
- Supabase-backed auth and saved-state flows routed through the API boundary

## Current Product Flow

1. Sign in with Google
2. Upload a resume
3. Search jobs, import a posting, or paste a JD
4. Review the JD summary
5. Run the agentic workflow
6. Review the tailored resume and cover letter
7. Ask grounded questions in the workspace assistant
8. Export Markdown or PDF documents

## Notes On Scope Changes

The migration was also used to simplify the product:

- the old visible Streamlit report-first surface is gone
- the visible workspace now centers on resume and cover letter
- the strategy stage is no longer part of the active agentic workflow
- the old multi-theme resume export path was removed in favor of one ATS-friendly resume format

## Deployment Shape

- `app.job-application-copilot.xyz` -> Vercel frontend
- `api.job-application-copilot.xyz` -> VPS FastAPI backend

## Remaining Follow-Up

The main remaining architecture improvement is operational rather than structural:

- background execution for long-running workflow jobs

The frontend/backend split itself is now the baseline, not a future transition target.
