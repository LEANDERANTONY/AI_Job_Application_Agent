# Landing Page Design System (shipped)

The marketing landing page for Job Application Copilot. Sits at `/` on the production host and acts as the entry point to the workspace at `/workspace`. It tells the four-step product story and routes the user into the workspace through Google SSO.

This package is a **design-system reference** — a context bundle for future design passes (Claude Design, Figma redesigns, sibling marketing surfaces). It is the landing-page equivalent of the workspace handoff that lives next door at `redesign/handoff/`.

> **Source of truth:** the shipped CSS lives in `frontend/src/app/globals.css` (scoped under `.l-shell`) and the React component is `frontend/src/components/landing-page.tsx`. When this doc and the shipped code disagree, the shipped code wins.

---

## 1 · What's in this folder

```
landing/
├── README.md           ← you are here
└── specs/
    ├── chrome.md       ← topbar, footer, background fx, scroll behaviors
    ├── hero.md         ← hero stack: headline, CTAs, feature pills, screenshot
    ├── workbench.md    ← sticky-scroll narrative + the four mock cards
    ├── bento.md        ← single-tile "Everything else" carousel
    └── final-cta.md    ← Ready-to-tailor band before the footer
```

The landing page didn't go through an A/B/C prototype phase like the workspace did — it was built directly against the shipped code. So there is no `prototype/` subfolder here.

---

## 2 · Mapping to shipped code

The whole landing page is one component file plus its slice of `globals.css`.

```
frontend/src/components/
├── landing-page.tsx        — Topbar + LandingHero + WorkbenchSection +
│                             BentoSection + FinalCtaSection + LandingFooter
│                             + the four WorkbenchVisual{0..3} mock cards
└── icons.tsx               — shared inline SVG icons (BrandLogo etc.)

frontend/src/app/page.tsx   — hosts <LandingPage /> at the root route
frontend/src/app/globals.css
                            — `.l-shell` token block + all `.l-*` styles
                              (lines ~2900–4250 in the shipped file)
```

Auth state is pulled from the same `useWorkspaceSession` hook the workspace uses. The hero CTA flips between **"Enter workspace"** (signed in) and **"Restoring session…" → "Sign in with Google"** (signed out / loading) based on that hook's status.

**Section ID anchors (used by the topbar nav):**
- `#workbench` — the sticky-scroll section
- `#bento` — the carousel section

---

## 3 · The five sections, top to bottom

```
┌─ Topbar (fixed, hairline bottom) ────────────────────────────┐
│ [● Job Application Copilot]    Workflow · Features · [Auth] │
└──────────────────────────────────────────────────────────────┘

┌─ Hero (centered, dark with two animated orbs behind) ────────┐
│              ◉ AI-POWERED APPLICATION WORKBENCH              │
│        Tailor every job application                           │
│                  with an                                      │
│              AI workbench    ← gradient                       │
│   Upload your resume, find a role you actually want, …        │
│   [G  Enter workspace]   [⌹ View on GitHub]                  │
│   • Smart resume reader · 12k+ live jobs · Tailored Word + …  │
│   ┌──────────────────────────────────────────────────────┐    │
│   │  ← real workspace screenshot (1200×827, priority)     │    │
│   └──────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────┘

┌─ Workbench (sticky-scroll narrative, 2-col grid) ────────────┐
│                  FOUR STEPS · ONE FLOW                        │
│         From a fresh resume to job ready application          │
│                                                              │
│ ┌────────────┐    01 · RESUME                                │
│ │ Sticky     │    Drop a resume or chat one into existence  │
│ │ visual     │    Upload a PDF, Word doc, or text file …    │
│ │ (480×480)  │                                              │
│ │ centered   │    02 · JOB SEARCH                           │
│ │ pinned at  │    Search 12,000+ open roles in one place    │
│ │ ~viewport  │    …                                         │
│ │ middle     │                                              │
│ │ + 4 mocks  │    03 · JOB DETAIL                           │
│ │ crossfade  │    See exactly what each role is asking for  │
│ │ as user    │                                              │
│ │ scrolls    │    04 · ANALYSIS                             │
│ └────────────┘    Get a tailored resume and cover letter    │
│       01·02·03·04 rail dots                                  │
└──────────────────────────────────────────────────────────────┘

┌─ Bento (single-tile carousel) ───────────────────────────────┐
│              BUILT INTO THE WORKBENCH                         │
│         Everything else worth knowing about                  │
│   ┌─────────────────────────────────────────────────────┐    │
│   │  12,000+ OPEN JOBS                                  │    │
│   │  Greenhouse · Lever · Ashby · Workday               │    │
│   │  Live listings from 130+ companies …                │    │
│   │  [greenhouse] [lever] [ashby] [workday]             │    │
│   └─────────────────────────────────────────────────────┘    │
│              ←  ●·○·○·○  →                                   │
└──────────────────────────────────────────────────────────────┘

┌─ Final CTA ──────────────────────────────────────────────────┐
│              Ready to tailor?                                │
│              [G  Enter workspace]                            │
└──────────────────────────────────────────────────────────────┘

┌─ Footer ─────────────────────────────────────────────────────┐
│ Job Application Copilot         NAVIGATION       SOCIALS     │
│ A focused workspace for …       Privacy Policy   GitHub      │
│ Built by Leander Antony A                        LinkedIn    │
└──────────────────────────────────────────────────────────────┘
```

Each section has its own spec — see `specs/`.

---

## 4 · Design tokens (shipped values)

All landing tokens are scoped under `.l-shell` so they don't leak into the workspace's `.b-shell`. The two surfaces deliberately share **only** the type stack and the accent color — everything else (cards, lines, ink) is local to each.

| Group | Token | Shipped value | Used for |
|---|---|---|---|
| Surface | `--l-card` | `#06080d` | Default card / panel surface (near-pure-black) |
| | `--l-card-strong` | `#04060b` | Even darker surface for stage cutouts |
| Borders | `--l-line` | `rgba(255, 255, 255, 0.06)` | Default card / divider hairlines |
| | `--l-line-strong` | `rgba(255, 255, 255, 0.10)` | Hovered / active card outlines |
| Ink | `--l-fg` | `#f5f8ff` | Body text |
| | `--l-fg-2` | `#c7cfdf` | Secondary text |
| | `--l-fg-3` | `#8a93a8` | Eyebrows, captions, metadata |
| | `--l-fg-4` | `#5e6677` | Disabled / pending pipeline rows |
| Radius | `--l-radius-sm / --l-radius / --l-radius-lg` | `10 / 14 / 20px` | Chips / cards / hero artifact + bento tiles |
| Motion | `--l-ease` | `cubic-bezier(0.16, 1, 0.30, 1)` | All landing transitions (matches workspace `--ease-out`) |
| | `--l-duration` | `320ms` | Default landing transition duration |

**Inherited from the global `:root`** (shared with the workspace, not redefined under `.l-shell`):

| Token | Value | Used for |
|---|---|---|
| `--accent-strong` | `#4171ff` (root) → `#5a86ff` (workspace override) | Primary CTA, gradient text, active rail step |
| `--font-space-grotesk` | Space Grotesk via `next/font/google` | Hero title, section titles, mock hero names, metric numbers |
| `--font-geist-mono` | Geist Mono via `next/font/google` | All eyebrows, file names, kbd-style labels, percent values |

The body font on the landing page falls through to the system stack inherited at the `html` level — there is no DM Sans on the landing page (that's a workspace-only choice).

---

## 5 · Visual rhythm rules

These are the conventions every landing surface follows. New sections should match.

- **Eyebrows are mono, uppercase, tracked.** `font-family: var(--font-geist-mono); font-size: ~10–11px; letter-spacing: 0.10–0.12em; text-transform: uppercase; color: var(--l-fg-3);`. Used at the start of every region (`AI-POWERED APPLICATION WORKBENCH`, `FOUR STEPS · ONE FLOW`, `BUILT INTO THE WORKBENCH`, plus `STEP NN · …` inside each mock card).
- **Cards are deep-black, not blue-tinted.** All card surfaces use `--l-card` (`#06080d`) or a `rgba(0, 0, 0, 0.40)` overlay over the page. The workspace's `.b-jd-block` treatment (flat dark + thin border) is the visual reference — all four workbench mocks and the bento tiles match it.
- **Accent is rare and load-bearing.** `--accent-strong` (`#4171ff`) appears in: the gradient on the third headline line, the hero "Enter workspace" button, the active workbench rail step, the workbench JD-mock match-score tile, the workbench analysis-mock running stage card + dot, and the bento carousel active dot. Nothing else uses it.
- **Background lighting is two animated orbs + a grain overlay.** `.l-orb-1` and `.l-orb-2` are blurred radial-gradient blobs that drift slowly behind everything; `.l-grain` is a fixed-position SVG noise PNG at low opacity. Both together prevent the deep black from feeling flat.
- **Sticky-scroll narrative for product steps.** The workbench section uses `position: sticky; top: 92px;` on the visual column and an IntersectionObserver with `rootMargin: -50% 0px -50% 0px` to pick the active step as each block crosses viewport-center.
- **Single-tile carousel for "everything else."** The bento section is `overflow-x: auto; scroll-snap-type: x mandatory` with each tile at `flex: 0 0 100%`. Prev/next arrows + dot indicators both drive a programmatic `scrollTo`; a debounced scroll listener keeps the active dot in sync with the user's swipe.
- **Hero artifact is a real workspace screenshot, not a CSS mock.** `frontend/public/landing/hero-workspace.png` (1200×827) is loaded via `next/image` with `priority` so it's part of the LCP.
- **Two breakpoints, that's it.** 900px collapses the workbench grid to a single column and the bento to a smaller tile; 540px tightens topbar / hero / footer paddings.

---

## 6 · Behavior preservation checklist

What the landing page actually does, beyond rendering:

### Auth flow
- [x] `useWorkspaceSession` runs on mount. Hero CTA shows `Restoring session…` (disabled) while `status === "loading"`.
- [x] Signed in → `Enter workspace` (router pushes `/workspace`).
- [x] Signed out → `Sign in with Google` (kicks `/api/auth/google/start` redirect).
- [x] Post-OAuth callback returns to `/`; the hook restores the session and the same CTA flips state without a hard reload.
- [x] Topbar shows a `Sign out` button when signed in (next to `Enter workspace`).

### Workbench scroll narrative
- [x] IntersectionObserver tracks the four `.l-workbench-step` blocks. The active index is mirrored to:
  - the active step's `is-active` class (drives opacity + emphasis),
  - the matching `WorkbenchVisual{N}` mock's `is-active` class (drives crossfade),
  - the matching rail dot's `is-active` class.
- [x] Clicking a rail dot scrolls the corresponding step into view (smooth scroll).
- [x] The visual stage is center-pinned via `position: sticky; top: 92px; height: calc(100vh - 200px); justify-content: center;` — its vertical center stays at roughly viewport-center as the user scrolls.

### Bento carousel
- [x] Trackpad / touch swipe scrolls the strip naturally; `scroll-snap` lands on tile boundaries.
- [x] Arrow buttons + dots both call `scrollToIndex(N)` which `scrollTo({ left: N * stripWidth, behavior: 'smooth' })`.
- [x] A scroll listener debounced via `requestAnimationFrame` derives the active index from `scrollLeft / clientWidth`. This keeps the dots correct when the user swipes instead of clicking.
- [x] Prev arrow disabled at index 0; next arrow disabled at the last tile.

### Hero artifact
- [x] `next/image` with `priority`, explicit width 1200 / height 827 to reserve space and avoid CLS. `sizes="(max-width: 900px) 100vw, 1200px"` so mobile gets the right buffer.

### Animations
- [x] `@keyframes lFadeUp` — initial fade-up on hero title + sub on mount (`.l-fade-up` class with stagger).
- [x] `@keyframes lBlink` — the streaming caret in the (now-removed) faux artifact preview; class kept (`.l-artifact-caret`) for potential reuse.
- [x] **`@keyframes lPulse` — referenced by `.l-mock-stage-dot-running` but currently undefined. Tracked as a known bug.**

---

## 7 · How to use this package as design-system input

When briefing a new design pass on a marketing surface (a sibling product's landing, a dedicated pricing page, a docs entry page):

1. **`README.md` §4 token table + §5 rhythm rules** — the visual contract in a page-and-a-half.
2. **`specs/chrome.md`** — the fixed page frame (topbar + footer + background fx + breakpoints).
3. **`specs/hero.md`** — the hero composition rules (headline structure, CTA pair, feature pills, artifact frame). The most copy-able pattern.
4. **`specs/workbench.md`** — if the new surface needs a sticky-scroll product-story narrative. Includes the IntersectionObserver math, sticky-pin formula, and the four mock-card layouts.
5. **`specs/bento.md`** — if the new surface needs a horizontal carousel.
6. **`specs/final-cta.md`** — the closing-band rhythm.

The shipped `.l-*` class names are the actual stable contract; reference `frontend/src/app/globals.css` for any specific style not covered here.

---

## 8 · Decisions resolved during the build

For posterity — the things this design landed on after iteration:

- **Single hero artifact, not a mosaic.** The earliest hero had a hand-built CSS faux workspace mock with 190+ lines of layout. We replaced it with one real screenshot of the Job Search view (with the saved-jobs drawer expanded). The screenshot is more honest about what the product looks like and dropped a lot of CSS surface area.
- **Center-pinned visual, not top-pinned.** Top-pinning the workbench visual made step 04's text fall below the visual at the end of the scroll. Center-pinning + a square (1/1) stage keeps the visual at viewport-middle the whole way down so step start/end alignment stops mattering.
- **Square 480×480 stage with content centered.** The stage previously stretched to fill the sticky container (480×853) which left ~400px of dead space inside each mock. Square stage with `justify-content: center` on the mock children balances any size variance between the four mocks.
- **Mock content mirrors the actual workspace pages.** Each of the four mocks pulls recognizable elements from `ResumeIntake`, `JobSearch`, `JDReview`, `AnalysisRunner` — the parsed-profile hero, the search results with Top Match badge, the three big metric tiles, the agent pipeline cards. Generic "Name / Role / Skills" form rows were replaced with the same hero+stats+chips pattern the workspace shows after parsing.
- **Bento dropped from 5 tiles to 4.** A "FAST SEARCH" tile was cut after it duplicated the hero's value prop; the remaining four ride one full-width stage each instead of a tighter 2×2 grid.
- **GitHub link consolidated to two surfaces.** Topbar nav had a third copy that was redundant with the hero CTA + footer link. Topbar is now `Workflow · Features · [Auth]` only.
- **All mock card surfaces match `.b-jd-block`'s flat dark treatment.** The workbench mocks and bento tiles previously had a subtle blue corner glow (`radial-gradient(rgba(48, 100, 255, 0.08), …)`); now they all use `rgba(0, 0, 0, 0.40)` so they read as the same surface family as the JD review block in the workspace.
