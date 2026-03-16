# ADR-006: Playwright-First PDF Export with ReportLab Fallback

## Status

Superseded on March 16, 2026

## Context

This ADR captured the earlier browser-rendering decision before the Windows runtime work on March 16, 2026 moved the product to a WeasyPrint-first exporter.

The application package can already be assembled deterministically as Markdown, but recruiter-facing output also needs a polished PDF form.

Plain-text export is not sufficient for the product direction because:

- users need a presentation-ready artifact they can share directly
- Markdown is useful for editing, but not as the final polished package
- the app already has a product-style visual system that should carry into exported output

The GitHub agent solved a similar problem by using browser-based PDF rendering rather than relying on a low-level PDF layout engine alone.

## Original Decision

Use Playwright/Chromium as the primary PDF backend for application-package export, with ReportLab retained as a fallback.

The export flow is:

1. build the deterministic application package as Markdown
2. render that Markdown into styled HTML/CSS
3. print the HTML through Chromium when available
4. fall back to ReportLab if the browser backend is unavailable or fails

Markdown remains the editable export format. PDF is the polished export format.

## Alternatives Considered

### 1. Markdown only

Rejected because it does not produce a polished recruiter-facing artifact.

### 2. ReportLab only

Rejected as the primary path because it is harder to evolve visually and tends to produce less natural document layout than browser rendering.

### 3. PDF generation directly from Streamlit UI markup

Rejected because it would couple export behavior too tightly to the UI runtime and make deterministic package rendering harder to control.

## Consequences

- PDF output can preserve a stronger visual hierarchy through HTML/CSS
- Markdown remains available for user edits before export
- the repo now depends on Playwright plus a Chromium install for the best PDF output
- fallback PDF generation still exists if the Playwright backend is unavailable
- deployment environments will need to account for the browser dependency explicitly

## Superseded By

The active product now uses WeasyPrint as the primary HTML-to-PDF renderer and keeps ReportLab as the fallback backend.

Reason for the change:

- the local Windows runtime was unreliable for Playwright subprocess startup
- WeasyPrint better matches the product goal of HTML/CSS-driven document templates without a browser dependency
- the active exporter no longer depends on Playwright or Chromium
