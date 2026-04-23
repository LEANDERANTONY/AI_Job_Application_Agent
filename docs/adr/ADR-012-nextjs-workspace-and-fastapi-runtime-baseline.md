# ADR-012: Next.js Workspace And FastAPI Runtime Baseline

- Status: Accepted
- Date: 2026-04-24

## Context

The product outgrew the old Streamlit runtime.

We needed:

- a cleaner hosted frontend for the user workspace
- a separate backend runtime on the VPS
- explicit API boundaries for auth, job search, JD review, workflow runs, exports, and persistence
- a UI that matches the real product flow instead of the earlier prototype shell

The active product also narrowed around the clearest user value:

- tailored resume
- cover letter
- grounded assistant help

The earlier visible strategy/report-heavy surface and multi-theme resume presentation were adding complexity without enough user value.

## Decision

We standardize the live product on:

- `Next.js` for the user-facing workspace in `frontend/`
- `FastAPI` for the backend API in `backend/`
- shared Python workflow logic in `src/`
- `Supabase` for Google auth, quotas, saved jobs, and the latest saved workspace snapshot
- one standard ATS-friendly resume output format
- a visible workspace centered on resume and cover letter

The internal report builder may remain available in Python for backend or support use, but it is no longer a first-class visible workspace output.

The old Streamlit shell is removed from the active runtime path.

## Consequences

### Positive

- The frontend is now easier to host, iterate on, and polish.
- The backend boundary is explicit and easier to harden.
- The product story is clearer for users.
- Auth, persistence, search, and workflow execution now live behind stable API contracts.
- Resume export is simpler because there is one supported format instead of a theme switch.

### Negative

- The migration removes the old Streamlit simplicity for local single-process iteration.
- Long agentic runs still need further work to become proper background jobs.
- Historical ADRs and docs need active maintenance so they do not drift toward the removed Streamlit architecture again.

## Follow-Up

- Keep the README, architecture doc, and transition doc aligned with the live Next.js + FastAPI product.
- Move long workflow runs to background execution when operationally justified.
- Continue simplifying the workspace language so it stays user-facing rather than implementation-facing.
