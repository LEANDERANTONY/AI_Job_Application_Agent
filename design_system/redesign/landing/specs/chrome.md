# Chrome — Topbar, Footer, Background, Scroll Behavior

The fixed frame of the landing page. Wraps the four content sections (hero · workbench · bento · final CTA). Lives in `landing-page.tsx` as the `<LandingPage>` outer JSX + the `LandingFooter` component.

## Topbar

```
┌──────────────────────────────────────────────────────────────────┐
│ [● Job Application Copilot]      Workflow · Features · [Auth]   │
│ ─────────────────────────────────────── (hairline)              │
└──────────────────────────────────────────────────────────────────┘
```

- **Sticky:** `position: sticky; top: 0; z-index: 30;` with a backdrop-filter blur and a hairline bottom border (`var(--l-line)`). 92px tall (the value subtracted from the workbench sticky `top:`).
- **Brand (left):** `<Link href="/">` wrapping the logo glyph (`<BrandLogo size={32} />`) + the wordmark "Job Application Copilot." Brand text is `font-weight: 600; letter-spacing: -0.01em;`.
- **Nav (right):** anchor links to `#workbench` and `#features` (the bento section). Class `.l-topbar-link` — `color: var(--l-fg-2); font-size: 13.5px;` with `:hover { color: var(--l-fg) }`. **Only two nav items**; the GitHub link was consolidated into the hero CTA + footer.
- **Auth slot (rightmost):** dynamic per `useWorkspaceSession` status:
  - `loading` → `<button class="l-btn l-btn-primary l-btn-sm" disabled>Restoring session…</button>`
  - `signed-in` → a `Sign out` ghost button + an `Enter workspace` primary button side by side
  - `signed-out` → a single `Sign in with Google` primary button (Google glyph + label)

CSS: `.l-topbar`, `.l-topbar-inner`, `.l-brand`, `.l-brand-logo`, `.l-brand-name`, `.l-topbar-nav`, `.l-topbar-link`.

## Footer

```
┌──────────────────────────────────────────────────────────────────┐
│ Job Application Copilot              NAVIGATION       SOCIALS    │
│ A focused workspace for preparing    Privacy Policy   GitHub     │
│ stronger applications from one place.                LinkedIn   │
│                                                                  │
│ Built by Leander Antony A                                        │
└──────────────────────────────────────────────────────────────────┘
```

- **Three-column grid** — brand block (left) + Navigation column + Socials column (right).
- **Brand block:** wordmark + 1-line description ("A focused workspace for preparing stronger applications from one place.") + a small grey "Built by Leander Antony A" credit underneath.
- **Each column has a mono uppercase header** in `--l-fg-3` (`NAVIGATION`, `SOCIALS`) followed by anchor links in `--l-fg-2`.
- **Hairline top border** (`var(--l-line)`) separates it from the final CTA.
- At ≤540px the columns stack: brand row first, then a 2-up `NAVIGATION` + `SOCIALS` row.

CSS: `.l-footer`, `.l-footer-inner`, `.l-footer-cols`, `.l-footer-col-head`, `.l-footer-link`.

## Background fx

Three layers behind everything:

1. **`.l-orb-1` and `.l-orb-2`** — two large blurred radial gradients positioned absolutely at opposite corners. Each is a fixed-size element with `background: radial-gradient(circle, rgba(48, 100, 255, 0.18), transparent 65%)`, `filter: blur(100px)`, and a slow infinite-loop drift animation. They give the deep black some atmosphere without competing with content.
2. **`.l-grain`** — a fixed-position SVG noise PNG at low opacity (`mix-blend-mode: overlay; opacity: 0.05`). Adds film-grain texture so large flat areas don't band on OLED displays.
3. **`.l-shell`** itself — `background: #04060b` (basically the workspace's `--bg-page` value). The orbs and grain layer over this base.

CSS: `.l-shell`, `.l-orb`, `.l-orb-1`, `.l-orb-2`, `.l-grain`.

## Scroll behavior

- **Smooth anchor scrolling.** `html { scroll-behavior: smooth; }` is set globally (workspace inherits it too). Topbar nav `#workbench` and `#bento` jumps animate.
- **Scroll padding.** The `<main class="l-main">` element sets `scroll-padding-top: 92px;` so anchor-jumped sections don't slide under the sticky topbar.
- **Workbench sticky offset.** The workbench visual column pins at `top: 92px` to clear the topbar exactly.
- **Reduced-motion.** Animations honour `prefers-reduced-motion: reduce` — orbs stop drifting, hero fade-up runs at near-zero duration, carousel scroll-snap stays.

## Buttons (`.l-btn` + variants)

The whole landing page uses one button system. Variants are stacked via classes:

- `.l-btn` — base. `display: inline-flex; align-items: center; gap: 10px; height: 44px; padding: 0 18px; border-radius: 999px; font-weight: 500; font-size: 14px; transition: all 240ms var(--l-ease);`.
- `.l-btn-primary` — accent fill. `background: var(--accent-strong); color: white;` with a `0 0 0 4px rgba(48,100,255,0.18)` glow on hover.
- `.l-btn-ghost` — outlined. `background: rgba(255, 255, 255, 0.04); border: 1px solid var(--l-line-strong); color: var(--l-fg);`.
- `.l-btn-quiet` — minimal. No background, just `color: var(--l-fg-2)` with `:hover { color: var(--l-fg) }`.
- `.l-btn-sm` — `height: 36px; padding: 0 14px; font-size: 13px;`.
- `.l-btn-lg` — `height: 52px; padding: 0 22px; font-size: 15px;` — used on the hero CTAs.

A `.l-glyph` slot sits inside `.l-btn` for inline SVG icons (Google glyph, GitHub glyph). All buttons are pill-radius (`999px`).

## Eyebrows (page-level)

Class `.l-eyebrow` — the small badge-style chip that opens the hero ("◉ AI-POWERED APPLICATION WORKBENCH"). Differs from in-mock eyebrows:

```
display: inline-flex; align-items: center; gap: 8px;
padding: 6px 12px;
background: rgba(48, 100, 255, 0.12);
border: 1px solid rgba(48, 100, 255, 0.32);
border-radius: 999px;
font-family: var(--font-geist-mono), monospace;
font-size: 10.5px; letter-spacing: 0.12em; text-transform: uppercase;
color: #cfddff;
```

The leading `.l-eyebrow-dot` is a 6×6 accent-colored circle.

For section-level eyebrows above section titles (`FOUR STEPS · ONE FLOW`, `BUILT INTO THE WORKBENCH`), use plain mono uppercase text, `var(--l-fg-3)` color, 11px / `0.10em` tracking — no chip background. See `.l-section-head` and `.l-section-title`.

## Mobile (single 900px breakpoint, then 540px)

- **900px:** workbench grid collapses to single column, visual unsticks (`position: relative; height: auto`); bento tile padding tightens.
- **540px:** topbar inner padding tightens (`12px 18px`), nav gap drops to 4px, hero title clamps to `clamp(36px, 11vw, 48px)`, hero CTAs go full-width vertical stack, footer collapses to a single brand block above a 2-up nav/socials row.
- All sections honor `padding-left: 18px; padding-right: 18px;` at the smallest breakpoint.

## Tokens used here

| Token | Value | Used for |
|---|---|---|
| `--l-fg` / `--l-fg-2` / `--l-fg-3` | `#f5f8ff` / `#c7cfdf` / `#8a93a8` | Brand · nav links · footer column heads |
| `--l-line` / `--l-line-strong` | `rgba(255,255,255,0.06)` / `0.10` | Hairline borders + ghost button outlines |
| `--accent-strong` | `#4171ff` | Primary buttons + eyebrow chip border |
| `--font-geist-mono` | Geist Mono | Eyebrow chip + footer column heads |
| `--l-ease` / `--l-duration` | `cubic-bezier(0.16,1,0.30,1)` / `320ms` | Button hover, link hover, orb drift |
