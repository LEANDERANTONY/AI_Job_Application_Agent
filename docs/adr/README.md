# ADR Index

This directory tracks the architectural decisions that shape the AI Job Application Agent.

ADRs are historical records — each one captures **the decision context at the moment it was made**. Several earlier entries describe the old Streamlit-first product phase; they remain in the index for traceability but have been superseded by later decisions.

The accepted set is grouped into four thematic clusters to make the current production picture easier to read at a glance. New ADRs land at the end of the relevant cluster.

## Accepted

### Core product + RAG-equivalent agent workflow

- [ADR-001: Lightweight document parsing for MVP](ADR-001-lightweight-document-parsing.md)
- [ADR-002: Demo assets for reproducible product flows](ADR-002-demo-assets-for-reproducible-product-flows.md)
- [ADR-007: Remove LinkedIn import from active product scope](ADR-007-remove-linkedin-import-from-active-product-scope.md)
- [ADR-009: Google sign-in via Supabase for persistent identity](ADR-009-google-sign-in-via-supabase-for-persistent-identity.md)
- [ADR-010: Single-pass review corrections and task-tuned model budgets](ADR-010-single-pass-review-corrections-and-task-tuned-model-budgets.md)
- [ADR-011: Unified grounded assistant surface](ADR-011-unified-grounded-assistant-surface.md)
- [ADR-012: Next.js workspace and FastAPI runtime baseline](ADR-012-nextjs-workspace-and-fastapi-runtime-baseline.md)
- [ADR-013: Cached jobs cache layer with scheduled refresh](ADR-013-cached-jobs-cache-layer-with-scheduled-refresh.md)
- [ADR-014: Postgres RPC for ranked job search](ADR-014-postgres-rpc-for-ranked-search.md)
- [ADR-015: DOCX-first artifact export with theme palette](ADR-015-docx-first-artifact-export-with-theme-palette.md)
- [ADR-016: Conversational LLM resume builder](ADR-016-conversational-llm-resume-builder.md)
- [ADR-017: Workspace assistant — ungated and state-aware context](ADR-017-workspace-assistant-state-aware-context.md)
- [ADR-018: Three-layer LLM retry and per-agent fallback isolation](ADR-018-three-layer-llm-retry-and-per-agent-fallback-isolation.md)
- [ADR-019: Independent step navigation in the workspace](ADR-019-independent-step-navigation.md)

### Tiering + payments

- [ADR-020: Tier resolution via a single shim function](ADR-020-tier-resolution-via-single-shim-function.md)
- [ADR-021: Atomic quota with refund-on-failure](ADR-021-atomic-quota-with-refund-on-failure.md)
- [ADR-022: Tier-aware model selection via constructor injection](ADR-022-tier-aware-model-selection-via-constructor-injection.md)
- [ADR-023: Lemon Squeezy as Merchant of Record for v1](ADR-023-lemon-squeezy-merchant-of-record-for-v1.md)

### Observability + compliance

- [ADR-024: Observability stack — Sentry + PostHog with consent-gated analytics](ADR-024-observability-stack-sentry-and-posthog.md)
- [ADR-025: EU cookie consent banner + GDPR-aligned analytics gating](ADR-025-eu-cookie-consent-banner-and-gdpr-analytics-gating.md)

### Maintenance + operational posture

- [ADR-026: Manual-only `nightly_eval` at pre-revenue stage](ADR-026-manual-only-nightly-eval-at-pre-revenue-stage.md)

## Superseded

- [ADR-003: Streamlit session state for navigation and persistence](ADR-003-streamlit-session-state-for-navigation-and-persistence.md) — superseded by ADR-012
- [ADR-004: LinkedIn data export ingestion instead of direct API access](ADR-004-linkedin-data-export-ingestion-instead-of-direct-api-access.md) — superseded by ADR-007
- [ADR-005: Streamlit-first, backend-ready delivery strategy](ADR-005-streamlit-first-backend-ready-delivery.md) — superseded by ADR-012
- [ADR-006: Playwright-first PDF export with ReportLab fallback](ADR-006-playwright-first-pdf-export.md) — superseded by ADR-015
- [ADR-008: Two-mode grounded assistant panel](ADR-008-two-mode-grounded-assistant-panel.md) — superseded by ADR-011

## Current state note

As of 2026-05-16, the shipped product is a Next.js workspace deployed on Vercel backed by a FastAPI container on a Frankfurt VPS, with a Supabase EU project for Auth + persistence + the cached-jobs index. The agentic workflow runs Tailoring → Review → ResumeGen → CoverLetter on every analysis, with per-agent retry + fallback isolation. Tier enforcement is live across eight counters (Free / Pro / Business) with the Lemon Squeezy payment scaffold env-gated behind a "Coming soon" frontend fallback until the dashboard's final variant IDs land. The observability stack (Sentry `jobagent-backend` + `jobagent-frontend` + a shared PostHog free-tier project tagged with `product: "jobagent"`) is wired with a custom EU cookie consent banner gating PostHog + Sentry Session Replay behind explicit user opt-in. `backend/nightly_eval.py` exists and is tested but is **not** on the production cron at pre-revenue stage — re-enabling is a single crontab edit when revenue justifies the recurring LLM spend.

## Adding a new ADR

1. Pick the next `ADR-NNN` number sequentially.
2. Use the existing format: Date, Status, Context, Decision, Consequences (Positive / Negative / Neutral), Alternatives considered, References.
3. **Never edit an existing ADR's Decision section after acceptance.** If the decision changes, write a new ADR that supersedes it and update the old one's status note to point at the successor — leave the body intact as historical record.
4. Add the new ADR to the right thematic cluster above in the same commit, and update the "Current state note" if the new decision changes the production picture.
