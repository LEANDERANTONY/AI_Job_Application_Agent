# Roadmap

This roadmap reflects the agreed implementation sequence for the AI Job Application Agent.

The more complete strategy document lives in [docs/project_strategy.md](docs/project_strategy.md). This file keeps the high-level execution order short and scannable.

## Phase 1: Streamlit Product Shell

- Keep sidebar navigation because the app has multiple workflows
- Move the app to a wide layout
- Apply the GitHub-agent visual system to the main content area
- Keep Streamlit as the first deployment target

Status:
- Completed

## Phase 2: Add Shared Domain Models

- Introduce `src/schemas.py` for candidate, job, fit, and tailored-output objects
- Introduce `src/errors.py` for typed failures
- Normalize resume and JD outputs into shared internal models

Status:
- Completed

## Phase 3: Build the First Real Agent Workflow

- Add `src/openai_service.py`
- Add `src/prompts.py`
- Add supervised specialist agents:
  - profile
  - job
  - fit
  - tailoring
  - review
- Add an orchestrator entrypoint for end-to-end runs

Status:
- Core workflow foundation implemented
- Deterministic and supervised workflow layers implemented
- Review-loop refinement implemented
- Resume generation and strategy layers implemented

## Phase 4: Deterministic Reports and Exports

- Add `src/report_builder.py`
- Render structured fit and tailoring results in deterministic sections
- Add Markdown export first
- Add PDF export once the report structure is stable

Status:
- Deterministic report assembly implemented
- Tailored resume builder implemented
- Markdown, PDF, and ZIP export implemented

## Phase 5: Grounded Assistance and Model Controls

- Add the two-mode assistant panel for product help and grounded resume/application Q&A
- Route assisted tasks across model tiers instead of relying on one global model
- Track assisted usage at the session level

Status:
- Implemented

## Phase 6: Auth, Quotas, and History Persistence

- Add Google sign-in through Supabase
- Persist lightweight app-user records
- Persist usage events and enforce daily plan-based quotas
- Persist workflow runs and artifact metadata
- Add a dedicated History page
- Regenerate historical downloads from saved workflow payloads instead of current session state

Status:
- Implemented in the codebase
- Supabase project bootstrap remains operator setup work

## Phase 7: Deployment Hardening

- Align the local Python version with the deployment runtime
- Finalize deployment configuration for Streamlit hosting
- Publish the first hosted MVP
- Gather product feedback before expanding infrastructure

Status:
- Next active delivery focus

## Phase 8: Persistence Hardening

- Add payload versioning for saved workflow reconstruction
- Tighten migration guidance for existing Supabase projects
- Consider object storage only if binary artifact retention becomes necessary

Status:
- Not started

## Phase 9: Backend Extraction

- Expose core orchestration through FastAPI
- Reuse the existing service, builder, and store boundaries
- Add Redis only if background jobs or shared cache become necessary
- Keep Streamlit usable as a demo or internal client during the transition

Status:
- Deferred until a second client or async execution is justified

## Phase 10: Production Frontend

- Build a Next.js frontend if the app outgrows Streamlit
- Connect it to the FastAPI backend
- Move the public-facing product UI to the new frontend when ready

Status:
- Deferred
