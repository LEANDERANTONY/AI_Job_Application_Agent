# ADR-015: DOCX-First Artifact Export With Theme Palette

- Status: Accepted
- Date: 2026-05-07

## Context

The recruiter-facing export had drifted across three earlier decisions:

- [ADR-006](ADR-006-playwright-first-pdf-export.md) initially picked Playwright/Chromium for PDF rendering with a ReportLab fallback.
- ADR-006 was superseded informally by a WeasyPrint-based pipeline once the local Windows runtime made Playwright subprocess startup unreliable.
- The frontend kept exposing both a "Download Markdown" and a "Download PDF" button — Markdown was useful as an editing intermediate but produced confusing artifacts in the wild because users would paste raw `**bold**` syntax into application portals that don't render Markdown.

Two new product needs forced a fresh decision:

- The conversational resume builder ([ADR-016](ADR-016-conversational-llm-resume-builder.md)) needs an export from a draft profile that doesn't yet have a JD; the existing artifact-export route assumed a `TailoredResumeArtifact` produced by the agentic workflow.
- Recruiters consistently asked for a DOCX so they could paste sections into their ATS. PDF was acceptable as a final artifact but not as the only artifact — DOCX is what survives the next editing round.

We also wanted both themes (`classic_ats` for ATS-safe single-column layouts, `professional_neutral` for editorial-leaning Georgia-bodied profiles) to read consistently across PDF and DOCX so a user picking a theme gets the same document in both formats.

## Decision

DOCX is now the primary artifact-export format alongside PDF. Markdown export is removed entirely.

The pipeline:

- `src/exporters.py` exposes `export_pdf_bytes(artifact, theme)` and `export_docx_bytes(artifact, theme)` for both `TailoredResumeArtifact` and `CoverLetterArtifact`.
- The DOCX renderer is built on `python-docx`, mirrors the structured PDF render decomposition (header, summary, skills, experience, projects, education, publications, certifications), and honours `artifact.section_order` so per-profile section ordering ([ADR-016 / Day 38 in DEVLOG](../DEVLOG.md)) flows into both outputs.
- A shared palette resolver (`_RESUME_THEME_PALETTES`) keys `classic_ats` and `professional_neutral` to font family, accent color, and heading rules. Both PDF (HTML/CSS via WeasyPrint) and DOCX (python-docx style runs) pull from the same palette so the two formats stay visually aligned without hand-syncing.
- The `WorkspaceArtifactExportRequest` now accepts `export_format: "pdf" | "docx"`; the markdown branch is removed from `backend/services/artifact_export_service.py`. Frontend types and download buttons drop the markdown literal and add a DOCX button next to the PDF button.
- The resume builder gets its own `POST /workspace/resume-builder/export` endpoint that synthesizes a `TailoredResumeArtifact` from the builder session's draft profile (no JD, empty `target_role`, empty `change_log`, empty `validation_notes`, `section_order` from `compute_section_order(candidate_profile)`), then dispatches through the same `export_pdf_bytes` / `export_docx_bytes` path. Auth-gated like the other resume-builder routes.

WeasyPrint stays as the PDF renderer (no change from the post-Playwright state).

## Alternatives Considered

### 1. Keep Markdown export and add DOCX
Rejected. Three formats means three code paths to maintain, three sets of theme styling, three columns of UI. The Markdown intermediate isn't a recruiter-facing artifact — users were copy-pasting raw syntax into application portals. The structured `TailoredResumeArtifact` schema already gives us everything Markdown was carrying, so the intermediate has no remaining purpose.

### 2. Convert PDF to DOCX via pandoc / libreoffice headless
Rejected. Adds a heavy dependency on the deploy host (LibreOffice install or pandoc binary) and the conversion fidelity for layout-rich documents is poor. A native `python-docx` renderer over the structured artifact gives us deterministic output that we can theme to match the PDF.

### 3. DOCX only, drop PDF
Rejected. Some recruiters specifically want a finished PDF for the application portal upload step. Both formats have a real use case.

### 4. One renderer per surface (resume vs cover letter), no shared palette
Rejected. Two formats × two artifacts × two themes = four renderers. A shared palette resolver collapses it back to two renderers (PDF + DOCX), each parameterized by theme + artifact type.

## Consequences

### Positive

- Recruiters get the format they actually edit in. DOCX exports survive the next round of changes without manual re-formatting.
- The shared palette resolver means a theme tweak (color, font, heading style) lands in both PDF and DOCX by editing one mapping.
- The resume builder finally has a download surface that doesn't require a JD upload — first-class exit point at "Generate base resume" with theme picker + format buttons.
- Removing Markdown export simplified the artifact viewer, the export hook, and the backend dispatch table.
- The structured-artifact schema (`TailoredResumeArtifact` / `CoverLetterArtifact`) is now load-bearing for export, which means schema changes are explicit rather than implicit through Markdown formatting.

### Negative

- `python-docx` is now a runtime dependency. Lightweight (~500 KB), but one more thing to keep up to date.
- DOCX visual fidelity in LibreOffice is a known weak spot; we test in Microsoft Word and Google Docs, document LibreOffice as nice-to-have but not blocking.
- The resume-builder export path duplicates a small amount of artifact-synthesis logic that the agentic workflow does naturally. Acceptable for now because the synthesis is straightforward; revisit if more "non-workflow exports" land.

## Follow-Up

- Supersedes [ADR-006](ADR-006-playwright-first-pdf-export.md) and the implicit Markdown export contract.
- Track DOCX rendering issues in the public bug tracker so we can prioritize Word vs Google Docs vs LibreOffice fidelity work.
- If a third theme lands, extract the palette resolver into a typed `ThemeSpec` so themes don't drift across renderers. → **Done in [ADR-029](ADR-029-themespec-single-source-and-color-theme-expansion.md)** (2026-05-19): one `ThemeSpec` registry derives all three palettes + the backend gate set; existing two themes proven byte-identical.
