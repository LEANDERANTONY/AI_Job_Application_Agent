# Punch List - Continuation Notes

This file is the durable hand-off for resuming work after a chat session
compacts or ends. **Read this first**, then ask the user which item to
pick up.

The branch is `frontend-redesign`, worktree
`.claude/worktrees/trusting-jones-afaa7e`. All recent commits live there.

> **Status as of 2026-05-08.** The DOCX export + resume builder
> download work has shipped (commits `6db8d6f` → `6cb4f65`, all six
> phases). The cached-jobs cache layer + multi-ATS coverage + dropdown
> filters work has also shipped (commits `0fa1e67` → `6e36c8f`, Phases
> 2–8). See `DEVLOG.md` Days 39 + 40 for the per-day breakdown and the
> ADR set (013–016) for the load-bearing decisions. There is no active
> punch-list item right now — pick the next thing from the
> follow-ups list below or wait for product input.

---

## DONE: DOCX export + resume builder download (Phases 1–6)

The six-phase DOCX plan is fully shipped. Commits in order:

```
6db8d6f Phase 1: DOCX exporter foundation (classic_ats theme)
7da724f Phase 2: wire DOCX through artifact export, drop markdown export path
0513721 Phase 3: frontend cleanup sweep — markdown export removed
0f92179 Phase 4: professional_neutral DOCX theme + palette resolver
f13912f Phase 5: resume builder export endpoint
6cb4f65 Phase 6: resume builder download row UI (Theme + PDF/DOCX buttons)
```

Markdown export was removed entirely — UI, routes, types, fixtures.
Both themes (`classic_ats`, `professional_neutral`) now render through
a shared palette resolver across PDF and DOCX. Decision recorded in
[ADR-015](adr/ADR-015-docx-first-artifact-export-with-theme-palette.md).

## DONE: Cached-jobs cache layer + multi-ATS + dropdown filters (Phases 2–8)

The job-search rebuild is fully shipped. Commits in order:

```
0fa1e67 Phase 2: cached_jobs refresh worker + /admin/refresh-cache
611aa02 Phase 3: cut /jobs/search to query cached_jobs (live= escape hatch)
51a5f40 Phase 4: bump source pool to ~117 Greenhouse + 30 Lever
8f22be9 Phase 5: pg_net + cron schedule + frontend Expired badge
2604891 Phase 5b: relevance-ranked cache search via Postgres RPC
b8f380c Phase 6: bigger Greenhouse list (79) + Ashby adapter (36 boards)
a0e0a20 Phase 7: Workday adapter (11 Fortune 500 tenants) + status fix
9055867 Phase 8 backend: work_mode + employment_type filters + sort_by
807c556 Phase 8 frontend: dropdown filters + sort for job search
6e36c8f Filter popover: dismiss on click-outside + Escape
```

Live cache size after Day 40: ~11,877 active jobs across four ATS
providers. Search latency 360ms warm / 5.5s cold via the
`search_cached_jobs_ranked` RPC, vs 25s for the live fan-out path
that's still available behind `?live=true`. Decisions recorded in
[ADR-013](adr/ADR-013-cached-jobs-cache-layer-with-scheduled-refresh.md)
and
[ADR-014](adr/ADR-014-postgres-rpc-for-ranked-search.md).

---

## Follow-up ideas not yet picked up

Track these here so they don't fall on the floor — none are in active
flight. The next chat should ask the user which (if any) to start.

- **URL / query-param persistence for filters.** A sorted-and-filtered
  job-search view should survive a refresh and a shared link. Probably
  ~half day of work on top of the existing dropdown state.
- **Reset filters affordance.** A small × on the search row that
  clears all five facets at once. Trivial.
- **Visual smoke test on narrow / mobile viewports.** The chip row uses
  `flex-wrap: wrap` so it should degrade gracefully, but the popover
  positioning hasn't been physically tested at <540px. Quick QA pass.
- **Per-provider freshness lag dashboard.** `cached_jobs.scraped_at` /
  `last_seen_at` distribution is the obvious metric; useful once we
  have user volume to justify it.
- **Workday IP rate-limit hardening.** Production cadence (one refresh
  / 30 min) is well below the threshold but a flap during a deploy
  loop could trip it. Per-tenant rate budgets if cache volume grows
  past current ~12k rows.

---

## DONE since the previous PUNCHLIST baseline

The original 14-item punch list is largely complete. Recent commits on
`frontend-redesign` (most recent first):

```
333dff2 Cross-origin redirect when signed-out user hits the workspace
428faab Redirect signed-out users away from /workspace to landing
dc7c8b0 Resume-builder drafts get a 7-day TTL with active-user refresh
6dc4cf8 Surface resume-builder persistence outcome to the user
3604585 Revert "Fix workspace chat bubbles..." (transcript style retained)
291e422 Fix workspace chat bubbles (experiment, reverted)
e2e3d4e Add docs/PUNCHLIST.md as durable handoff for chat continuation
84f67db Punch list 1-14 + conversational LLM resume builder + frontend chat UI
efba3ff CoverLetterAgent battle-test
bd78156 ResumeGenerationAgent battle-test + section-order fixes
f4ce384 Per-profile resume section ordering
c9ac9e0 ReviewAgent battle-test
84c1698 TailoringAgent battle-test
dfedd0f Remove FitAgent + report builder + bundle endpoint
```

Major milestones since the original PUNCHLIST:
- All 14 punch-list items shipped (DB migrations, lazy-load,
  thread bound, all three battle tests, adversarial coverage,
  signature hash, dead-code cleanup)
- Conversational LLM resume builder shipped + verified end-to-end
  in Brave (5/8 fields extracted in one turn, backtracking works,
  100% completion + Generate base resume produces clean markdown)
- Persistence indicator: tri-state (saved / skipped / unauthenticated)
  surfaced in the field-completeness rail
- 7-day TTL on resume_builder_sessions with active-user refresh +
  "refreshes through Mon Nov 11" hint in UI; mirrors saved_workspaces
  TTL pattern; cron + RLS expires-at filter both wired
- Workspace auth gate: signed-out users at `/workspace` get bounced
  to the landing page. Cross-origin handled via `app.X` -> `X` host
  stripping (mirrors the existing middleware convention; no new env
  var). Localhost stays same-origin via the no-prefix path.

Open metric work that didn't get a separate punch-list commit:
- `summary_groundedness` metric calibration on minimal-profile cover
  letters (LLM 0.85 case `minimal_info`). Inspected and accepted —
  prose connector words flagged but every substantive claim is
  grounded. Not a real fabrication; just metric noise.

---

## Project facts a fresh session needs

### Deployment shape
- Single Docker container on a VPS (`deploy/vps/docker-compose.yml`).
- ONE uvicorn worker. Not multi-worker. There is no race condition
  in the in-memory `_SESSIONS` / `_JOBS` dicts.
- Caddy fronts the API at `:443/:80`. The Caddyfile sets
  `flush_interval -1` so SSE streaming works.
- Frontend is on Vercel (Next.js, separate runtime). One Vercel
  project (`job-application-copilot`) serves BOTH the landing
  (`job-application-copilot.xyz`) and the workspace
  (`app.job-application-copilot.xyz`) via the host-based middleware
  in `frontend/src/middleware.ts`:
    - app subdomain `/`: rewrite to `/workspace` content (clean URL)
    - app subdomain `/workspace`: redirect to `/` (clean URL)
- Supabase is the auth + persistence backend (project id
  `ubjneczlcmwmhejenuid`).

### Local dev
- `.env` is at the repo root (auto-loaded by `src/config.py`).
  `OPENAI_API_KEY` is configured.
- `frontend/.env.local` mirrors `.env.example` (use
  `http://localhost:3000` for `NEXT_PUBLIC_SITE_URL`).
- `NEXT_PUBLIC_SITE_URL` is the WORKSPACE URL, not the landing URL.
  In production it's `https://app.job-application-copilot.xyz`.
- Pytest run command (Windows):
  ```
  "C:/Users/Leander Antony A/Documents/Projects/AI_Job_Application_Agent/.venv/Scripts/python.exe" -m pytest <path> -q
  ```

### Supabase
- MCP is connected. Project id: `ubjneczlcmwmhejenuid`.
- Live DB tables: `app_users`, `usage_events`, `saved_workspaces`,
  `saved_jobs`, `resume_builder_sessions`, `cached_jobs`. The
  Streamlit-era `workflow_runs` and `artifacts` tables were dropped.
- `pg_cron` jobs running:
  - `cleanup-expired-saved-workspaces` (every 5 min, 24h TTL)
  - `cleanup-expired-resume-builder-sessions` (every 5 min, 7d TTL)
  - `refresh-cached-jobs` (every ~30 min via `pg_net.http_post` to
    `/admin/refresh-cache`; bearer-protected by
    `REFRESH_CACHE_SECRET`; setup script in
    `docs/job_cache_cron_setup.sql`)
- RLS on per-user tables filters out expired rows. `cached_jobs`
  is global / non-user-scoped — RLS enabled with no policies as
  defence-in-depth, all reads/writes go through the service-role
  key.

### Vercel MCP — limited access
The Vercel MCP token doesn't have access to the user's account
(`leanderantonys-projects` team). `list_teams` returns `[]`,
`get_project` returns 403. Don't waste time on it. The codebase +
`.env.example` + `frontend/README.md` are the source of truth.

### Pre-existing flake — was fixed
The `test_resume_builder_session_can_progress_to_review` flake was
fixed as part of the resume-builder LLM commit (`84f67db`). Full
suite is currently 322/322 green (after Phase 8 added
cached-jobs / RPC / dropdown-filter coverage). If it fails, that's
a real new regression — investigate.

### Quality runner pattern
All Tier-2/Tier-3 runners live in `tests/quality/` and follow the
same pattern:
- 6-13 fixture pairs in `tests/quality/sample_resumes/` and
  `tests/quality/sample_jds/`
- deterministic + llm_only modes scored side-by-side
- weighted dimensions; weights vary by failure-mode severity
- `--include-llm` flag (costs ~$0.05-$0.10 per run)
- `--json out.json` dumps the full scorecard
- output JSONs match `tests/quality/_last_*.json` and are gitignored

Existing runners:
- `parser_quality_runner.py` (resume parser)
- `jd_parser_quality_runner.py` (JD parser)
- `renderer_fidelity_runner.py` (HTML/PDF render)
- `skill_canonicalization_runner.py` (skill aliasing)
- `tailoring_quality_runner.py`
- `review_quality_runner.py`
- `resume_generation_quality_runner.py`
- `cover_letter_quality_runner.py`
- `resume_builder_quality_runner.py`
- `assistant_quality_runner.py`
- `orchestrator_e2e_runner.py`

---

## Investigations completed (no action needed)

- `saved_workspaces.rows = 0`: explained by 24h TTL +
  `cleanup-expired-saved-workspaces` cron running every 5 min.
  Save flow is wired automatically via `onAnalysisCompleted()` ->
  `persistLatestWorkspace()`. Not a bug.
- "In-memory state on stateless backend" critique: wrong - VPS
  runs one uvicorn worker, no race. Container restart is the
  realistic risk and it's covered (resume builder lazy-loads,
  workspace run jobs surface a friendly error).
- "No request timeout for LLM": wrong - `OpenAIService` constructs
  the SDK client with `timeout=120.0, max_retries=2`.
- Chat-bubble vs transcript style for resume builder: experiment
  shipped + reverted. Transcript style is the chosen direction.

---

## How to start a fresh chat

Paste roughly this:

> Continuing the AI_Job_Application_Agent project on branch
> `frontend-redesign` in worktree
> `.claude/worktrees/trusting-jones-afaa7e`. Read
> `docs/PUNCHLIST.md` first — it has the durable hand-off context.
> The big shipped pieces are in DEVLOG Days 37–40 and ADRs 013–016.
> There's no active punch-list item right now; pick from the
> "Follow-up ideas not yet picked up" list near the top of the
> punchlist or wait for me to point you at something.

The new session should:
1. Read this file
2. Skim the most recent commits (`git log --oneline -10`) to know
   what's already in place
3. Skim DEVLOG Days 37–40 for the most recent shipped work
4. Skim ADR-013 → ADR-016 for the load-bearing decisions on the
   cached-jobs cache layer, the search RPC, the DOCX export
   pipeline, and the conversational resume builder
5. Ask the user which follow-up to pick (or wait for instructions)
