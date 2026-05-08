# Workspace Design System — Direction B "Workbench" (shipped)

Direction B is the dark deep-space variant with hairline section dividers and an emissive blue accent. It shipped in production in 2026-04 and has continued evolving since.

This package is now a **design-system reference** rather than a redesign hand-off. Use it as input context for future workspace expansion (new tabs, new surfaces) or as a starting point for redesigning a sibling product against the same visual language.

> **Source of truth:** the shipped CSS lives in `frontend/src/app/globals.css` (scoped under `.b-shell`) and the React components live in `frontend/src/components/workspace/`. When this doc and the shipped code disagree, the shipped code wins. The token table below is mirrored from the live values.

---

## 1 · What's in this folder

```
handoff/
├── README.md                ← you are here
├── prototype/
│   ├── index.html           ← run to see the original three-direction explorer
│   ├── tokens.css           ← original design tokens (with shipped values added)
│   ├── direction-b.css      ← original Direction B prototype styles
│   ├── direction-b.jsx      ← original Direction B JSX (split by tab)
│   ├── shared.jsx           ← atoms reused across the prototype
│   ├── mock-data.jsx        ← sample data
│   ├── tweaks-panel.jsx     ← A/B/C toggle + density + accent + type-system controls
│   └── job-copilot-logo.png ← brand mark used in topbar
└── specs/
    ├── chrome.md            ← topbar, step rail, hero, command palette, FAB, mobile
    ├── 01-resume.md         ← step 1: Resume intake + parsed profile + conversational builder
    ├── 02-jobs.md           ← step 2: Job search + filters + sort + saved drawer
    ├── 03-jd.md             ← step 3: JD intake + parsed JD
    └── 04-analysis.md       ← step 4: Analysis run + artifact viewer + DOCX/PDF export
```

The original prototype HTML still works for a quick A/B/C compare. **Production only ships Direction B**; the other two directions are kept inside the prototype as historical reference.

---

## 2 · Mapping to shipped components

The redesign mapped 1:1 onto `frontend/src/components/workspace/`. The full shipped tree is:

```
frontend/src/components/workspace/
├── WorkspaceShell.tsx       — top-level layout, topbar, step rail, hero, tab switching
├── Sidebar.tsx              — kept for future multi-workspace use, not mounted in main flow
├── ResumeIntake.tsx         — Upload / Build with assistant
├── JobSearch.tsx            — search + filter dropdowns + saved-jobs drawer + URL import
├── JDReview.tsx             — paste / URL / file intake + parsed JD
├── AnalysisRunner.tsx       — Run analysis CTA + progress timeline
├── ArtifactViewer.tsx       — tabs (Resume / Cover Letter) + DOCX + PDF + theme picker
├── AssistantPanel.tsx       — chat with SSE streaming, mounted inside the floating FAB
├── CommandPalette.tsx       — ⌘K palette overlay
├── CollapsibleSection.tsx   — reusable `<details>`-backed section wrapper
└── icons.tsx                — shared inline SVG icons

frontend/src/hooks/
├── useWorkspaceSession.ts   — auth restore, saved-snapshot bootstrap
├── useAnalysisJob.ts        — POST /workspace/analyze-jobs + polling state machine
├── useAssistantHistory.ts   — localStorage-backed chat history
├── useSavedJobs.ts          — GET/POST/DELETE /workspace/saved-jobs
└── useArtifactExport.ts     — POST /workspace/artifacts/export with toast feedback
```

State management ended up using a per-feature hook + lifted-callback pattern from `WorkspaceShell.tsx` rather than the Zustand store option discussed in the original handoff. There's no `state/workspace-store.ts` in the shipped tree.

**Surfaces added during the build:**

- **⌘K command palette** (`CommandPalette.tsx`) — opens on `Cmd/Ctrl+K` or by clicking the topbar pill; jump-to-step + saved jobs + recent assistant turns + actions.
- **Floating assistant FAB** — wraps `AssistantPanel` in a portal-mounted bottom-right shell.
- **Per-step lock-reason tooltips** — the rail surfaces an honest reason why a step is locked (e.g. `Upload a resume to unlock`).
- **Filter popover dropdowns** in Job Search — built on native `<details>`/`<summary>` with click-outside + Escape dismiss.
- **Account popover** in the topbar — sign-out, plan tier, daily quota usage strip, saved-workspace TTL hint.

---

## 3 · Behavior preservation checklist

These are the existing behaviors the redesign promised to preserve — all shipped:

### Step 1 — Resume

- [x] Drag-and-drop file → `uploadResumeFile` → parsed profile populates hero.
- [x] "Build with assistant" toggle → `startResumeBuilderSession` → conversational chat.
- [x] Generated resume preview → `commitResumeBuilderResume`.
- [x] Edit-in-place fields on parsed profile → `updateResumeBuilderDraft`.
- [x] Last-upload metadata pulled from `loadLatestResumeBuilderSession`.
- [x] All error/notice states show in the canvas-level Notice slot.
- [x] Resume builder downloads (PDF + DOCX, two themes) directly from the chat surface — see `04-analysis.md` for the export contract.
- [x] 7-day TTL on resume-builder drafts with active-user refresh; tri-state persistence indicator (saved / skipped / unauthenticated) in the field-completeness rail.

### Step 2 — Job Search

- [x] `searchJobs(...)` runs on submit; loading state shows.
- [x] Filter **dropdowns** (Source / Work mode / Type / Posted within / Sort) drive the cached-jobs RPC — see `02-jobs.md` for the param contract. The original "filter chips" idea was replaced with multi-select popovers because chips can't express the five-facet × multi-select × single-select sort combination cleanly.
- [x] Saved jobs persist via `useSavedJobs` (server-synced).
- [x] Selected job highlights and drives Step 3.
- [x] "Resolve URL" path via `resolveJobUrl` — shipped as a separate small import form on the search row, not as an inline pill below the search.
- [x] Cached-jobs cache layer: `?live=true` falls back to live fan-out for diagnostics.
- [x] "Expired" badge on cards whose upstream listing was tombstoned by the cleanup pass — keeps saved bookmarks visible without misrepresenting application status.

### Step 3 — JD Review

- [x] Paste mode: textarea → `[Parse JD]` → fills hero + sections.
- [x] URL mode: `resolveJobUrl` → fills the same.
- [x] File upload: `uploadJobDescriptionFile`.
- [x] If a job is selected in Step 2, the JD prefills with that posting.
- [x] Hard/soft skill chips render parser output verbatim — no reorder, no dedupe.

### Step 4 — Analysis + Artifacts

- [x] "Run analysis" → `useAnalysisJob` polls until `WorkspaceAnalysisResponse` resolves.
- [x] Progress timeline shows the actual job phases reported by the hook.
- [x] Streaming uses the SSE endpoint `POST /workspace/assistant/answer/stream` with `meta` → `delta` × N → `followups` → `done` event contract; `streamWorkspaceAssistantAnswer` in `lib/api.ts` consumes it via `fetch` + `ReadableStream`.
- [x] Artifact tabs (Tailored Resume + Cover Letter) — both render through the same structured-artifact pipeline.
- [x] Download buttons → `useArtifactExport` for **PDF + DOCX** (two themes: `classic_ats`, `professional_neutral`). Markdown export was removed in 2026-05; see `04-analysis.md` and project ADR-015.

### Chrome

- [x] Step rail navigation respects `WorkspaceMainTab` state machine; lock-reason tooltips per step.
- [x] ⌘K opens palette; results include jump-to-step, saved jobs, recent assistant turns, "Run analysis" action when prerequisites are met.
- [x] FAB opens `AssistantPanel`; closing the FAB does not lose chat history (`useAssistantHistory` persists).
- [x] Daily quota indicator + plan tier + saved-workspace meta surface in the topbar's account popover.
- [x] Single 540px-breakpoint mobile responsive pass covering topbar, hero, rail, regions, popover, intake mode toggle, and the search filter row.

---

## 4 · Design tokens (shipped values)

All workspace tokens are scoped under `.b-shell` in `frontend/src/app/globals.css` so they don't leak into landing-page styles. The landing page has its own (older) token block at the top of the same file under `:root`.

The original handoff used `:root` + `data-direction="b"` to A/B the directions; in production we shipped only Direction B and chose the simpler `.b-shell`-scoped approach. There is no `data-direction` attribute on the production page.

| Group | Token | Shipped value | Used for |
|---|---|---|---|
| Surface | `--bg-page` | `#04070f` | App background (radial gradient layered over) |
| | `--bg-card` | `rgba(10, 14, 22, 0.72)` | All cards, modals, panels |
| | `--bg-card-2` | `rgba(20, 26, 40, 0.70)` | Inset surfaces, hover states |
| | `--bg-input` | `rgba(10, 14, 22, 0.85)` | Form inputs |
| | `--bg-chip` | `rgba(255, 255, 255, 0.04)` | Subtle chip background |
| Borders | `--border` | `rgba(160, 178, 218, 0.12)` | Card + input borders |
| | `--border-strong` | `rgba(160, 178, 218, 0.20)` | Hover/focus borders |
| | `--hairline` | `rgba(160, 178, 218, 0.07)` | Section dividers |
| Ink | `--fg` | `#f5f8ff` | Body text |
| | `--fg-2` | `#c7cfdf` | Secondary text |
| | `--fg-3` | `#8a93a8` | Captions, eyebrows, metadata |
| | `--fg-4` | `#5e6677` | Placeholder, disabled |
| Accent | `--accent` | `#4171ff` | Primary CTA, active tab pill |
| | `--accent-strong` | `#5a86ff` | Primary hover |
| | `--accent-soft` | `rgba(48, 100, 255, 0.10)` | Active tab background tint |
| | `--accent-fg` | `#ffffff` | Text on accent surface |
| | `--accent-tint` | `rgba(48, 100, 255, 0.14)` | Soft accent backgrounds |
| | `--accent-glow` | `rgba(48, 100, 255, 0.45)` | Rail progress connector, hero hairline glow |
| Status | `--success` | `#7fe0b0` / `--success-soft` | Live / ready indicators |
| | `--warning` | `#ffcb94` / `--warning-soft` | Soft warning states |
| | `--danger` | `#ff8b8b` / `--danger-soft` | Errors, destructive buttons |
| Radius | `--radius-sm / --radius / --radius-lg / --radius-xl` | `6 / 10 / 14 / 20px` | Chips / inputs / cards / hero |
| Motion | `--ease-out` | `cubic-bezier(0.16, 1, 0.30, 1)` | Standard transitions (Linear-style) |
| | `--ease-spring` | `cubic-bezier(0.34, 1.56, 0.64, 1)` | Celebratory transitions (palette flips) |
| | `--duration-fast / --duration-base` | `150ms / 240ms` | Micro vs macro motion |

**Type stack** (different from the original handoff's "Geist" claim — production matches the landing page so workspace + marketing share one voice):

| Token | Family | Used for |
|---|---|---|
| `--font-display` | Space Grotesk | Hero titles, section headings |
| `--font-body` | DM Sans | Body copy, buttons, chips |
| `--font-mono` | Geist Mono | Eyebrows (tracked +0.04em), step numbers, kbd shortcuts, timestamps |

The body uses `font-size: 15.5px` (bumped from the prototype's 14px so the dense workspace reads comfortably on standard 1080p+ displays without redoing every per-element size).

---

## 5 · Visual rhythm rules

These are the conventions the shipped workspace consistently follows. New surfaces should match.

- **Eyebrow before every region:** mono `STEP NN · SECTION NAME`, `--fg-3`, `letter-spacing: 0.04em`, `font-size: 11px`, `font-weight: 500`. Exception: the topbar and FAB don't use eyebrows.
- **Hairline-first section dividers:** prefer `1px var(--hairline)` lines over heavy borders. Cards still get `--border`, but inside a card use hairlines for sub-sections.
- **Accent is rare:** `--accent` is only used for the active state of one thing on screen (active tab in the step rail, primary submit, current chat-stream caret). Multiple accent things at once dilutes the affordance.
- **Status uses pips, not badges:** small dot + label, `font-size: 12px`, `--fg-2` text. The dot color encodes the state (live = success, ready = accent, warn = warning).
- **Motion under 250ms:** entrance animations and hover transitions all sit under `--duration-base` (240ms). Anything longer feels laggy in a tool.
- **Mobile collapses to a single column at 540px.** No two-up grids survive below that breakpoint; the chip row uses `flex-wrap: wrap`.

---

## 6 · Decisions resolved since the original handoff

The original "Open questions" section is closed:

- **Sidebar fate.** No sidebar in the four-step flow. Multi-workspace switching, if/when it lands, will go in the topbar account popover.
- **Saved jobs surface.** Lives as a collapsible drawer above the results grid in Step 2 (not a right rail, not the sidebar). Drawer is closed by default; the toggle shows the count.
- **Notice panel.** Reused as `b-notice` with `b-notice-success`, `b-notice-warning` modifiers; the warning variant is the default for inline errors so the page has one consistent error voice.
- **Daily quota indicator.** Lives in the account popover, not the topbar pill. Frees the topbar for the ⌘K trigger and the user identity.
- **Analysis progress timeline.** Phase labels are reported by `useAnalysisJob` and rendered verbatim. The hook does any user-facing label massaging.

---

## 7 · How to use this package as design-system input

When briefing a new design pass (Claude Design, Figma, a sibling product, etc.), the most useful entry points are:

1. **`specs/chrome.md`** for the overall page frame (topbar, rail, hero, palette, FAB).
2. **The token table in §4 above** for color, type, spacing, radius, motion.
3. **§5 Visual rhythm rules** for the conventions that aren't in the token table but are visible at a glance.
4. **The relevant per-step spec** (`01-resume.md` … `04-analysis.md`) when the new surface analogues an existing tab.
5. **`prototype/index.html`** for a live A/B/C compare — useful when the brief is "show me what we considered and rejected."

The shipped CSS class names (e.g. `.b-rail`, `.b-region`, `.b-job-card`, `.b-filter-popover`) are the actual stable contract. The class names in `direction-b.css` here are the original prototype names; some renamed during the build, so cross-reference `frontend/src/app/globals.css` if you're pulling specific styles.
