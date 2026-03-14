# Project Strategy

This document captures the current architectural decisions for the AI Job Application Agent, why they were made, and how the project should evolve from a Streamlit MVP into a production-grade application.

## Current Product Position

The app is currently a Streamlit-first authenticated workflow product with four user-facing flows:

- upload and parse a resume
- search jobs placeholder
- upload or paste a job description and run the supervised workflow
- review authenticated history and regenerate saved downloads

The product is still an MVP, but it is no longer parser-only. It already includes supervised agent orchestration, tailored resume generation, deterministic report assembly, export packaging, Google sign-in, persisted usage tracking, plan-based daily quotas, and authenticated workflow history.

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

Unlike the GitHub agent, this app has multiple workflows rather than one primary flow. A sidebar is appropriate here because it improves navigation between resume intake, JD parsing, and later application workflows.

## UI Decisions

### Keep Streamlit for the first deployed version

We are still keeping Streamlit for the first serious deployed version because it is the fastest path to:

- validate the application workflow
- iterate on parsing, tailoring, and review loops
- ship a working demo quickly
- keep the engineering surface manageable

That decision is still holding up even after adding auth, quotas, and history, because the business logic already lives outside the page layer.

### Keep the sidebar

The app should retain a sidebar because:

- the product has multiple user tasks
- users may move between resume, JD, history, and job-search flows
- a linear top-down-only interface would make navigation worse for this domain

### Reuse the GitHub agent visual system selectively

The AI Job Application Agent should still borrow the GitHub agent's design language where it helps:

- dark navy page background
- white cards and shells
- strong blue primary actions
- product-like layout and spacing
- structured result panels rather than raw text dumps

The main difference is navigation model and workflow complexity, not the basic product-shell direction.

## Current Architecture

The app now has a layered architecture with clear separation between UI, deterministic domain logic, orchestration, assistance, and persistence.

### The main runtime layers today

- `src/ui/`: Streamlit pages, navigation, state helpers, and the UI workflow boundary
- `src/parsers/`: defensive file and text ingestion
- `src/services/`: deterministic normalization, fit analysis, and tailoring logic
- `src/agents/`: supervised specialist-agent pipeline with review passes and resume generation
- `src/openai_service.py` and `src/assistant_service.py`: model access, routing, usage tracking, and conversational help
- `src/auth_service.py` plus store modules: authenticated persistence for users, usage, workflows, and artifacts
- builders/exporters: deterministic report and resume assembly plus export generation

### What the app is today

- Streamlit UI with sidebar navigation
- deterministic parsing, normalization, and fit analysis
- supervised specialist-agent workflow with bounded review-driven revision
- deterministic report and tailored-resume builders
- Markdown, PDF, and ZIP export flows
- two-mode grounded in-app assistant
- Google sign-in via Supabase
- persisted user, usage, workflow, and artifact records
- plan-based daily assisted quotas
- saved-run history regeneration without re-running OpenAI
- broad test coverage across parsing, services, orchestration, exports, auth, persistence, and UI workflow state

### What the app is not yet

- a job-board integration or automated application submission system
- an async worker platform with queues and retries
- an object-storage-backed artifact retention system
- a public multi-client API platform
- a separate production frontend beyond Streamlit

The architecture is therefore backend-ready, but not yet fully platform-extracted.

## Target Agent Architecture

We want a genuine but controlled multi-agent design, and that is already the active pattern in the codebase.

The correct pattern is not an unconstrained swarm. The correct pattern is a supervised pipeline of specialist agents that exchange structured objects and feed a deterministic final output layer.

### Agent roles

#### `Orchestrator Agent`

Owns workflow control:

- determines which specialist runs next
- tracks run state
- validates prerequisites
- enforces bounded review passes
- hands the final state to deterministic builders

#### `Profile Agent`

Builds a normalized candidate profile from resume inputs:

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

#### `Resume Generation Agent`

Produces the final tailored resume artifact after review approval or the final allowed revision pass.

### Key design rule

Agents should not exchange unstructured prose as the main system contract.

They should exchange typed internal objects, and the final report should be assembled deterministically in code.

That rule now also applies to persistence: authenticated history stores structured payload JSON so historical exports can be reconstructed deterministically.

## Operating Principles

- Keep deterministic builders at the boundary of anything user-downloadable.
- Use model calls only for bounded, explicitly triggered assisted steps.
- Keep Streamlit-specific state management in `src/ui/` and keep domain logic transport-agnostic.
- Persist only the minimum useful authenticated history needed for exact historical regeneration.
- Prefer Postgres payloads over blob storage until product needs justify object storage.
- Treat quotas and usage accounting as product controls, not as ad hoc logging.

## Streamlit-First Delivery Strategy

We are intentionally not extracting to a separate backend yet.

### Why this is still the right choice

The project already has:

- authenticated users
- persisted usage and quotas
- workflow history
- supervised orchestration
- deterministic export assembly

But it still has only one real client: the Streamlit app. Extracting to `FastAPI + worker + separate frontend` before multi-client or async needs appear would add more platform work than product value.

### What we should keep doing now

- keep Streamlit as the active product shell
- continue pushing business logic into services, builders, and stores
- harden the hosted deployment path
- tighten history payload compatibility and migration safety
- only introduce new infrastructure when the product actually needs it

## Backend and Frontend Migration Plan

### When FastAPI becomes worth it

FastAPI should be introduced when at least one of these becomes important:

- another client besides Streamlit needs the same workflow entrypoints
- background jobs are needed for long-running exports or application workflows
- admin or operational tooling needs a stable API boundary
- tighter service-level auth and data isolation is needed beyond the current app shell

### When Redis becomes worth it

Redis should be introduced only when we need:

- queued background jobs
- task retries
- shared cache across processes
- worker coordination

Redis is still unnecessary for the current product.

### When object storage becomes worth it

Object storage should be introduced only when the product truly needs to retain or share large binary files.

Right now the cheaper and simpler model is:

- keep metadata plus saved workflow payloads in Postgres
- regenerate PDFs and ZIP bundles on demand
- avoid storing large binaries unless retention or external sharing becomes mandatory

### Frontend target later

If the app outgrows Streamlit, the recommended frontend target remains `Next.js`, not a raw React SPA.

Why:

- built-in routing
- strong deployment story
- easier auth integration
- better ergonomics for a product UI with history and account state

### Transitional architecture

The migration path should be:

1. Streamlit remains the active product shell.
2. Existing services and stores become the stable backend boundary.
3. FastAPI wraps those boundaries only when a second client or async execution is needed.
4. A Next.js frontend becomes worthwhile only after that API boundary exists.

This still avoids rewriting the business logic twice.

## Hosting Strategy

### Phase 1: current hosted target

- Streamlit Community Cloud or an equivalent Streamlit-friendly host
- Supabase for auth and Postgres persistence

This remains sufficient while the product is single-client and workloads are moderate.

### Phase 2: backend-backed deployment

When a separate backend becomes justified:

- frontend: Vercel or another Next.js host
- backend: Render, Railway, Fly.io, or another API/container host
- database: managed Postgres
- queue/cache: managed Redis only if async work demands it

## Re-Baselined Timeline

The timeline below is an implementation sequence from the current product state, not a calendar promise.

### Completed foundation

- Streamlit product shell with sidebar navigation
- typed schemas and deterministic services
- supervised specialist-agent workflow with review loop
- tailored resume and report builders
- Markdown, PDF, and ZIP export paths
- grounded assistant and task-aware model routing
- Google sign-in via Supabase
- persisted users, usage events, daily quotas, workflow history, and artifact metadata
- historical regeneration from saved run payloads

### Current focus

- deployment hardening for a real hosted environment
- README and architecture alignment
- safer long-term history payload compatibility

### Next meaningful expansion

- payload versioning for saved workflow records
- better history and quota UX polish
- optional object storage only if binary retention becomes necessary
- backend extraction only when multiple clients or async work make it worthwhile
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

1. Add `src/report_builder.py` so current deterministic and agent outputs can be rendered into a stable recruiter-facing package.
2. Add export support, starting with Markdown and structured text download.
3. Improve the review layer so revision requests can feed back into another tailoring pass cleanly.
4. Align the local Python version with the planned Streamlit deployment runtime.
5. Prepare the first hosted Streamlit MVP before extracting FastAPI.

Current progress:

- `src/report_builder.py` implemented
- Markdown and PDF export implemented
- next meaningful work is review-loop refinement and deployment hardening

## Decision Summary

The current agreed direction is:

- keep Streamlit for the first deployed version
- keep the sidebar because this is a multi-workflow app
- adopt the GitHub agent's visual system, but not its navigation model
- implement a supervised multi-agent architecture, not a loose swarm
- keep final output structure deterministic
- delay FastAPI, Redis, Docker, and Next.js until the workflow and service boundaries are stable
- write the core logic so those platforms can be added later without a rewrite
