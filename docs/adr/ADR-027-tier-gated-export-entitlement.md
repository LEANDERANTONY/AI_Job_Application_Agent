# ADR-027: Tier-Gated Export Entitlement (Free = PDF + Professional theme)

- Status: Accepted
- Date: 2026-05-17

## Context

The landing pricing cards differentiate the tiers on export capability: Free is advertised as **"PDF export, Professional theme"** while Pro/Business advertise **"PDF + DOCX export, all themes"**. A pricing-claims audit (every bullet cross-referenced against `backend/tiers.py` + the gating code) found that differentiation was **not backed by any code**:

1. Every tier check in the codebase was on a metered counter (`tailored_applications`, `premium_applications`, `assistant_turns`, `saved_jobs`, …). **Nothing** gated `export_format` or `resume_theme`/`cover_letter_theme`.
2. `POST /workspace/artifacts/export` (the main tailored-resume / cover-letter download) took **no auth dependency at all** — it operated purely on the `workspace_snapshot` in the request body, so there was no user identity to resolve a tier from even if a check had existed.

Net: a Free user could already download DOCX and use either theme. The Free/Pro export bullets were a fabricated paywall — exactly the class of unwired claim the audit exists to catch. Two ways to make the pricing copy honest: (a) reword the bullets to drop the differentiation, or (b) wire the gate so the existing copy becomes true. We chose (b) — DOCX + theme choice is a reasonable paid lever and the copy is already shipped.

## Decision

Enforce the export entitlement server-side as an **entitlement, not a metered counter**, reusing the existing quota 429 path so the frontend needs no new surface.

### Policy lives in `backend/tiers.py` (single source of truth)

`FREE_EXPORT_FORMAT = "pdf"` and `FREE_EXPORT_THEME = "professional_neutral"` (also the product-wide DEFAULT theme — see the Update note below), plus `export_entitlement_block_reason(tier, *, export_format, themes) -> str | None`. Pro/Business return `None` (full entitlement). Free returns a short human label (`"DOCX export"` / `"Custom export themes"`) when the requested format/theme is outside the free allowance; format/theme comparison is whitespace- and case-insensitive (matching the request models' `_strip_theme` normalisation) and a blank/omitted value is never a violation (a caller that doesn't pass a theme must not be upsold). These two constants are kept in lockstep with the pricing copy — changing what Free gets is a pricing decision, recorded here, not a silent refactor.

### Enforcement reuses the `QuotaExceededError` 429 (not a bespoke error)

`backend/quota.py::enforce_export_entitlement(...)` raises `QuotaExceededError` with `counter="premium_export"`, `current=0`, `cap=0`, `reset_period="lifetime"`, `tier=tier`. This is the *same pattern* the `premium_applications` "Pro+ feature" rejection already uses (`_build_quota_exceeded_error`): an entitlement gate that flows through the canonical 429 handler so the frontend renders the uniform upgrade nudge (`.b-notice-action`). `counter="premium_export"` is a display-routing hint only — deliberately **not** a `TIER_CAPS` counter (there is no count to track); `reset_period="lifetime"` keeps the frontend from rendering a wrong "resets on the 1st" line.

### Both export routes gated; the main one gains auth

`enforce_export_entitlement` is called in both `POST /workspace/resume-builder/export` (already authed) and `POST /workspace/artifacts/export` (the missing `get_optional_auth_tokens` dependency was added). Tier resolution is **best-effort and never hard-fails the allowed path**: a soft `_resolve_export_tier` helper resolves anon / expired / invalid sessions to `"free"` (the most restrictive tier) rather than 401-ing, so the Free-allowed `pdf` + `professional_neutral` export keeps working for everyone — including anonymous callers. Only the DOCX / non-`professional_neutral` request on a non-paid tier is blocked. The gate runs before any session hydrate / export work so a blocked request has no side effects.

## Consequences

### Positive

- The shipped Free/Pro/Business export pricing bullets are now true by construction.
- One source of truth (`backend/tiers.py`) for the export policy, lock-stepped with the pricing copy; a future "let Free have DOCX" change is a one-line, reviewed, pricing-visible edit.
- Zero new frontend surface: the existing 429 → `Notice` + `.b-notice-action` "Upgrade" CTA handles the rejection uniformly with every other quota wall.
- `/workspace/artifacts/export` now has a user identity, closing a gap where a metered/abuse decision could never be made on that route.

### Negative

- `/workspace/artifacts/export` is no longer anonymous at the FastAPI layer. In practice the whole workspace is already behind Google sign-in to reach the export UI, and the soft resolver defaults missing auth to Free (most restrictive) rather than rejecting, so no legitimate flow breaks — but the route's contract did change.
- Reusing `QuotaExceededError` for an entitlement (no real `counter`/`cap`) is a slight semantic stretch; mitigated by following the established `premium_applications` precedent and the `reset_period="lifetime"` shaping.

### Neutral

- Preview (`/workspace/artifacts/preview`) is intentionally **not** gated — previewing a theme in-app is the upsell, only the *download* is the paid lever.
- Frontend polish (pre-disabling the DOCX button + theme options for Free with an inline upgrade hint) is deliberately deferred; today a Free DOCX click returns the standard upgrade nudge, consistent with every other quota wall.

## Alternatives considered

- **Reword the pricing copy to drop the export differentiation.** Rejected: DOCX + theme choice is a legitimate paid lever and the differentiated copy was already shipped; making it true is the higher-value outcome.
- **A dedicated `FeatureLockedError` + new 402/403 handler + new frontend handling.** Rejected as over-engineering: it would duplicate the upgrade-CTA UX that the `QuotaExceededError` 429 path already renders.
- **Gate in the frontend only (hide DOCX/theme for Free).** Rejected: a frontend-only gate is not enforcement — the endpoint must be the source of truth; frontend pre-disabling is an optional later polish on top.

## References

- `backend/tiers.py` — `FREE_EXPORT_FORMAT`, `FREE_EXPORT_THEME`, `export_entitlement_block_reason`
- `backend/quota.py` — `enforce_export_entitlement`, `_build_quota_exceeded_error` (the `premium_applications` precedent it mirrors)
- `backend/routers/workspace.py` — `_resolve_export_tier`, both export routes
- `tests/backend/test_export_entitlement.py` — 14 hermetic policy + raiser tests
- ADR-021 (atomic quota with refund-on-failure) and ADR-020 (tier resolution shim) — the quota/tier infrastructure this builds on
- ADR-015 (DOCX-first artifact export with theme palette) — the export surface now being entitlement-gated

## Update — 2026-05-17 (same day, pre-settle refinement)

The initial draft set the Free theme to `classic_ats`. A same-day
product call changed it: **Free's theme is `professional_neutral`**,
and `professional_neutral` is now the **product-wide default theme**
(every request model + the frontend theme state + the
`artifact_export_service` normaliser default to it). `classic_ats`
becomes the Pro/Business-only alternate.

Why the default also moved: every theme field used to default to
`classic_ats`. With Free restricted to `professional_neutral` but the
default still `classic_ats`, a Free user who never opened the theme
picker would have been blocked on their **own default export**.
Making `professional_neutral` the global default closes that hole —
the Free-allowed combination is exactly what an untouched export
produces. Paid tiers can still switch to `classic_ats`.

Consequence for tests: `tests/test_backend_workspace.py` export tests
pre-date the gate and exercise export *mechanics* (DOCX round-trip,
snapshot forwarding, multi-role rendering). An autouse fixture there
resolves the export tier as a paid user so they keep testing
mechanics rather than all 429-ing; the entitlement itself stays
exclusively + exhaustively tested in `test_export_entitlement.py`
(themes inverted accordingly).

Governance note: the Decision text above was corrected in place
(rather than spawning a superseding ADR) because this ADR was
authored and refined within the same work session, before it had
settled as a relied-upon historical record. This Update section is
the audit trail of that refinement.
