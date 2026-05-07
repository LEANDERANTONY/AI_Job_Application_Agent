# Punch List - Continuation Notes

This file is the durable hand-off for resuming work after a chat session
compacts or ends. **Read this first**, then ask the user which item to
pick up.

The branch is `frontend-redesign`, worktree
`.claude/worktrees/trusting-jones-afaa7e`. All recent commits live there.

---

## ACTIVE WORK: DOCX export + resume builder download

**Six-phase plan agreed with the user. Tackle one per commit, in order.**

Decisions locked in (don't relitigate):
- **Markdown is being REMOVED entirely.** Not hidden — removed from UI,
  routes, and types. Code paths get deleted.
- **Per-phase commits.** Each phase below gets its own commit so the
  user can review / revert independently.
- **Visual fidelity is high priority.** DOCX needs to look right in
  Microsoft Word AND Google Docs. LibreOffice nice-to-have but not
  blocking. Manual visual QA expected after each theme lands.
- **Resume builder is NOT a separate surface.** Stays inside the
  workspace; download buttons appear after "Generate base resume."
- **Two themes for the resume-builder download:** `classic_ats` and
  `professional_neutral`. Same as the tailored-resume export.
- **Auth gating:** same as the resume builder LLM — login required.

### Phase 1 — DOCX exporter foundation (start here)
- Add `python-docx` to `pyproject.toml`
- Implement `export_docx_bytes(artifact)` in `src/exporters.py` for
  `classic_ats` only (Phase 4 adds the second theme)
- Mirror the existing `_build_structured_resume_body_classic` /
  `_build_cover_letter_html` structural decomposition: pull header,
  summary, skills, experience, projects, education, publications,
  certifications from the structured `TailoredResumeArtifact` /
  `CoverLetterArtifact` fields (NOT from the markdown — markdown is
  going away).
- Honor `artifact.section_order` (the per-profile ordering helper
  already wired through resume_builder).
- Unit tests: render a fixture artifact, parse the resulting bytes
  with python-docx, assert structural shape (heading count, bullet
  count, etc.). Don't try to assert on visual output — that's manual.
- ~half day. ~300 LOC plus tests.

### Phase 2 — Wire DOCX through artifact export
- `backend/workspace_models.py`:
  `WorkspaceArtifactExportRequestModel.export_format`: replace
  `Literal["markdown", "pdf"]` with `Literal["pdf", "docx"]`. Markdown
  goes away.
- `backend/services/artifact_export_service.py`: dispatch on the new
  format. Drop the markdown branch entirely.
- `frontend/src/lib/api-types.ts`: update the `ExportFormat` type +
  `WorkspaceArtifactExportRequest` shape.
- ~1-2 hr.

### Phase 3 — Frontend: replace Markdown with DOCX everywhere
- Tailored-resume artifact viewer: remove "Download Markdown" button,
  add "Download DOCX." Theme picker stays.
- Cover-letter artifact viewer: same.
- Any `useArtifactExport` hook plumbing that referenced markdown:
  remove.
- Search the whole frontend for any `"markdown"` literal in artifact
  context and remove. Also remove any test fixtures that mock
  markdown export.
- ~2 hr.

### Phase 4 — `professional_neutral` DOCX theme
- Mirror the existing `_RESUME_THEME_PALETTES["professional_neutral"]`
  (pure black / white, Georgia body, no warm-brown accents) into the
  DOCX renderer.
- Manual QA: open both themes in Word + Google Docs, screenshot. Diff
  against the PDF rendering of the same theme — they should READ as
  the same document, not necessarily pixel-match.
- ~half day (mostly the QA loop).

### Phase 5 — Resume builder export endpoint
- New route: `POST /workspace/resume-builder/export`
  - Body: `{ session_id, export_format: "pdf" | "docx", theme:
    "classic_ats" | "professional_neutral" }`
  - Auth-gated like the other resume-builder routes
- Service layer: synthesize a `TailoredResumeArtifact` from the
  resume_builder session's draft profile (no JD, empty
  `target_role`, empty `change_log`, empty `validation_notes`,
  `section_order` from `compute_section_order(candidate_profile)`).
  Reuse `export_pdf_bytes` / `export_docx_bytes`.
- Tests: integration test that goes through start -> message ->
  generate -> export round-trip and asserts the response is bytes.
- ~half day.

### Phase 6 — Resume builder UI: download buttons
- After "Generate base resume" produces the markdown preview, render
  a download row:
  - Theme picker: Classic ATS / Professional Neutral (radio)
  - Format buttons: Download PDF / Download DOCX
- Copy: a small line above the buttons making it clear this is the
  exit point — "Download your resume now, or continue to tailor it
  for a specific role below."
- ~2 hr.

**Total estimate: 2.5-3 days of focused work.**

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
  `saved_jobs`, `resume_builder_sessions`. The Streamlit-era
  `workflow_runs` and `artifacts` tables were dropped.
- `pg_cron` jobs running:
  - `cleanup-expired-saved-workspaces` (every 5 min, 24h TTL)
  - `cleanup-expired-resume-builder-sessions` (every 5 min, 7d TTL)
- RLS on both tables filters out expired rows.

### Vercel MCP — limited access
The Vercel MCP token doesn't have access to the user's account
(`leanderantonys-projects` team). `list_teams` returns `[]`,
`get_project` returns 403. Don't waste time on it. The codebase +
`.env.example` + `frontend/README.md` are the source of truth.

### Pre-existing flake — was fixed
The `test_resume_builder_session_can_progress_to_review` flake was
fixed as part of the resume-builder LLM commit (`84f67db`). Full
suite should be 211/211 green. If it fails, that's a real new
regression — investigate.

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

## How to start a fresh chat for the DOCX work

Paste roughly this:

> Continuing the AI_Job_Application_Agent project on branch
> `frontend-redesign` in worktree
> `.claude/worktrees/trusting-jones-afaa7e`. Read
> `docs/PUNCHLIST.md` first — it has the durable hand-off context
> and the active 6-phase DOCX export plan. Then start on **Phase 1
> (DOCX exporter foundation)** and ask me to verify after each
> phase commit.

The new session should:
1. Read this file
2. Skim the most recent commits (`git log --oneline -10`) to know
   what's already in place
3. Open `src/exporters.py` to see the existing render structure
   (PDF + markdown). The DOCX exporter mirrors the PDF render's
   structural decomposition.
4. Open `src/schemas.py` `TailoredResumeArtifact` and
   `CoverLetterArtifact` to know the structured fields available.
5. Start Phase 1.
