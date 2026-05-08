# Step 4 — Analysis & Artifacts

Maps to `frontend/src/components/workspace/AnalysisRunner.tsx` + `ArtifactViewer.tsx`. The shipped surface follows the original handoff's overall shape, but **the export contract changed during the build**: Markdown export was removed entirely and DOCX was added as a first-class format, both formats carry a theme picker, and the streaming chat lives inside the floating FAB rather than the artifact viewer.

## Layout

```
┌─ Run header ───────────────────────────────────────────────────────┐
│ STEP 04 · ANALYSIS                                                 │
│ Generate a tailored resume + cover letter                          │
│ ─────────────────────────                                          │
│ Inputs: ✓ Resume   ✓ Job description                               │
│                                                                    │
│         [ Run analysis ]   ← primary CTA, centered                 │
└────────────────────────────────────────────────────────────────────┘

┌─ Progress timeline (visible while running) ────────────────────────┐
│ STEP 04 · WORKFLOW RUN                                             │
│ ● Tailoring             · 0:02                                     │
│ ● Review                · 0:05                                     │
│ ◐ Resume generation     · running...   ← current phase             │
│ ○ Cover letter                                                     │
└────────────────────────────────────────────────────────────────────┘

┌─ Artifact viewer (mounts inline when ready) ───────────────────────┐
│ STEP 04 · DOCUMENTS                                                │
│ [ Tailored Resume | Cover Letter ]                                 │
│ ─────────────────────────                                          │
│ ┌─ Document body ────────────────────┐ ┌─ Right rail ─────────────┐│
│ │ # Aria Patel                       │ │ Tailored Resume           │
│ │ Staff ML Engineer                  │ │ for Anthropic             │
│ │                                    │ │ Senior ML Engineer        │
│ │ ## Summary                         │ │                           │
│ │ ▍ streaming text with caret...     │ │ Theme:                    │
│ │   [Streaming] chip                 │ │  ( ) Classic ATS          │
│ │                                    │ │  ( ) Professional Neutral │
│ │ ## Experience                      │ │                           │
│ │ ...                                │ │ [ Download PDF ]          │
│ │                                    │ │ [ Download DOCX ]         │
│ │                                    │ │                           │
│ │                                    │ │ Generated 2:14 ago        │
│ └────────────────────────────────────┘ └───────────────────────────┘│
└────────────────────────────────────────────────────────────────────┘
```

## Workflow phases

The orchestrator runs the following stages, each surfacing as a row in the timeline:

1. `tailoring` — TailoringAgent produces tailoring guidance from the (resume, JD) pair.
2. `review` — ReviewAgent passes corrections back to tailoring when needed (single-pass review per ADR-010).
3. `resume_generation` — ResumeGenerationAgent assembles the tailored resume artifact.
4. `cover_letter` — CoverLetterAgent assembles the cover letter artifact.

The earlier `fit` and `strategy` stages are no longer in the live workflow — fit-scoring is still used internally by tailoring but no longer surfaces as a visible phase. Phase labels come from `useAnalysisJob`; whatever the hook reports is what renders.

## Component contract (shipped)

```ts
interface AnalysisRunnerProps {
  ready: boolean;            // true when both resume + JD are present
  status: AnalysisStatus;    // "idle" | "running" | "done" | "error"
  phases: AnalysisPhase[];   // from useAnalysisJob
  onRun: () => void;
  result: WorkspaceAnalysisResponse | null;
}

type ArtifactTab = "resume" | "cover";
type ArtifactTheme = "classic_ats" | "professional_neutral";
type WorkspaceArtifactExportFormat = "pdf" | "docx";

interface ArtifactViewerProps {
  tab: ArtifactTab;
  onTabChange: (t: ArtifactTab) => void;
  artifact: TailoredResumeArtifact | CoverLetterArtifact;
  streaming: boolean;        // shows caret + Streaming chip
  theme: ArtifactTheme;
  onThemeChange: (t: ArtifactTheme) => void;
  onExport: (format: WorkspaceArtifactExportFormat) => void;
  exporting: boolean;
}
```

## Export pipeline (shipped — DOCX-first)

The original handoff sketched **PDF, Markdown, Copy to clipboard** download buttons. The shipped pipeline is:

- **Download PDF** — calls `useArtifactExport.export("pdf", theme)` → `POST /workspace/artifacts/export` with `{ artifact_id, export_format: "pdf", theme }`. WeasyPrint renders the artifact's structured body to PDF.
- **Download DOCX** — same shape, `export_format: "docx"`. `python-docx` renders the structured body using a shared theme palette so PDF and DOCX read as the same document.
- **Markdown is gone.** Removed in 2026-05 because Markdown was an editing intermediate, not a recruiter-facing artifact, and users were copy-pasting raw `**bold**` syntax into application portals. The `WorkspaceArtifactExportRequest.export_format` literal union is now `"pdf" | "docx"`.
- **No "Copy to clipboard"** button shipped — the structured DOCX is the editing format users want.

### Theme picker

Two themes ship behind a single radio:

| Theme | Vibe | Use case |
|---|---|---|
| `classic_ats` | ATS-safe single-column, sans body, neutral accent | Default — works everywhere |
| `professional_neutral` | Editorial, Georgia body, pure black/white, no warm accents | Recruiter-leaning profiles, design / writing roles |

The palette resolver lives in `src/exporters.py` (`_RESUME_THEME_PALETTES`) and is shared between the PDF and DOCX renderers, so a theme switch lands consistently in both formats. See ADR-015 in the project docs.

The theme also affects the **on-screen artifact preview** so the user sees what they're about to download. Switching theme re-renders the preview but doesn't re-run the workflow.

## Resume builder export shortcut

The resume builder (Step 1, Assistant mode) ships its own download row directly under "Generate base resume" — same theme + format options, different endpoint (`POST /workspace/resume-builder/export`) that synthesizes a `TailoredResumeArtifact` from the builder session's draft profile (no JD, empty `target_role`, `section_order` from `compute_section_order(candidate_profile)`). See `01-resume.md` and ADR-016.

## Streaming contract

Streaming uses the SSE endpoint `POST /workspace/assistant/answer/stream`. The frontend consumer is `streamWorkspaceAssistantAnswer` in `lib/api.ts`, which uses `fetch` + `ReadableStream` (not `EventSource` — `EventSource` only supports GET and can't carry the `X-Auth-Access-Token` header).

Event contract:

| Event | Data | When |
|---|---|---|
| `meta` | `{"sources": [...]}` | First event, immediately after the OpenAI request dispatches. Sources are pre-computed from the workspace snapshot. |
| `delta` | `{"text": "..."}` | One per OpenAI streaming token chunk. Frontend appends to the growing `answer` buffer. |
| `followups` | `{"suggested_follow_ups": [...]}` | After the stream completes, before `done`. |
| `done` | `{}` | Signals end. Frontend stops the reader. |
| `error` | `{"detail": "..."}` | If anything fails. Frontend shows the error and closes. |

This contract is shared with the AssistantPanel chat (the FAB-mounted assistant uses the same endpoint). The artifact viewer's "streaming text with caret" affordance reads from the same buffer.

Caddy's reverse proxy in `deploy/vps/Caddyfile` is configured with `flush_interval -1` so streamed deltas reach the browser without buffering. The endpoint sets `X-Accel-Buffering: no` on the response too, belt-and-suspenders.

## Behavior preservation

- "Run analysis" disabled until `ready` is true (resume + JD both present).
- `useAnalysisJob` polling unchanged — phases drive the timeline.
- Streaming caret animation is presentation only: a 1px-wide block element after the last token, blinking @ 1Hz, that hides when `streaming === false`.
- "Streaming" chip in the document header is also presentation; same condition.
- Downloads → `useArtifactExport` (PDF, DOCX).
- Tab switch is local state; downloads + theme picker always reflect the active tab.

## States

| Phase | Visual |
|---|---|
| Not ready | Header with disabled CTA + "Need: resume, JD" hint |
| Idle (ready, not run) | CTA active, no timeline, no artifact |
| Running | Timeline expands, current phase shown with `◐` half-dot animation |
| Streaming results | Artifact viewer mounts, streaming chip + caret on the active tab |
| Done | Streaming chip hides, "Generated Nm ago" timestamp + theme picker + download buttons in the right rail |
| Error | Notice panel above CTA with retry button; timeline freezes at the failed phase with `✗` |

## Streaming caret implementation

Append `<span class="b-stream-caret" data-streaming={streaming} />` to the live text node. CSS handles blink + hide:

```css
.b-stream-caret { display: inline-block; width: 2px; height: 1.05em;
  background: var(--accent); margin-left: 2px; vertical-align: -2px;
  animation: bStreamBlink 1s step-end infinite; }
.b-stream-caret[data-streaming="false"] { display: none; }
@keyframes bStreamBlink { 50% { opacity: 0; } }
```

## CSS classes

- `.b-run-cta` — primary "Run analysis" button
- `.b-timeline`, `.b-timeline-row` — phase list
- `.b-artifact` — overall artifact viewer
- `.b-artifact-doc` — document body scroller
- `.b-artifact-rail` — right rail (theme picker + download buttons + meta)
- `.b-artifact-tab-pill` — Tailored Resume / Cover Letter tab pill
- `.b-theme-picker`, `.b-theme-option` — radio styling for the two themes
- `.b-stream-chip` — "Streaming" chip
- `.b-stream-caret` — blinking caret

See project ADR-015 (DOCX-first export with theme palette) for the export design rationale.
