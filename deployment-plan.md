# Deployment Plan

Next steps for taking the AI Job Application Agent from development to a live hosted environment.  
Based on the Day 23 re-assessment (March 14, 2026).

---

## Architectural Verdict

**No architectural changes needed.** The layered design (parsers → services → agents → orchestrator → builders → exporters) is sound. The Streamlit-first strategy is correct for a first deployment. FastAPI extraction (ROADMAP Phase 9) remains correctly deferred until a second client or async execution is justified.

---

## Pre-Deployment Blockers

These are required for a real hosted environment and are not covered by the 12 code-quality suggestions in `improvements.md`.

### 1. Add deployment configuration

`.streamlit/config.toml` is now present. Remaining work is just to confirm the target host uses `app.py` as the Streamlit entrypoint.

- Confirm `app.py` is the entrypoint the target platform expects.

### 2. Secrets management

`.env.example` and `README.md` now distinguish between:

- no-secret minimal deployment
- optional OpenAI-assisted deployment
- later Supabase-backed authenticated deployment

On Streamlit Cloud these values go into the Secrets panel; on other hosts (Render, Railway) they go into environment config. `os.getenv` in `config.py` works on all platforms.

### 3. Supabase production setup

Phase 6 notes: "Supabase project bootstrap remains operator setup work." This is still deferred until you create the real project. Before the authenticated launch:

- Create a production Supabase project.
- Apply the SQL schemas from `docs/`.
- Configure Google OAuth with the production redirect URL.
- Verify Row Level Security (RLS) policies.

Concrete operator steps are captured in [docs/supabase-setup-checklist.md](docs/supabase-setup-checklist.md).

Until then, the app can still be deployed in a pre-auth state. For that phase, keep `AUTH_REQUIRED_FOR_ASSISTED_WORKFLOW=false` if you want assisted features reachable without login.

### 4. Keep the WeasyPrint runtime ready for deployment

The chosen first deployment target is **Streamlit Community Cloud**, and the PDF path should stay **WeasyPrint-first** with the required native runtime present on the host.

- Ensure the deployment runtime includes the native GTK/Pango libraries WeasyPrint needs.
- Treat ReportLab as the automatic runtime fallback if the WeasyPrint backend is unavailable.
- Verify PDF export during hosted smoke testing with the same HTML/CSS templates used locally.

Decision taken: use **Streamlit Community Cloud** for the first deploy and keep the current **WeasyPrint-first** PDF path. ReportLab remains the resilience fallback, not the intended primary renderer.

### 5. Error handling for missing OpenAI key

Verify that if someone hits the assisted workflow without a valid API key configured, the UI shows a clean user-facing error instead of a stack trace.

---

## Suggestions to Address Before Deployment

From the 12 improvement items in `improvements.md`, the deployment-safety cleanup items below are now done:

| # | Item | Why | Effort |
|---|---|---|---|
| 6 | Fix `datetime.utcnow()` deprecation | Avoids warnings on Python 3.12+ runtimes | Done |
| 7 | Remove dead code and consolidate near-duplicates | Clean ship, no unused code in production | Done |
| 12 | Comment the `hashlib.md5` monkey-patch | If ReportLab version differs on the deployment host, the comment saves debugging time | Done |

---

## Suggestions to Address After First Deploy

The remaining items are quality-of-life improvements that do not affect deployment:

| # | Item | Category |
|---|---|---|
| 9 | Add server-side aggregation for daily usage | Performance at scale |
| 11 | Add token budget awareness to prompts | Edge case for very large inputs |

OpenAI retry hardening is now in place in the Responses API wrapper for:

- unsupported `temperature` handling on GPT-5 routed models
- incomplete responses caused by exhausted `max_output_tokens`
- longer client timeouts with SDK retries for transient network reads

---

## What Does Not Need to Change

- **No FastAPI extraction.** Single-client Streamlit does not need a separate backend.
- **No database migration.** Supabase + the existing store layer is sufficient.
- **No agent redesign.** The 7-agent supervised workflow with review loop is production-quality.
- **No state management rewrite.** The centralized `state.py` pattern is correct for Streamlit.

---

## Suggested Deployment Sequence

| Step | What | Effort |
|---|---|---|
| 1 | Fix suggestions #6, #7, #12 | Done |
| 2 | Add `.streamlit/config.toml` with server and theme config | Done |
| 3 | Decide deployment platform (Streamlit Cloud vs Docker host) | Done: Streamlit Cloud |
| 4 | Handle WeasyPrint runtime: keep GTK/Pango available and retain ReportLab as runtime fallback | Done for first deploy |
| 5 | Create production Supabase later, then apply schemas, OAuth, and RLS | ~1–2 hours |
| 6 | Deploy and smoke-test the pre-auth shell first, then the authenticated flows after Supabase exists | Testing |
| 7 | Tackle remaining suggestions (#9–#11) later | Iterative |
