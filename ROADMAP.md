# Roadmap

This roadmap reflects the agreed implementation sequence for the AI Job Application Agent.

The more complete strategy document lives in [docs/project_strategy.md](docs/project_strategy.md). This file keeps the high-level execution order short and scannable.

## Phase 1: Strengthen the Streamlit Product Shell

- Keep sidebar navigation because the app has multiple workflows
- Move the app to a wide layout
- Apply the GitHub-agent visual system to the main content area
- Keep Streamlit as the first deployment target

## Phase 2: Add Shared Domain Models

- Introduce `src/schemas.py` for candidate, job, fit, and tailored-output objects
- Introduce `src/errors.py` for typed failures
- Normalize resume, LinkedIn, and JD outputs into shared internal models

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
- Next work in sequence is review-loop refinement and deployment hardening

## Phase 4: Deterministic Reports and Exports

- Add `src/report_builder.py`
- Render structured fit and tailoring results in deterministic sections
- Add Markdown export first
- Add PDF export once the report structure is stable

Status:
- Deterministic report assembly implemented
- Markdown and PDF export implemented
- PDF refinement and template polish remain future work

## Phase 5: Streamlit MVP Deployment

- Align the local Python version with the deployment runtime
- Finalize deployment configuration for Streamlit hosting
- Publish the first hosted MVP
- Gather product feedback before expanding infrastructure

## Phase 6: Backend Extraction

- Expose core orchestration through FastAPI
- Add persistent storage if product needs justify it
- Add Redis only if background jobs or shared cache become necessary
- Keep Streamlit usable as a demo or internal client during the transition

## Phase 7: Production Frontend

- Build a Next.js frontend if the app outgrows Streamlit
- Connect it to the FastAPI backend
- Move the public-facing product UI to the new frontend when ready
