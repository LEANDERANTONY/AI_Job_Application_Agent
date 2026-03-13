# Project Strategy

This document captures the current architectural decisions for the AI Job Application Agent, why they were made, and how the project should evolve from a Streamlit MVP into a production-grade application.

## Current Product Position

The app is currently an intake-focused MVP with four user-facing workflows:

- upload and parse a resume
- import a LinkedIn data export
- search jobs placeholder
- upload or paste a job description

The existing implementation is intentionally lightweight. It proves the candidate-input and job-input flows before adding heavier orchestration, model calls, persistence, and production infrastructure.

## Reference Pattern

The primary reference app for this project is `Github_Agent`.

What we are reusing from that project:

- product-style Streamlit presentation rather than notebook-style UI
- `src/` package structure
- documented architecture and ADRs
- deterministic final report assembly as a design principle
- separation between UI, orchestration, rules, model calls, and exports

What we are intentionally not copying exactly:

- the no-sidebar layout rule

Unlike the GitHub agent, this app has multiple workflows rather than one primary flow. A sidebar is appropriate here because it improves navigation between resume intake, LinkedIn import, JD parsing, and later application workflows.

## UI Decisions

### Keep Streamlit for the first deployed version

We will deploy the first public version with Streamlit because it is the fastest path to:

- validate the application workflow
- iterate on parsing and tailoring
- ship a working demo quickly
- keep the engineering surface manageable

### Keep the sidebar

The app should retain a sidebar because:

- the product has multiple user tasks
- users may move between resume, LinkedIn, JD, and job-search flows
- a linear top-down-only interface would make navigation worse for this domain

### Reuse the GitHub agent visual system

The AI Job Application Agent should still borrow the GitHub agent's design language:

- dark navy page background
- white cards and shells
- strong blue primary actions
- product-like layout and spacing
- structured result panels rather than raw text dumps

The main difference is navigation model, not visual identity.

## Current Architecture

The app currently has three working ingestion modules:

- `src/resume_parser.py`
- `src/jd_parser.py`
- `src/linkedin_parser.py`

And one UI shell:

- `app.py`

This is enough for the current MVP, but it is not yet an agentic or production-ready architecture.

### What the app is today

- Streamlit UI with sidebar navigation
- deterministic parsing and extraction
- session-state persistence for a single user session
- parser-focused unit tests

### What the app is not yet

- a multi-agent system
- a backend/API platform
- a multi-user persistent product
- a report/export engine
- a job-application automation pipeline

## Target Agent Architecture

We want a genuine but controlled multi-agent design.

The correct pattern is not an unconstrained swarm. The correct pattern is a supervised pipeline of specialist agents that exchange structured objects and feed a deterministic final output layer.

### Agent roles

#### `Orchestrator Agent`

Owns workflow control:

- determines which specialist runs next
- tracks run state
- validates prerequisites
- assembles the overall application package

#### `Profile Agent`

Builds a normalized candidate profile from resume and LinkedIn inputs:

- skills
- experience
- education
- certifications
- projects
- evidence-backed strengths

#### `Job Agent`

Structures the job description into:

- role title
- must-have requirements
- preferred requirements
- domain keywords
- experience expectations
- location/work model signals

#### `Fit Analysis Agent`

Compares candidate profile against job requirements:

- fit summary
- matched qualifications
- gaps
- missing evidence
- risks
- readiness score inputs

#### `Tailoring Agent`

Produces targeted application content:

- tailored professional summary
- rewritten or prioritized resume bullets
- highlighted skills
- recruiter-facing emphasis points

#### `Application Strategy Agent`

Produces downstream application guidance:

- recruiter positioning
- cover-letter talking points
- interview preparation themes
- portfolio/project emphasis suggestions

#### `Review Agent`

Acts as the quality gate:

- checks grounding against the actual inputs
- flags unsupported claims
- catches drift or hallucinated resume content
- validates schema completeness before final rendering

### Key design rule

Agents should not exchange unstructured prose as the main system contract.

They should exchange typed internal objects, and the final report should be assembled deterministically in code.

## Planned Core Modules

The next architecture step is to evolve from parser-only modules to a full service and agent layout.

### Planned `src/` structure

```text
src/
|- __init__.py
|- config.py
|- errors.py
|- schemas.py
|- prompts.py
|- openai_service.py
|- report_builder.py
|- parsers/
|  |- resume_parser.py
|  |- jd_parser.py
|  \- linkedin_parser.py
|- services/
|  |- profile_service.py
|  |- job_service.py
|  |- fit_service.py
|  |- tailoring_service.py
|  \- job_sources_service.py
\- agents/
   |- orchestrator.py
   |- profile_agent.py
   |- job_agent.py
   |- fit_agent.py
   |- tailoring_agent.py
   |- strategy_agent.py
   \- review_agent.py
```

### Module responsibilities

- `app.py`
  Streamlit UI only
- `schemas.py`
  typed shared models
- `errors.py`
  typed application errors
- `prompts.py`
  centralized prompt templates
- `openai_service.py`
  model calls only
- `services/*`
  deterministic domain logic and normalization
- `agents/*`
  controlled LLM-specialist orchestration
- `report_builder.py`
  deterministic final output assembly

## Streamlit-First Delivery Strategy

We are intentionally not starting with a full production backend stack.

### Why

Starting with `FastAPI + Redis + Postgres + React/Next.js + Docker` would add too much platform complexity before the product workflow is validated.

For this app, the correct order is:

1. finish the core job-application workflow
2. stabilize the domain models and agent contracts
3. then extract the backend boundary

### What we should do now

- keep Streamlit as the deployable frontend
- move business logic out of `app.py`
- make Streamlit call service and agent entrypoints
- keep the core logic transport-agnostic so FastAPI can wrap it later

This gives us a backend-ready codebase without forcing a premature platform split.

## Backend and Frontend Migration Plan

### When FastAPI becomes worth it

FastAPI should be introduced when at least one of these becomes important:

- multi-user accounts and saved history
- external client access beyond Streamlit
- background jobs for long-running tailoring, scraping, or exports
- stronger auth and data boundaries
- frontend independence from Streamlit

### When Redis becomes worth it

Redis should be introduced only when we need:

- queued background jobs
- shared cache across processes
- task retries
- async worker coordination

Redis is not required for the current MVP.

### When Docker becomes worth it

Docker is optional for the current Streamlit deployment.

It becomes useful once we run:

- a standalone FastAPI app
- worker processes
- Postgres/Redis-backed local development
- environment parity between local and production

### Frontend target later

If we move beyond Streamlit, the recommended frontend target is `Next.js`, not a raw React SPA.

Why:

- built-in routing
- strong deployment story
- easier auth and full-stack patterns
- better production ergonomics for a product UI

### Transitional architecture

The migration path should be:

1. Streamlit app calls local services directly
2. same services get wrapped by FastAPI endpoints
3. Streamlit can remain as a demo or internal client
4. Next.js becomes the public-facing frontend later

This avoids rewriting the business logic twice.

## Hosting Strategy

### Phase 1: initial public deployment

- Streamlit Community Cloud or an equivalent Streamlit-friendly host

This is enough for the first public MVP if:

- the app remains mostly session-based
- workloads are modest
- the main goal is validation and portfolio/demo use

### Phase 2: backend-backed deployment

When we introduce a separate backend:

- frontend: Vercel or another Next.js host
- backend: Render, Railway, Fly.io, or another container/API host
- database: managed Postgres
- cache/queue: managed Redis

This is the better architecture for a production-grade application.

## Timeline

The timeline below is an implementation sequence, not a calendar promise. It should be treated as a phased plan.

### Phase 0: current baseline

Status:

- resume parsing works
- JD parsing works
- LinkedIn import works
- tests cover the parser layer

### Phase 1: product shell and domain models

Indicative effort: 1 to 2 weeks

Goals:

- apply the GitHub-agent visual system while keeping the sidebar
- move to `layout="wide"`
- introduce `schemas.py`
- introduce `errors.py`
- normalize parsed inputs into shared models

### Phase 2: first real agent workflow

Indicative effort: 2 to 3 weeks

Goals:

- add `openai_service.py` and `prompts.py`
- implement the orchestrator plus profile, job, fit, tailoring, and review agents
- build the first end-to-end flow:
  - candidate inputs
  - job input
  - fit analysis
  - tailored output

### Phase 3: deterministic report and export layer

Indicative effort: 1 to 2 weeks

Goals:

- add `report_builder.py`
- render deterministic result sections in Streamlit
- add Markdown export first
- add PDF export when the report structure stabilizes

### Phase 4: Streamlit MVP deployment

Indicative effort: 1 week

Goals:

- align local Python version with deployment target
- finalize deployment configuration
- publish the first hosted Streamlit version
- collect feedback on workflow quality

### Phase 5: backend extraction

Indicative effort: 2 to 4 weeks

Goals:

- expose the core orchestration through FastAPI
- move persistence to Postgres if needed
- add Redis only if background jobs or shared cache become necessary
- keep Streamlit as a client during the transition

### Phase 6: production frontend

Indicative effort: 3 to 5 weeks

Goals:

- build a Next.js frontend
- connect it to the FastAPI backend
- move the public product UI off Streamlit if product needs justify it

## Immediate Next Steps

These are the next practical engineering steps for this repository.

1. Apply the GitHub-agent style system to this Streamlit app while preserving the sidebar.
2. Add `src/schemas.py` for candidate, job, fit, and tailored-output models.
3. Add `src/errors.py` for typed application failures.
4. Refactor `app.py` so it becomes a thin UI layer over services.
5. Build the first orchestrated feature:
   - resume or LinkedIn input
   - job description input
   - fit analysis
   - tailored resume output

## Decision Summary

The current agreed direction is:

- keep Streamlit for the first deployed version
- keep the sidebar because this is a multi-workflow app
- adopt the GitHub agent's visual system, but not its navigation model
- implement a supervised multi-agent architecture, not a loose swarm
- keep final output structure deterministic
- delay FastAPI, Redis, Docker, and Next.js until the workflow and service boundaries are stable
- write the core logic so those platforms can be added later without a rewrite

