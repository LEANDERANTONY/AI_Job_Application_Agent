# Project Strategy

This document captures the current product and architecture direction for the AI Job Application Agent.

## Current Product Position

The app is currently a Streamlit-first authenticated workflow product with three active user-facing areas:

- `Upload Resume`
- `Job Search` placeholder
- `Manual JD Input`

The sidebar account panel is also part of the core product flow because it owns:

- Google sign-in
- sign-out
- `Reload Workspace`

The app is still an MVP, but it is no longer parser-only. It already includes supervised orchestration, tailored resume generation, cover letter generation, deterministic report assembly, export flows, Google sign-in, persisted usage tracking, plan-based daily quotas, and one latest saved-workspace snapshot per user.

## Product Boundaries

The active product scope is intentionally narrow:

- resume in
- JD in
- grounded recruiter-facing artifacts out

What that means in practice:

- no job-board integration yet
- no automated application submission
- no public multi-client API
- no separate history browser

The saved-workspace feature is deliberately lightweight. The app stores one latest authenticated snapshot and restores it back into `Manual JD Input` through the sidebar `Reload Workspace` action.

## UI Strategy

### Keep Streamlit for the current product

Streamlit is still the right shell because it keeps the iteration loop short while the workflow and export surfaces continue to mature.

That remains true even after auth, quotas, and saved-workspace persistence, because the business logic already lives outside the page layer.

### Keep the sidebar

Unlike the single-flow GitHub reference app, this product benefits from a sidebar because users move across:

- account actions
- resume intake
- JD workflow
- job-search placeholder

### Current UX stance

The current UI is intentionally login-first for resume intake. That keeps:

- assisted usage
- saved-workspace reload
- quota enforcement
- account identity

under one coherent model instead of splitting the product between anonymous and authenticated paths.

## Architecture Strategy

The architecture is still layered correctly:

- `src/parsers/` for ingestion
- `src/services/` for deterministic business logic
- `src/agents/` for supervised assisted orchestration
- builders/exporters for deterministic final artifacts
- auth/persistence stores for account-bound behavior
- `src/ui/` for Streamlit-only composition

The key design rule is unchanged:

- model calls are bounded and explicit
- deterministic builders sit at the download boundary
- Streamlit state stays in the UI layer
- domain logic stays reusable outside Streamlit

## Assisted Workflow Strategy

The active orchestrator path is intentionally smaller than the earlier live-agent design.

The current supervised sequence is:

1. fit
2. tailoring
3. strategy
4. review
5. resume generation
6. cover letter

Important consequences:

- `ProfileAgent` and `JobAgent` are no longer part of the live orchestrator path
- Review acts as a direct correcting stage rather than a trigger for a second full rerun loop
- higher-trust model budget is reserved for the later grounding-sensitive stages

## Persistence Strategy

The current persistence model is intentionally cheap and narrow:

- persist `app_users`
- persist `usage_events`
- persist one latest `saved_workspaces` row per user

The product does not currently need:

- `workflow_runs`
- `artifacts`
- object storage for binary files

Instead, the app stores structured payload JSON and regenerates the latest artifacts from those payloads when needed.

This keeps the persistence surface small while still supporting:

- quota enforcement
- latest-workspace reload
- stable reconstruction of the saved state

## Hosting Strategy

The chosen deployment direction is:

- Render Docker web service for the Streamlit app
- Supabase free tier for auth and persistence
- WeasyPrint as the intended hosted PDF renderer

Docker is part of the plan because the PDF runtime needs controlled native libraries, not because the product already needs a decomposed backend platform.

## What We Should Keep Doing

- keep Streamlit as the active product shell
- keep pushing logic into services, builders, and stores
- keep the download boundary deterministic
- keep saved-workspace payload compatibility safe over time
- keep the hosted runtime stable before adding new major scope

## What We Should Not Add Yet

- FastAPI, unless a second client or async execution actually appears
- Redis, unless background jobs or shared caching become necessary
- object storage, unless binary retention becomes a product requirement
- a Next.js frontend, until an API boundary is genuinely needed

## Near-Term Priorities

The highest-value work from the current product state is:

1. deployment hardening
2. doc and runtime consistency
3. saved-workspace reload polish
4. artifact/export polish inside the active JD flow
5. only then, broader feature expansion

## Longer-Term Migration Path

If the product outgrows Streamlit, the migration path should still be:

1. keep the current service and store boundaries stable
2. expose those boundaries through FastAPI
3. add Redis only if async/background work is required
4. move the public frontend to Next.js only after that API boundary exists

That path still avoids rewriting the business logic twice.
