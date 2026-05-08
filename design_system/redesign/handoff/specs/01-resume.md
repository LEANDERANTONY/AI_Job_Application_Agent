# Step 1 — Resume Intake

Maps to `frontend/src/components/workspace/ResumeIntake.tsx`. The shipped surface kept the original "Upload / Build with assistant" toggle but the **builder mode is now a conversational LLM chat** rather than a structured form, and the builder ships its own DOCX/PDF download exit point so users without a JD can still leave with an artifact.

## Layout

```
┌─ Intake panel ─────────────────────────────────────────────────────┐
│ STEP 01 · IMPORT RESUME                                            │
│ Bring in your resume                          [Upload | Assistant] │
│ ─────────────────────────                                          │
│                                                                    │
│   Upload mode:                                                     │
│   ┌─ Dropzone ────────────────────────┐                            │
│   │ ↑ Drop your resume here           │                            │
│   │   PDF, DOCX or TXT · Up to 5MB    │                            │
│   │   [Choose file]                   │                            │
│   └───────────────────────────────────┘                            │
│   Last upload: resume_v3.pdf · 2d ago     [Clear]                  │
│                                                                    │
│   Assistant mode:                                                  │
│   ┌─ Field-completeness rail ─────────┐ Saved · auto-saving        │
│   │ ✓ Name        ✓ Location          │                            │
│   │ ✓ Target role ◐ Experience        │                            │
│   │ ○ Education   ○ Skills            │                            │
│   │ ○ Projects    ○ Publications      │                            │
│   └───────────────────────────────────┘                            │
│                                                                    │
│   [chat transcript — user + assistant alternating]                 │
│   [composer textarea] [Send]                                       │
│                                                                    │
│   When complete: [Generate base resume] then theme + download row  │
└────────────────────────────────────────────────────────────────────┘

┌─ Parsed-profile hero ──────────────────────────────────────────────┐
│ ▔▔▔▔ emissive blue hairline ▔▔▔▔                                   │
│ ◉ Parsed profile                                       [Re-upload] │
│                                                                    │
│ Aria Patel                                                         │
│ Staff ML Engineer · Inference & Serving                            │
│                                                                    │
│ San Francisco, CA · 8 yrs experience · github.com/aria             │
└────────────────────────────────────────────────────────────────────┘

┌─ Skills (left) ──────────┐  ┌─ Experience (right) ─────────────────┐
│ STEP 01 · SKILLS         │  │ STEP 01 · EXPERIENCE                 │
│ Languages & Tools        │  │ Anthropic · Staff ML Eng (2023–now)  │
│   [Python] [TypeScript]  │  │   • bullet                            │
│ ML/DL Frameworks         │  │   • bullet                            │
│   [PyTorch] [JAX] ...    │  │ Stripe · Senior ML Eng (2020–2023)   │
│ Cloud & Infra            │  │   ...                                 │
│   [AWS] [Terraform] ...  │  │                                       │
└──────────────────────────┘  └───────────────────────────────────────┘

┌─ Projects + Publications (when present) ───────────────────────────┐
│ STEP 01 · PROJECTS                                                 │
│ • Project name — short description                                 │
│ ...                                                                │
└────────────────────────────────────────────────────────────────────┘
┌────────────────────────────────────────────────────────────────────┐
│ STEP 01 · PUBLICATIONS                                             │
│ • Title — venue, year                                              │
└────────────────────────────────────────────────────────────────────┘

┌─ Parser signals (collapsible) ─────────────────────────────────────┐
│ STEP 01 · PARSER SIGNALS                                           │
│ ✓ 12 sections detected   ✓ Dates normalized   ⚠ 2 ambiguous roles  │
└────────────────────────────────────────────────────────────────────┘
```

## Mode toggle

The mode toggle at the top of the intake panel is the primary affordance:

- **Upload** — file dropzone + picker. Accepts PDF, DOCX, TXT up to 5 MB. Calls `uploadResumeFile` → backend hybrid LLM-first parser produces a `CandidateProfile`.
- **Assistant** — conversational chat builder. Calls `startResumeBuilderSession`, then `sendResumeBuilderMessage` per turn until the user has enough fields filled to generate.

Switching modes does **not** discard the other mode's state — an uploaded resume stays uploaded, an in-progress assistant chat stays in progress. The user can flip back and forth.

## Conversational resume builder (Assistant mode)

The original handoff just sketched "Conversational chat surface (existing assistant component)" — the shipped builder is significantly more involved.

### Field-completeness rail

The builder doesn't march through "Step N of 5" wizard pages. Instead, a checklist rail shows what's been captured so the user can see progress at a glance and the LLM picks the next gap:

| Field | Filled when |
|---|---|
| Name | `full_name` non-empty |
| Location | `location` non-empty |
| Target role | `target_role` non-empty |
| Contact | `contact_lines` non-empty |
| Experience | `experience_notes` non-empty |
| Education | `education_notes` non-empty |
| Skills | `skills` non-empty |
| Certifications | `certifications` non-empty |
| Projects | `projects_notes` non-empty |
| Publications | `publications` non-empty |

Each row renders as `○` / `◐` (partial) / `✓` plus the field label.

### Chat transcript

Transcript style (not bubble style — the bubble experiment shipped + reverted in 2026-05). User + assistant turns alternate with subtle indentation and a `--font-mono` role marker. The composer is a single auto-grow textarea with a `Send` button; Enter sends, Shift+Enter newlines.

### Persistence indicator

The session row in `resume_builder_sessions` (Supabase) has a 7-day TTL refreshed on every save. The intake panel surfaces a tri-state pill next to the field rail:

| State | Pill | Meaning |
|---|---|---|
| Saved | `Saved · auto-saving` | Authenticated user, save round-trip succeeded |
| Skipped | `Working locally` | Authenticated user, save round-trip failed (network) — work continues in browser state |
| Unauthenticated | `Sign in to save your draft` | Anonymous user; the chat works but won't survive a reload |

### Generate base resume + download row

Once the user has filled enough fields (the LLM proposes "Generate base resume" when the state is plausible), clicking the button:

1. Runs the **structuring pass** server-side (`POST /workspace/resume-builder/generate`) — LLM-first content quality lift that buckets the flat `skills` list into named categories, expands thin one-liner summaries to full paragraphs, and recovers a full name when the LLM intake dropped a surname mid-conversation.
2. Computes `section_order` via `compute_section_order(candidate_profile)` so students lead with Education / Projects, academics with Publications, seniors with Experience after Skills.
3. Renders a download row directly under the chat:

```
   Download your base resume

   Theme:  ( ) Classic ATS    ( ) Professional Neutral

   [Download PDF]   [Download DOCX]
```

4. Calls `POST /workspace/resume-builder/export` with `{ session_id, export_format, theme }` — same export path as the tailored-resume artifact (see `04-analysis.md`).

This is the **first-class exit point** for users who just want a base resume. They can stop here and never load a JD.

## Parsed-profile hero (after upload)

When upload mode produces a parsed profile, the intake panel collapses to a single "Last upload" row and the hero takes over below:

- Emissive blue top hairline (`--accent-glow` glow on a 1px border)
- "Parsed profile" pill on the left, "Re-upload" ghost button on the right
- Big display name (`--font-display`, semibold, tight letter-spacing)
- Title + meta line in `--fg-2`
- Meta-dot row: location · years · primary contact link

If the user is in assistant mode, the hero shows the in-progress draft profile values too — same layout, with `Working draft` instead of `Parsed profile`.

CSS: `.b-resume-hero`, `.b-resume-hero-head`, `.b-resume-hero-pill`, `.b-resume-hero-title`, `.b-resume-hero-sub`, `.b-resume-hero-meta`.

## Skills + Experience two-up

A two-column grid below the hero. On mobile (≤ 540px) it stacks to one column.

### Skills column

Skills render in **named categories** — not a flat pipe-separated list. The structuring pass groups them into buckets like:

- Languages & Tools
- ML/DL Frameworks
- Cloud & Infrastructure
- Data & Storage
- Domain expertise
- (etc.)

Each category becomes a row with the category label as a small uppercase eyebrow and chips below. Falls back to the flat `highlighted_skills` list when `skill_categories` is empty (legacy JD-driven exports keep their original layout).

### Experience column

One row per `WorkExperience`:

- Title · organization (display weight)
- Date range (mono caption)
- Bullet list (parser output verbatim — bullets aren't reordered or massaged)

## Projects + Publications

Render as their own sections **only when the underlying field is non-empty**. The "drop empty sections" rule is project-wide: a senior with no Publications doesn't see a "Publications" empty-state card; a student with no Experience yet doesn't see an Experience card. Same rule for Certifications.

Per-profile section ordering is driven by `section_order` from `compute_section_order(candidate_profile)`:

| Profile shape | Order |
|---|---|
| Default | summary, skills, experience, projects, education, publications, certifications |
| Student / early-career | summary, education, projects, skills, experience, publications, certifications |
| Academic | summary, publications, education, experience, skills, projects, certifications |

The HTML and DOCX renderers honour the same `section_order`, so the Word doc reads in the same order as the on-screen profile. See ADR-016 in the project docs for the rationale.

## Parser signals

A collapsible section at the bottom (`<details>` open by default on first load, closed after the user dismisses it once). Lists the parser-side observations: section count, normalized dates, ambiguous roles, etc. Useful for the user to confirm the parser saw what they expected.

## Component contract (shipped)

```ts
type ResumeIntakeMode = "upload" | "assistant";

type ResumeBuilderDraftForm = {
  full_name: string;
  location: string;
  contact_lines: string;
  target_role: string;
  professional_summary: string;
  experience_notes: string;
  education_notes: string;
  skills: string;
  certifications: string;
  projects_notes: string;     // free-form prose; structuring pass splits into ProjectEntry[]
  publications: string;       // one citation per line
};

type ResumeBuilderPersistenceStatus = "saved" | "skipped" | "unauthenticated";

type ResumeBuilderChatTurn = {
  role: "user" | "assistant";
  content: string;
};

interface ResumeIntakeProps {
  // Mode toggle
  intakeMode: ResumeIntakeMode;
  onIntakeModeChange: (mode: ResumeIntakeMode) => void;

  // Upload path
  candidate: CandidateProfile | null;
  onResumeUpload: (file: File) => Promise<WorkspaceResumeUploadResponse>;
  onClearUploadedResume: () => void;
  uploading: boolean;
  uploadNotice: ResumeIntakeNotice | null;

  // Builder path
  builderSession: ResumeBuilderSessionResponse | null;
  builderDraft: ResumeBuilderDraftForm;
  onBuilderDraftChange: Dispatch<SetStateAction<ResumeBuilderDraftForm>>;
  builderChatLog: ResumeBuilderChatTurn[];
  builderInput: string;
  onBuilderInputChange: (value: string) => void;
  onBuilderSendMessage: () => void | Promise<void>;
  builderLoading: boolean;
  builderGenerating: boolean;
  onBuilderGenerate: () => void | Promise<void>;
  builderPersistenceStatus: ResumeBuilderPersistenceStatus;
  builderTtlHint: string | null;     // "Refreshes through Mon Nov 11"

  // Builder export
  onBuilderExport: (
    format: WorkspaceArtifactExportFormat,
    theme: ArtifactTheme,
  ) => void | Promise<void>;
  builderExporting: boolean;
}
```

## Behavior preservation

- Drag-and-drop file → `uploadResumeFile`.
- Builder toggle → `startResumeBuilderSession` (lazy-loads the session if one already exists for the user).
- Edit-in-place fields on the parsed profile → `updateResumeBuilderDraft` keeps the structured payload fresh as the user tweaks specific fields.
- Last-upload metadata → `loadLatestResumeBuilderSession` on mount.
- Re-upload button on the hero re-opens the upload card (scrolls to top + flips mode to "upload" if the user was in assistant mode).
- Chat history persists across reloads via the session row (server-side conversation_history, NOT browser localStorage).

## States

| State | Visual |
|---|---|
| Empty | Intake panel visible (Upload mode), hero hidden |
| Uploading | Dropzone shows spinner; hero shows skeleton |
| Parsed | Intake panel collapses to "Last upload" row; hero + skills + experience + parser-signals visible |
| Parse error | Notice panel above intake card; intake panel stays open |
| Builder active (no fields yet) | Intake panel swaps body to chat surface; hero hidden until first generate |
| Builder partial | Field rail shows progress; chat transcript builds up |
| Builder generating | "Generate base resume" button flips to spinner; hero appears with `Working draft` pill once generated |
| Builder downloadable | Theme picker + Download PDF / Download DOCX row visible under the generate output |
| Unauthenticated builder | "Sign in to save your draft" pill in the rail; chat works but persistence is local-only |

## CSS classes

- `.b-intake-panel`, `.b-intake-head`, `.b-intake-mode-toggle`, `.b-intake-mode-toggle button[aria-pressed="true"]`
- Upload: `.b-dropzone`, `.b-dropzone-active`, `.b-last-upload`
- Builder: `.b-builder`, `.b-builder-rail`, `.b-builder-rail-row`, `.b-builder-chat`, `.b-builder-turn` (+ `[data-role="user"]` / `[data-role="assistant"]`), `.b-builder-composer`, `.b-builder-preview`, `.b-builder-download-row`
- Persistence pill: `.b-builder-status` (+ `[data-status="saved" | "skipped" | "unauthenticated"]`)
- Hero: `.b-resume-hero`, `.b-resume-hero-head`, `.b-resume-hero-pill`, `.b-resume-hero-title`, `.b-resume-hero-sub`, `.b-resume-hero-meta`
- Two-up: `.b-resume-twoup`, `.b-twoup-section`
- Skills: `.b-skills-category`, `.b-skills-category-label`, `.b-chip`
- Experience: `.b-experience-row`, `.b-experience-title`, `.b-experience-meta`, `.b-experience-bullets`

See project ADR-016 for the rationale behind the conversational builder design.
