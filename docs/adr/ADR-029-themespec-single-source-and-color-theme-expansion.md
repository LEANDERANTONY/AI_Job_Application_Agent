# ADR-029: ThemeSpec single-source + color-theme expansion

- Status: Accepted (Phase 1 + first color theme shipped; theme series continuing)
- Date: 2026-05-19

## Context

The operator approved widening the résumé/cover-letter theme offering
beyond the two original themes (`classic_ats`, `professional_neutral`)
with several more ATS-safe color/font themes plus one deliberately
gated, non-ATS two-column "presentation" layout. The full design
research + archetype catalogue + ATS evidence is parked in `report.md`
("Phase-0 RESULTS").

[ADR-015](ADR-015-docx-first-artifact-export-with-theme-palette.md)'s
own Follow-Up anticipated this exactly: *"If a third theme lands,
extract the palette resolver into a typed `ThemeSpec` so themes don't
drift across renderers."* The pre-existing structure made adding a
theme a multi-place, drift-prone edit:

- `src/exporters.py` carried **three hand-synced palette maps**
  (`_RESUME_THEME_PALETTES`, `_COVER_LETTER_THEME_PALETTES`,
  `_DOCX_THEME_PALETTES`).
- Two **more** hardcoded theme sets lived in the backend
  (`artifact_export_service._SUPPORTED_THEMES`,
  `resume_builder_service`'s inline set) — an unknown theme silently
  normalised to a default, so a missed edit = a theme that renders as
  the wrong theme with no error.
- The cover-letter renderer **hardcoded Georgia serif** for every
  theme. Invisible while both themes were serif-ish; a sans theme
  would render a serif letter clashing with its own sans résumé.

## Decision

A single typed `ThemeSpec` (frozen dataclass) registry,
`src/exporters._THEME_SPECS`, is the **one source of truth** for
theming. It derives all three palettes via adapter methods
(`resume_palette()`, `cover_letter_palette()`, `docx_palette()` — the
last strips `#`/upper-cases for OOXML and carries single font names).
The three module-level maps are kept but **derived** from the
registry, so the resolvers and any external reference stay
byte-for-byte identical. Adding a theme = **one registry entry**.

Supporting decisions:

- **Backend gates derive from the registry.** `src/exporters` exposes
  public `SUPPORTED_THEMES = frozenset(_THEME_SPECS)`;
  `artifact_export_service` and `resume_builder_service` import it
  instead of hand-maintaining their own theme sets. A new theme needs
  zero backend-service edits.
- **The cover letter follows the theme's prose font**, not a
  hardcoded Georgia. `classic_ats` / `professional_neutral` have
  Georgia as their prose font, so this is provably byte-identical for
  them (golden snapshots + the renderer-fidelity runner confirm zero
  regression). Sans themes now get a sans letter that matches their
  résumé — the "matched set" guarantee is now true at the font level,
  not just colour.
- **Entitlement stays by-exclusion** (ADR-027): Free =
  `professional_neutral` only; *any* other theme is Pro/Business via
  `export_entitlement_block_reason`. New ATS-safe themes need no
  `tiers.py` change. The future two-column theme gets its own
  separate, explicit non-ATS gate (Phase 3).
- **`ThemeSpec.layout` is reserved** (`"single_column"` default;
  `"two_column"` for Phase 3). Only the résumé renderer will branch on
  it — a cover letter is prose and always renders single-column.
- **First new theme shipped: `modern_blue`** — single-column (fully
  ATS-safe), all-sans, deep professional blue accent (`#1a56db`, ~5.9:1
  on white), faint cool off-white paper (`#f6f8fd`/`#f8fafe` — the
  `classic_ats` "designed, not stark" trick in a cool key; a paint
  layer, ATS-irrelevant). Pro/Business via the existing by-exclusion
  gate.

Themes are validated against real WeasyPrint output from deterministic
fixtures (zero LLM/API cost) before wiring; `creative_warm`,
`architect_mono`, and the gated `presentation_twocol` follow the same
build-sample-approve-wire loop.

## Consequences

### Positive

- Adding a colour theme is one `ThemeSpec` entry; résumé + cover
  letter + DOCX cannot drift, and the backend gates pick it up for
  free. This is the structural guarantee ADR-015's follow-up wanted.
- The existing two themes are provably output-neutral across the
  refactor (resolver dicts byte-identical for every theme + fallback;
  the 12-fixture renderer-fidelity runner byte-identical).
- A theme's cover letter now visually matches its résumé (font, not
  just colour).

### Negative

- The cover-letter body font is now theme-dependent rather than a
  fixed constant. Intended, and verified zero-regression for the two
  existing themes, but it is a behavioural coupling to be aware of
  when authoring future themes (set `prose_font_family` deliberately).

### Neutral

- The two-column layout branch is deferred (Phase 3). The `layout`
  field exists but only `single_column` is implemented.
- The three derived maps are retained (not deleted) to keep the
  refactor minimal-blast-radius and the resolvers untouched.

## Alternatives Considered

1. **Keep the three hand-synced maps, just add entries to each.**
   Rejected — this is the drift ADR-015 explicitly warned about, now
   multiplied by two more backend theme sets (five places per theme).
2. **Per-theme backend allowlists.** Rejected — duplicates the
   registry and re-introduces the missed-edit-renders-wrong-theme
   failure mode.
3. **Ship the two-column theme now.** Deferred to Phase 3: the ATS
   research (parked in `report.md`) shows multi-column is the #1
   parse-failure cause; it must ship behind its own explicit non-ATS
   entitlement + in-picker warning, not as a normal dropdown option.

## References

- Supersedes the Follow-Up of
  [ADR-015](ADR-015-docx-first-artifact-export-with-theme-palette.md)
  (the typed-`ThemeSpec` extraction it called for).
- [ADR-027](ADR-027-tier-gated-export-entitlement.md) — the
  by-exclusion export entitlement that new themes inherit unchanged.
- `report.md` → "Phase-0 RESULTS" — archetype catalogue, ATS
  evidence, and the approved theme build-list.
- Verification: `tests/test_exporters.py`,
  `tests/backend/test_export_entitlement.py`,
  `tests/quality/renderer_fidelity_runner.py` (now exercises
  `modern_blue`).
