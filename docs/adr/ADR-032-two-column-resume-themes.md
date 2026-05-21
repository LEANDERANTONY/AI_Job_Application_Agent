# ADR-032: Six bespoke two-column résumé themes

- Status: Accepted
- Date: 2026-05-21

## Context

[ADR-029](ADR-029-themespec-single-source-and-color-theme-expansion.md)
shipped the single-source `ThemeSpec` registry and a series of
single-column colour themes, plus ONE gated two-column theme,
`presentation_twocol`. That two-column theme was always a **placeholder**:
a single generic builder (`_build_resume_html_twocol`) rendered a
Deedy-style asymmetric layout from the same `ThemeSpec` palette as the
single-column themes, and ADR-029 / `report.md` explicitly held it from
the user surface "pending a designer-grade rework".

The operator has now commissioned that rework: six finished two-column
résumé designs, delivered as six standalone HTML/CSS documents in
`resume_builder/` (`01-timeline-tech`, `02-editorial-minimal`,
`04-classic-slate`, `05-monochrome-black`, `08-plum-berry`,
`10-burgundy-champagne`). They are **genuinely distinct designs**, not
palette variants of one layout:

- Each has its own `<style>` block — different mastheads (monogram
  circle vs. eyebrow vs. double-rule vs. oversized index line),
  different section-header treatments (accent tick / underline rule /
  flanking rule both sides), different sidebar block styling.
- There are **three distinct experience-section structures**: a
  dot-and-rail timeline (`01`, and a heavy-rule variant in `05`), a
  left date-gutter (`04`, `10`), and a head-row with the dates inline
  (`02`, `05`, `08`).

The single generic `_build_resume_html_twocol` cannot express six
bespoke designs. A decision is needed for how to represent them.

## Decision

**Each two-column theme carries its own renderer, selected by a new
`ThemeSpec` field; `_build_resume_html` extends its existing
`layout == "two_column"` branch to dispatch by theme.**

Concretely:

1. **`ThemeSpec` gains one field: `twocol_layout: str = ""`.** For a
   single-column theme it stays `""`. For a two-column theme it names
   the bespoke layout (`"timeline_tech"`, `"editorial_minimal"`,
   `"classic_slate"`, `"monochrome_black"`, `"plum_berry"`,
   `"burgundy_champagne"`). This is the ONLY `ThemeSpec` change — it
   is just another spec attribute, so the ADR-029 single-source model
   holds: every palette (`resume_palette`, `cover_letter_palette`,
   `docx_palette`) still derives from the one registry, and a new
   two-column theme is still **one registry entry**.

2. **`_build_resume_html` dispatches.** Its existing early-return
   branch (`artifact is not None and spec.layout == "two_column"`)
   now routes to `_render_twocol_resume(artifact, title, spec)`, which
   looks the bespoke renderer up in a `_TWOCOL_RENDERERS` dict keyed
   by `spec.twocol_layout`. The single-column path below is provably
   untouched.

3. **Each bespoke renderer is a Python function** that emits a full
   self-contained HTML document: the template's exact `<style>` block
   (colours/metrics inlined — these themes are NOT re-palettised
   through `ThemeSpec` colour fields, because the designs ARE the
   colour; the `ThemeSpec` colour fields exist only so the
   cover-letter + DOCX renderers still produce a coherent matched
   document, see below) plus the template DOM bound to artifact data.

4. **Three shared structural builders, not six.** The three
   experience structures (timeline rail / date gutter / head row) are
   each one parametrized builder; the six renderers compose them with
   their own section-header / project / publication / sidebar markup.
   This keeps the six renderers small and the structural logic
   single-sourced per family.

5. **Faithful reproduction is a hard constraint.** These are approved
   designs. The CSS in each renderer is the template's CSS verbatim;
   only the hardcoded dummy DOM is replaced by data binding. No
   redesign.

### Why a per-theme renderer (not the alternatives)

- **One generic builder + more palette tokens** (the
  `presentation_twocol` approach extended): rejected — six bespoke
  `<style>` blocks with three different experience structures cannot
  collapse to a token set. This is exactly why the placeholder needed
  a "designer-grade rework".
- **An external template engine (Jinja) + six template files**:
  rejected for v1 — the renderer is otherwise pure-Python string
  formatting with no template-engine dependency, and adding one for
  six templates is disproportionate. The per-function approach keeps
  the existing `escape`-everything discipline visible in code.
- **Six top-level `ThemeSpec.layout` values**: rejected — `layout`
  is the `single_column | two_column` discriminator that the
  *cover-letter* and *DOCX* paths also read; overloading it with six
  values would force every non-resume reader to enumerate them. A
  separate `twocol_layout` field keeps `layout` binary.

## `presentation_twocol` — retired

`presentation_twocol` was the placeholder these six themes are the
rework *of*. Keeping it would mean a seventh two-column option that is
strictly worse than the six finished designs and confusing in the
picker. It is **removed**: its `ThemeSpec`, its `RESUME_THEMES` entry,
and its generic builder (`_build_resume_html_twocol`,
`_build_structured_resume_body_twocol`) are deleted. It was never on
the user surface (excluded from every frontend picker and both
backend `Literal`s), so removing it is not a user-facing regression.
The section-split constants `_TWOCOL_MAIN_SECTIONS` /
`_TWOCOL_SIDEBAR_SECTIONS` are **kept** — the six new renderers reuse
them for the main-column / sidebar section assignment.

## Gating, ATS, and DOCX

- **Gating stays by-exclusion** (ADR-027 / ADR-029): Free =
  `professional_neutral` only; any other theme is Pro/Business via
  `export_entitlement_block_reason`. The six two-column themes are
  non-`professional_neutral`, so they are Pro/Business with **no
  `tiers.py` change** — verified.
- **Two-column is NON-ATS.** Multi-column / sidebar layouts are the
  #1 documented résumé-parser failure cause. The picker hint
  (`THEME_HINT`) for each of the six carries an explicit
  "two-column, NOT ATS-safe" warning, the same way the placeholder
  was to have warned. DOM is authored **header → main → sidebar** so
  the PDF text layer still extracts as a coherent linear read — the
  realistic tolerance ceiling for a deliberately non-ATS design.
- **DOCX renders single-column.** The DOCX renderer has no layout
  input; a two-column theme's DOCX falls back to the single-column
  DOCX in that theme's palette. This matches the documented
  `presentation_twocol` policy (ADR-029) and ADR-015's
  DOCX-two-column deferral. Carried forward unchanged.
- **Cover letters never branch on layout** — prose is always
  single-column; a two-column theme's cover letter uses its
  `cover_letter_palette()` (derived from the `ThemeSpec` colour
  fields, which is why those fields are still set per theme).

## Product-knowledge / policy copy

Shipping six selectable two-column themes **reverses** the standing
product policy. `src/prompts.py` `_PRODUCT_KNOWLEDGE_BLOCK` (and its
two byte-mirrored registry copies, `prompts/assistant/v1.json` +
`prompts/assistant_text/v1.json`) previously said "There is no
two-column, multi-column, or sidebar resume theme available today".
That sentence is replaced with copy that describes the six two-column
themes accurately: available to users, **non-ATS**, Pro/Business-gated,
single-column themes remain the ATS-safe default set.

## Consequences

### Positive

- Six approved designs ship faithfully; the placeholder is gone.
- Adding a future two-column theme is still one `ThemeSpec` entry +
  one renderer function — the ADR-029 single-source guarantee holds.
- The single-column code path is byte-identical (the dispatch is an
  early return reached only for a `two_column` spec).

### Negative

- The two-column renderers inline their CSS rather than deriving
  colours from `ThemeSpec` colour fields. Intended — the designs are
  the colour — but it means a two-column theme's *résumé* look and its
  *cover-letter/DOCX* look are single-sourced only at the structural
  level, not the colour level. Documented; the `ThemeSpec` colour
  fields for the six are set to match their design so the matched-set
  feel holds.

### Neutral

- DOCX two-column remains deferred (ADR-015 / ADR-029).
- `renderer_fidelity_runner.py`'s theme list swaps `presentation_twocol`
  for the six new keys (a manual quality runner, not part of pytest).

## References

- [ADR-029](ADR-029-themespec-single-source-and-color-theme-expansion.md)
  — the `ThemeSpec` single-source model this extends; `layout`
  discriminator; the `presentation_twocol` placeholder this retires.
- [ADR-027](ADR-027-tier-gated-export-entitlement.md) — by-exclusion
  export entitlement the two-column themes inherit unchanged.
- [ADR-015](ADR-015-docx-first-artifact-export-with-theme-palette.md)
  — DOCX-two-column deferral.
- Source designs: `resume_builder/01,02,04,05,08,10-*.html`.
- Verification: `tests/test_exporters.py` (per-theme render tests).
