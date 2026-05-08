# Workbench — Sticky-Scroll Narrative + Four Mocks

The product-story section. Section ID `#workbench`. Maps to `WorkbenchSection()` in `landing-page.tsx` plus the four `WorkbenchVisual{0..3}` mock components.

## Layout

```
                  FOUR STEPS · ONE FLOW
       From a fresh resume to job ready application
─────────────────────────────────────────────────────────

┌────────────────────┐  ┌─ Step block 01 (48vh, centered) ─┐
│                    │  │ 01 · RESUME                       │
│  ┌──────────────┐  │  │ Drop a resume or chat one into    │
│  │              │  │  │ existence                          │
│  │   Visual     │  │  │ Upload a PDF, Word doc, or text…  │
│  │   stage      │  │  │ ┌─────────────────────────────┐   │
│  │   480 × 480  │  │  │ │ aside / quote                │   │
│  │              │  │  │ └─────────────────────────────┘   │
│  │   (centered  │  │  └────────────────────────────────────┘
│  │    pinned    │  ┌─ Step block 02 (48vh, centered) ─┐
│  │    at        │  │ 02 · JOB SEARCH                   │
│  │    viewport  │  │ Search 12,000+ open roles in one  │
│  │    middle)   │  │ place                              │
│  │              │  │ Live listings from Greenhouse, …  │
│  └──────────────┘  └────────────────────────────────────┘
│   01·02·03·04     ┌─ Step block 03 (48vh, centered) ─┐
│   rail dots       │ 03 · JOB DETAIL                   │
│                    │ See exactly what each role is …  │
└────────────────────┘ ...
                       ┌─ Step block 04 (48vh, centered) ─┐
                       │ 04 · ANALYSIS                     │
                       │ Get a tailored resume and cover  │
                       │ letter                            │
                       └────────────────────────────────────┘
```

The section is a 2-column CSS grid (`.l-workbench-grid`) with equal-width columns and a 80px gap. The left column is the sticky visual; the right column is four scrollable step blocks stacked vertically.

## Section head

```jsx
<div className="l-section-head">
  <span className="l-section-eyebrow">FOUR STEPS · ONE FLOW</span>
  <h2 className="l-section-title">From a fresh resume to job ready application</h2>
</div>
```

- **`.l-section-eyebrow`** — mono uppercase, `var(--l-fg-3)`, 11px, tracking `0.10em`.
- **`.l-section-title`** — Space Grotesk, `clamp(28px, 4vw, 48px)`, weight 600, letter-spacing `-0.02em`, centered.

Padding-bottom on `.l-section-head` is tight (`24px`) so the section title sits close to the first step's text.

## Sticky visual column

```jsx
<div className="l-workbench-visual" aria-hidden>
  <div className="l-workbench-visual-stage">
    {WORKBENCH_VISUALS.map((Visual, i) => (
      <Visual key={i} active={i === activeIndex} />
    ))}
  </div>
  <div className="l-workbench-rail">
    {[0,1,2,3].map(i => (
      <button className={`l-workbench-rail-step ${i === activeIndex ? "is-active" : ""}`} … >
        <span className="l-workbench-rail-num">0{i+1}</span>
      </button>
    ))}
  </div>
</div>
```

Key CSS:

```css
.l-workbench-visual {
  position: sticky;
  top: 92px;                       /* clears the topbar */
  height: calc(100vh - 200px);     /* shorter than viewport so the
                                      centered stage sits ~80px above
                                      viewport-center, aligning with
                                      the centered step text */
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 24px;
}
.l-workbench-visual-stage {
  position: relative;              /* mocks are absolute children */
  width: 100%;
  max-width: 480px;
  flex: 0 0 auto;
  aspect-ratio: 1 / 1;             /* square 480×480 */
  max-height: calc(100vh - 200px); /* cap on short viewports */
  background: rgba(0, 0, 0, 0.40); /* matches workspace .b-jd-block */
  border: 1px solid var(--l-line-strong);
  border-radius: var(--l-radius-lg);
  overflow: hidden;
  box-shadow:
    0 1px 0 rgba(255, 255, 255, 0.04) inset,
    0 24px 60px rgba(0, 0, 0, 0.55);
}
```

**Why these values:**
- **`top: 92px`** matches the topbar height so the sticky visual lands directly under the topbar's hairline.
- **`height: calc(100vh - 200px)`** is intentionally shorter than `100vh - 92px`. Combined with `justify-content: center`, the sticky container's vertical center sits ~50px above viewport-center, aligning with the centered step text.
- **`aspect-ratio: 1/1`** with `max-width: 480px` gives a 480×480 square stage. Earlier versions stretched the stage to fill the sticky container (480×853), which left ~400px of dead dark space inside since mock content is fixed-size.
- **`overflow: hidden`** clips the absolutely-positioned mocks.

## Step blocks

```jsx
{WORKBENCH_STEPS.map((step, i) => (
  <div
    ref={el => stepRefs.current[i] = el}
    className={`l-workbench-step ${i === activeIndex ? "is-active" : ""}`}
  >
    <span className="l-workbench-eyebrow">{step.eyebrow}</span>
    <h3 className="l-workbench-title">{step.title}</h3>
    <p className="l-workbench-body">{step.body}</p>
    <p className="l-workbench-aside">{step.aside}</p>
  </div>
))}
```

Key CSS:

```css
.l-workbench-step {
  min-height: 48vh;
  display: flex;
  flex-direction: column;
  justify-content: center;          /* center text in the 48vh block —
                                       aligns with the centered visual */
  gap: 18px;
  padding: 8px 0 32px;
  opacity: 0.45;
  transition: opacity 360ms var(--l-ease);
}
.l-workbench-step.is-active { opacity: 1; }
```

**Why 48vh?** Tall enough to give the IntersectionObserver scroll distance to fire one step at a time (no two simultaneously inside the middle band), short enough that the user doesn't feel they're scrolling forever.

**Why `justify-content: center`?** With `flex-start` (the previous setting), step 01's text sat at the very top of the column on first scroll-in while the centered visual floated at viewport-middle — they read as off-axis. Centering pushes step 01's text down to mid-block, much closer to the visual's center.

The four step contents are defined once in a `WORKBENCH_STEPS` array:

```ts
const WORKBENCH_STEPS = [
  {
    eyebrow: "01 · RESUME",
    title: "Drop a resume or chat one into existence",
    body:  "Upload a PDF, Word doc, or text file and our AI pulls out everything that matters — your skills, experience, projects, publications. The layout adapts to your career stage so students lead with education and seniors lead with experience.",
    aside: "No resume yet? Chat with our AI builder — one question at a time, change your answers whenever you need, and your draft saves automatically for a week.",
  },
  // ... three more
] as const;
```

## Active-state detection (IntersectionObserver)

```ts
useEffect(() => {
  const observer = new IntersectionObserver(
    entries => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          const idx = stepRefs.current.indexOf(entry.target as HTMLDivElement);
          if (idx !== -1) setActiveIndex(idx);
        }
      }
    },
    { rootMargin: "-50% 0px -50% 0px", threshold: 0 }
  );
  for (const el of stepRefs.current) if (el) observer.observe(el);
  return () => observer.disconnect();
}, []);
```

**The math:**
- `rootMargin: -50% 0px -50% 0px` shrinks the IO root rect to a 0-height line at viewport-center.
- `threshold: 0` fires when ANY part of the step's bounding box crosses that line.
- Net effect: a step is "active" the moment its top edge crosses viewport-middle (going up via scroll).

Earlier versions used `rootMargin: -40% 0px -40% 0px` + `threshold: 0.45`. With 56vh blocks that was unsatisfiable (a 56vh block can't be 45% inside a 20vh band) so the observer never fired. Switching to a 0-height line + threshold 0 is robust regardless of block height.

## Rail dots

```css
.l-workbench-rail {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px;
  background: rgba(0, 0, 0, 0.3);
  border: 1px solid var(--l-line);
  border-radius: 999px;
}
.l-workbench-rail-step {
  width: 36px; height: 28px;
  background: transparent;
  border-radius: 999px;
  color: var(--l-fg-3);
  font-family: var(--font-geist-mono);
  font-size: 11px;
  cursor: pointer;
}
.l-workbench-rail-step:hover { background: rgba(255, 255, 255, 0.04); color: var(--l-fg); }
.l-workbench-rail-step.is-active {
  background: rgba(48, 100, 255, 0.20);
  color: var(--l-fg);
}
```

Each rail step has an `onClick` that scrolls the corresponding step block into view. The rail sits below the visual stage, separated by a 24px gap.

---

## The four mock cards

All four are siblings inside `.l-workbench-visual-stage`, absolutely positioned with `inset: 0`. Only one has `is-active` (opacity 1); the rest are at opacity 0 with a 360ms crossfade.

```css
.l-workbench-mock {
  position: absolute;
  inset: 0;
  padding: 26px;
  display: flex;
  flex-direction: column;
  justify-content: center;          /* center mock content vertically */
  gap: 14px;
  opacity: 0;
  transform: translateY(8px);
  transition: opacity 360ms var(--l-ease), transform 360ms var(--l-ease);
  pointer-events: none;
}
.l-workbench-mock.is-active {
  opacity: 1;
  transform: translateY(0);
}
```

Each mock pulls recognizable elements from the **actual workspace page** for that step. The goal is "tiny preview of the page the user will land on," not generic data card.

### Mock 1 — Resume (mirrors `ResumeIntake` parsed-profile hero)

```
STEP 01 · RESUME                                        ← .l-mock-eyebrow
[ resume_v3.pdf  · PARSED ]                             ← .l-mock-file-pill (filename pill + green tag)

Aria Patel                                              ← .l-mock-hero-name (large)
Staff ML Engineer · San Francisco                       ← .l-mock-hero-meta

┌─ 12 ─┐  ┌─ 27 ─┐  ┌─ 9 ─┐                             ← .l-mock-stats (3-up grid)
│ ROLES│  │SKILLS│  │YEARS │
└──────┘  └──────┘  └──────┘

SKILLS DETECTED                                          ← .l-mock-skills-head
[Python] [PyTorch] [CUDA] [Triton] [+12 more]            ← .l-mock-skills (chip cluster)
```

Classes:
- `.l-mock-file-pill`, `.l-mock-file-name` (mono), `.l-mock-file-tag` (green badge — `rgba(127, 224, 176, 0.16)` background, `#9be8c0` text)
- `.l-mock-hero`, `.l-mock-hero-name` (Space Grotesk 20px / 600), `.l-mock-hero-meta` (12.5px, fg-3)
- `.l-mock-stats` (3-up CSS grid), `.l-mock-stat`, `.l-mock-stat-num` (Space Grotesk 20px), `.l-mock-stat-label` (mono uppercase)
- `.l-mock-skills-block`, `.l-mock-skills-head`, `.l-mock-skills`, `.l-mock-chip`, `.l-mock-chip-hard`

### Mock 2 — Job Search (mirrors `JobSearch`)

```
STEP 02 · JOB SEARCH

⌕  machine learning engineer        |  Remote                ← .l-mock-search-bar with .l-mock-search-divider + .l-mock-search-loc

[Source · 2] [Mode · Remote] [Posted · 7d] [Sort · Best]    ← .l-mock-filters (.l-mock-filter)

47 MATCHES · BY RELEVANCE                                    ← .l-mock-matches-head

┌─────────────────────────────────────────┐
│ ★ TOP MATCH                             │ ← .l-mock-result.l-mock-result-top (blue-tinted border)
│ Senior ML Engineer                      │   .l-mock-result-badge ★ TOP MATCH chip
│ Stripe · greenhouse · Remote            │
└─────────────────────────────────────────┘
┌─────────────────────────────────────────┐
│ ML Engineer, Inference                  │ ← .l-mock-result (regular)
│ Pinterest · greenhouse                  │
└─────────────────────────────────────────┘
┌─────────────────────────────────────────┐
│ Founding ML Engineer                    │
│ Notion · ashby                          │
└─────────────────────────────────────────┘
```

Classes:
- `.l-mock-search-bar`, `.l-mock-search-icon`, `.l-mock-search-text` (flex 1 to fill), `.l-mock-search-divider` (1px vertical line), `.l-mock-search-loc`
- `.l-mock-filters` (flex wrap), `.l-mock-filter` (rounded chip)
- `.l-mock-matches-head` (mono uppercase, 10px tracked)
- `.l-mock-results`, `.l-mock-result`, `.l-mock-result-top` (blue-tinted border + soft glow), `.l-mock-result-badge` (mono "★ TOP MATCH" pill in accent-tint)
- `.l-mock-result-title`, `.l-mock-result-meta`

### Mock 3 — JD Detail (mirrors `JDReview`)

```
STEP 03 · JOB DETAIL
Senior ML Engineer, Inference                                ← .l-mock-jd-title (Space Grotesk 18px)
Anthropic · San Francisco · Hybrid                           ← .l-mock-jd-sub

┌─ 87% ──┐  ┌─ 12 ─────┐  ┌─ 5+ ────┐                        ← .l-mock-metrics (3-up grid)
│ MATCH  │  │ HARD     │  │ YEARS   │   the leftmost tile
│ SCORE  │  │ SKILLS   │  │ REQ     │   uses .l-mock-metric-accent
└────────┘  └──────────┘  └─────────┘    (blue-tinted bg + #cfddff number)

HARD SKILLS · 5 OF 12
[Python] [CUDA] [Triton] [Distributed] [Postgres]            ← .l-mock-chip-hard

SOFT SKILLS
[Mentorship] [Cross-functional] [Pragmatic]                  ← .l-mock-chip-soft (blue-tinted)
```

Classes:
- `.l-mock-jd-title` (Space Grotesk 18px / 600), `.l-mock-jd-sub`
- `.l-mock-metrics` (3-up grid), `.l-mock-metric`, `.l-mock-metric-accent` (blue background tint), `.l-mock-metric-num` (Space Grotesk 24px), `.l-mock-metric-unit` (smaller % suffix), `.l-mock-metric-label` (mono uppercase)
- `.l-mock-chip-hard` (white-tinted bg), `.l-mock-chip-soft` (blue-tinted bg + border + `#cfddff` text)

### Mock 4 — Analysis (mirrors `AnalysisRunner` agent pipeline)

```
STEP 04 · ANALYSIS

┌─ ✓  Matchmaker             100% ─┐                        ← .l-mock-stage.l-mock-stage-done
│    Scored role fit                │
└──────────────────────────────────┘
┌─ ✓  Forge agent            100% ─┐
│    Drafted tailored resume        │
└──────────────────────────────────┘
┌─ ●  Gatekeeper              62% ─┐                        ← .l-mock-stage.l-mock-stage-running
│    Reviewing outputs…              │   accent bg + border, pulsing dot
│    ▓▓▓▓▓▓▓▓░░░░░░░░░░               │   .l-mock-stage-bar with .l-mock-stage-fill (62% width)
└──────────────────────────────────┘
┌─ ○  Cover letter agent  standby ─┐                        ← .l-mock-stage.l-mock-stage-pending (opacity 0.55)
└──────────────────────────────────┘
```

Classes:
- `.l-mock-pipeline` (flex column with 8px gap)
- `.l-mock-stage` — base card (`rgba(0,0,0,0.40)` + thin border + 8px radius)
- `.l-mock-stage-running` — accent-tint background + accent border
- `.l-mock-stage-pending` — `opacity: 0.55`
- `.l-mock-stage-dot` — 16×16 round status indicator. `-done` is green-tinted with a `✓`; `-running` is solid accent with a pulsing box-shadow ring (animation: `lPulse 1400ms infinite` — **note: lPulse keyframe is currently undefined; tracked as a known bug**). Default (`pending`) is hollow.
- `.l-mock-stage-body` (flex column), `.l-mock-stage-row` (title + percent right-aligned via `justify-content: space-between`)
- `.l-mock-stage-title` (13px, weight 500), `.l-mock-stage-pct` (mono 10.5px, fg-3 default, `#cfddff` for running)
- `.l-mock-stage-detail` (11.5px, fg-3)
- `.l-mock-stage-bar` (4px tall, rounded), `.l-mock-stage-fill` (62% width, accent-strong fill)

Real workspace stage names (from `AnalysisRunner.tsx`): Matchmaker · Forge agent · Gatekeeper · Workflow crew · Builder · Cover letter agent. The mock picks 4 of these to keep the card readable.

---

## Behavior preservation

- [x] IntersectionObserver tracks all four step blocks; sets `activeIndex` state in `WorkbenchSection`.
- [x] `activeIndex` drives `is-active` on the matching step block, mock card, and rail dot — three reflections of one source of truth.
- [x] Rail dot click → `stepRefs.current[i]?.scrollIntoView({ behavior: 'smooth', block: 'center' })`.
- [x] Crossfade between mocks runs for 360ms with a small upward translate so the new card appears to settle.
- [x] Section honors `prefers-reduced-motion: reduce` — opacity transitions still fire, transform changes are suppressed.
- [x] Mobile (≤900px): grid collapses to single column; visual unsticks (`position: relative; height: auto`); each step block becomes natural-height instead of 48vh.

## Tokens used here

| Token | Value | Used for |
|---|---|---|
| `--font-space-grotesk` | Space Grotesk | Section title, mock hero name, JD title, metric numbers |
| `--font-geist-mono` | Geist Mono | Eyebrows, file names, labels, percent values |
| `--accent-strong` | `#4171ff` | Active rail step bg-tint, running stage card, top-match badge |
| `--l-card` / `--l-line-strong` | `#06080d` / `rgba(255,255,255,0.10)` | Rail bg + visual stage border |
| `--l-radius-lg` / `--l-radius` / `--l-radius-sm` | `20 / 14 / 10px` | Stage / mock cards / chips |
| `--l-ease` | `cubic-bezier(0.16, 1, 0.30, 1)` | All transitions |

## Variations to consider when redesigning

- **Step count.** Four was chosen because the product has four steps. Three would also work — the IO logic is step-count-agnostic. Five+ starts to feel long given each step is 48vh.
- **Visual aspect ratio.** 1/1 (square) was the sweet spot for our mock content. If the new mocks have more vertical content, 4/5 (taller) is fine — just ensure `justify-content: center` on the mock element so any slack splits evenly.
- **Pin strategy.** Center-pin (current) keeps the visual at viewport-middle the whole way down. Top-pin works too but step 04's text falls below the visual at the end unless the visual is extended to match the column height — which leaves dead space inside the visual.
- **Mock fidelity.** The wins here came from mirroring the actual workspace pages, not from prettier abstract diagrams. If the new product surface has identifiable hero elements (like our parsed-profile hero or the metric tiles), pick those.
