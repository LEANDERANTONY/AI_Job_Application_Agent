# Deployment Plan

Current deployment and architecture plan for the next stage of the AI Job Application Agent.

Last updated: March 18, 2026.

---

## Current State

The live product is already deployed as:

- Render web service for the Streamlit app
- Supabase for Google auth, persisted usage, and saved workspace state
- OpenAI for AI-assisted workflow and assistant features

That current deployment remains the production baseline.

---

## Next Strategic Decision

The next major expansion is **job search and scraping**, and that should **not** be implemented inside Streamlit request flow.

The chosen direction is:

- keep Streamlit as the current user-facing app
- add a separate **FastAPI backend**
- deploy that backend in **Docker**
- let Streamlit call the backend over HTTP
- keep Supabase Postgres as the first shared persistence layer

This is the correct path because job discovery and scraping introduce:

- slower network-bound operations
- retry and provider-failure concerns
- possible anti-bot / browser-automation requirements
- future need for background execution
- stronger need for service boundaries than the current single Streamlit runtime can provide

---

## Target Architecture

### Existing production app

- Render web service 1: Streamlit app
- Supabase:
  - auth
  - app users
  - usage events
  - saved workspaces

### Next addition

- Render web service 2: FastAPI job backend
- same Supabase project for first persistence path

### Later, only if needed

- background worker service
- Redis for queueing / job coordination
- object storage for heavy artifacts or cached source payloads

---

## Architectural Boundary

### Streamlit should own

- search form
- search filters
- results display
- selecting a job
- handing selected job content into the existing JD workflow

### FastAPI should own

- provider adapters
- scraping / source fetch orchestration
- normalization into shared job-posting schemas
- dedupe and ranking
- persistence of job-search results if we keep them
- retries, timeouts, and provider-health behavior

This keeps UI concerns and ingestion concerns separate from day one.

---

## Why FastAPI Instead Of More Streamlit Logic

FastAPI is the right next boundary because:

- job search should not block the Streamlit app script unnecessarily
- backend routes can be reused later by another frontend
- provider logic is easier to test outside the UI
- retries, status reporting, and background execution fit an API service better than a Streamlit rerun loop
- Dockerizing a backend service is a cleaner place to host scraping dependencies than pushing all of them into the main Streamlit app image

This is also the cleanest path toward future concurrency, such as:

- running a job search while the app remains interactive
- letting the assistant and workflow stay separate from scraping work
- later background refreshes of provider results

---

## Why We Are Not Switching Database Or Framework

### Database

We are **not** moving away from Postgres right now.

Supabase Postgres still fits the next step because we already use it for:

- users
- quotas
- saved workspaces

and it can also support:

- saved jobs
- search runs
- normalized job postings
- job-source metadata

MongoDB is not justified yet because the product still has strong relational needs across users, workflow state, quotas, and saved jobs.

### Backend framework

We are **not** adopting Django for this subsystem.

FastAPI is the better fit because this is an API-first service boundary, not a server-rendered monolith.

### LangChain / LlamaIndex

We are **not** introducing LangChain or LlamaIndex as the core backend architecture.

They do not meaningfully simplify:

- deployment
- Dockerization
- scraping adapters
- persistence
- retries
- provider normalization

If semantic retrieval over stored jobs becomes useful later, retrieval tooling can be evaluated then. It is not the right foundation for the backend rollout itself.

---

## First Backend Scope

The first FastAPI service should stay narrow.

### Initial capabilities

- search one or two provider types
- return normalized job postings
- fetch enough detail to populate the JD workflow
- allow Streamlit to select one job and send that content into `Manual JD Input`

### Do not build yet

- full autonomous multi-site crawling
- background job queue
- semantic job retrieval
- heavy ranking ML
- paid-job-board scale infrastructure

The point of the first backend is to establish the correct service boundary, not to overbuild the scraping platform on day one.

---

## Proposed Repo Shape

Inside the current repo, the next layer should likely look like this:

- `backend/`
  - FastAPI app entrypoint
  - API routers
  - backend config
- `src/job_sources/`
  - one adapter per provider
- `src/job_search_service.py`
  - fan-out, normalization, dedupe, ranking
- `src/job_normalizer.py`
  - provider payload to shared schema mapping
- `src/job_store.py`
  - persistence helpers for search runs / saved jobs if we add them
- `src/schemas.py`
  - add shared job-search models

The existing Streamlit app should call the backend instead of importing provider adapters directly once the boundary is introduced.

---

## Suggested Shared Schemas

The backend should normalize everything into typed models such as:

- `JobSearchQuery`
- `JobPosting`
- `JobSearchResult`
- `JobPostingDetail`
- `SavedJob`

Each provider adapter should return those schemas, not provider-specific shapes.

That is critical because the rest of the app should not care whether a posting came from:

- LinkedIn
- Indeed
- Greenhouse
- Lever
- a company careers page

---

## Hosting Shape

### Current production

- Render: Streamlit app

### Next deployment

- Render: Streamlit app
- Render: FastAPI backend
- Supabase: shared persistence and auth-related product data

### Docker posture

Both services should remain Dockerized where helpful, but the backend especially should be containerized because source adapters may later require:

- browser automation
- HTML parsing dependencies
- custom system packages
- stable runtime control across providers

---

## Local-First Rollout Strategy

This work should be delivered without breaking the currently hosted Streamlit app.

The rollout rule is:

- build locally first
- deploy the backend separately
- connect production only after the backend is stable

### Local development shape

- local Streamlit app: `http://localhost:8501`
- local FastAPI backend: `http://localhost:8000`

During the first implementation pass, local Streamlit should call the local backend directly.

That allows:

- backend iteration without touching the hosted app
- end-to-end UI testing before any production cutover
- provider debugging without using the live user-facing deployment

### Required config boundary

Add an environment variable for the backend base URL, for example:

- `JOB_BACKEND_BASE_URL=http://localhost:8000` for local development
- `JOB_BACKEND_BASE_URL=https://<job-backend>.onrender.com` for hosted deployment

This keeps the Streamlit integration environment-driven instead of hardcoded.

### Feature flag requirement

The new job-search backend path should remain behind a feature flag until the backend is proven stable.

Example:

- `ENABLE_JOB_SEARCH_BACKEND=false` in current production
- `ENABLE_JOB_SEARCH_BACKEND=true` locally during development

This allows the backend integration code to ship before the public UI path is exposed.

### Safe deployment sequence

1. Build and test FastAPI locally.
2. Connect local Streamlit to local FastAPI.
3. Deploy the FastAPI backend as a separate Render service.
4. Test the deployed backend directly through its own health and search endpoints.
5. Point local Streamlit at the hosted backend and verify end-to-end behavior.
6. Only then enable the backend-driven job-search path in the hosted Streamlit app.

This sequence is the safest way to avoid breaking the currently live product.

---

## Phase Plan

## Phase 1: Backend foundation

- create FastAPI service
- define shared job-search schemas
- add one or two provider adapters
- add `/health`
- add `/jobs/search`
- return normalized postings
- integrate Streamlit with backend search API

Success criteria:

- user can search jobs from Streamlit
- results render without scraping logic living in Streamlit
- selecting a result can feed the existing JD workflow

## Phase 2: Better job ingestion

- add detailed posting fetch where needed
- improve normalization quality
- add dedupe rules
- add provider-specific error handling
- persist search runs or saved jobs if useful

Success criteria:

- multiple sources can feed one consistent results view
- noisy duplicates are controlled
- provider failures do not break the entire search response

## Phase 3: Operational hardening

- add metrics and structured logging
- add backend smoke checks
- add retry and timeout policy per provider
- add provider health visibility
- make Docker runtime dependable in Render

Success criteria:

- backend failures are diagnosable
- providers degrade gracefully
- deployment is stable enough for real usage

## Phase 4: Background execution if justified

- add async search-job model
- add worker process
- add Redis only if job coordination truly requires it
- let Streamlit poll status endpoints instead of waiting on long-running scrape requests

Success criteria:

- long-running provider work no longer ties up request/response cycles
- user experience stays responsive during heavier search operations

---

## Immediate Next Implementation Work

The next concrete repo work should be:

1. decide the backend package location and service entrypoint
2. define shared job-search schemas in `src/schemas.py`
3. create the FastAPI app skeleton
4. define the provider-adapter interface
5. pick the first one or two sources to support
6. wire Streamlit to call the backend instead of doing any source work locally
7. add environment-driven backend URL configuration
8. add a feature flag so hosted production can keep the current path disabled until the backend is validated

---

## Key Rule Going Forward

Do not let job-source logic spread into the Streamlit pages.

If we keep that boundary clean:

- backend extraction will stay manageable
- provider additions will stay safer
- deployment complexity will stay localized
- future frontend changes will be much easier

That is the most important architectural constraint for the next phase.
