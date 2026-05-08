# Hero

The opening composition above the fold. Maps to `LandingHero({ status, isSignedIn, … })` in `landing-page.tsx`.

## Layout

```
                                                                 
                  ◉ AI-POWERED APPLICATION WORKBENCH              
                                                                 
              Tailor every job application                       
                        with an                                  
                    AI workbench    ← gradient + glow            
                                                                 
   Upload your resume, find a role you actually want, review     
   the job description, and walk away with a tailored resume     
   and cover letter.                                              
                                                                 
   [G  Enter workspace]    [⌹  View on GitHub]                  
                                                                 
   • Smart resume reader · 12k+ live jobs · Tailored Word + PDF · 
                            Built-in AI assistant                 
                                                                 
   ┌──────────────────────────────────────────────────────────┐  
   │                                                          │  
   │   ← real workspace screenshot (1200×827, priority)        │  
   │     Job Search view with results + saved-jobs drawer      │  
   │                                                          │  
   └──────────────────────────────────────────────────────────┘  
```

Everything is centered horizontally at desktop. The whole hero is one vertical stack inside `.l-hero > .l-hero-stack`. Spacing between blocks is `gap: 24–32px` depending on size.

## Eyebrow chip

```jsx
<div className="l-eyebrow">
  <span className="l-eyebrow-dot" aria-hidden />
  AI-POWERED APPLICATION WORKBENCH
</div>
```

Pill-shaped badge. See `chrome.md` for the full token. Sits at the very top of the hero, above the title.

## Title

Three lines, each on its own `<span>` for explicit line breaks:

```jsx
<h1 className="l-hero-title">
  <span>Tailor every job application</span>
  <span>with an</span>
  <span className="l-hero-title-accent">AI workbench</span>
</h1>
```

- **`.l-hero-title`** — `font-family: var(--font-space-grotesk); font-size: clamp(48px, 7vw, 88px); font-weight: 600; line-height: 1.05; letter-spacing: -0.025em; color: var(--l-fg);`
- **Each `<span>` is `display: block;`** so each line stacks.
- **`.l-hero-title-accent`** is the third line. It applies a soft blue gradient + glow:
  ```css
  background: linear-gradient(180deg, #c5d8ff 0%, #4171ff 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  text-shadow: 0 8px 40px rgba(48, 100, 255, 0.18);
  ```

The title is wrapped in `.l-fade-up` so it animates `lFadeUp` (translateY 12 → 0 + opacity 0 → 1) on mount with a small delay.

## Subtitle

```jsx
<p className="l-hero-sub">
  Upload your resume, find a role you actually want, review the job
  description, and walk away with a tailored resume and cover letter.
</p>
```

`font-size: clamp(15px, 1.25vw, 17px); color: var(--l-fg-2); max-width: 640px; line-height: 1.5;`. Two-line natural break at desktop.

## CTA pair

Two buttons side by side. The primary CTA is **dynamic per auth status**:

| `status` | `isSignedIn` | Primary CTA renders |
|---|---|---|
| `loading` | — | `Restoring session…` (disabled, primary style) |
| `ready` | `true` | `Enter workspace` (primary, `onClick={() => router.push('/workspace')}`) |
| `ready` | `false` | `Sign in with Google` (primary, with Google glyph; `onClick={() => handleSignIn()}`) |
| `error` | — | `Sign in with Google` + an inline error notice below the button row |

The secondary CTA is always **`View on GitHub`** with an inline GitHub glyph (`<GitHubGlyph />`) — opens the repo in a new tab.

```jsx
<div className="l-hero-actions">
  <button className="l-btn l-btn-primary l-btn-lg" onClick={handlePrimaryCta} disabled={status === 'loading'}>
    {primaryGlyph} {primaryLabel}
  </button>
  <a className="l-btn l-btn-ghost l-btn-lg" href={GITHUB_URL} target="_blank" rel="noreferrer">
    <GitHubGlyph /> View on GitHub
  </a>
</div>
```

CSS: `.l-hero-actions` → `display: flex; gap: 12px; justify-content: center;`. At ≤540px the actions go vertical (each button full-width).

## Feature pills

A single mono row of four short value-prop pills underneath the CTAs.

```
• Smart resume reader · 12k+ live jobs · Tailored Word + PDF · Built-in AI assistant
```

Implemented as a flex row of `<span>`s with bullet separators.

```jsx
<div className="l-hero-pills">
  <span>• Smart resume reader</span>
  <span>• 12k+ live jobs</span>
  <span>• Tailored Word + PDF</span>
  <span>• Built-in AI assistant</span>
</div>
```

CSS: `.l-hero-pills` → `display: flex; flex-wrap: wrap; justify-content: center; gap: 6px 18px; font-size: 12.5px; color: var(--l-fg-3); font-family: var(--font-geist-mono); letter-spacing: 0.04em;`. Each `•` is part of the text content (kept simple — no pseudo-element).

## Hero artifact (real workspace screenshot)

The single most important visual on the page — sells the product in a glance.

```jsx
<div className="l-hero-visual">
  <div className="l-artifact-glow" aria-hidden />
  <Image
    src="/landing/hero-workspace.png"
    alt="Job Application Copilot workspace — Job Search view"
    width={1200}
    height={827}
    className="l-artifact-image"
    priority
    sizes="(max-width: 900px) 100vw, 1200px"
  />
</div>
```

- `frontend/public/landing/hero-workspace.png` — 1200×827 PNG screenshot of the **Job Search view** with results + the saved-jobs drawer expanded. It's the most data-rich workspace tab and reads as "live product."
- **`priority`** to make it part of the LCP. Explicit `width`/`height` so the layout reserves space (no CLS).
- **`.l-artifact-glow`** is a soft blue radial gradient positioned absolutely behind the image — gives the screenshot a subtle "lifted" feel.
- **`.l-artifact-image`** rounds the corners (`border-radius: var(--l-radius-lg)`) and adds a thin border (`var(--l-line)`) plus a deep box-shadow so the screenshot reads as a card cut out of the page.

A streaming caret element (`.l-artifact-caret`) was inside an earlier version when the hero used a CSS-built mock. The class is kept in `globals.css` for potential reuse but the current hero doesn't render one.

## Shipped behavior

- [x] Title + subtitle fade-up on mount via `.l-fade-up` + `lFadeUp` keyframe (320ms, eased).
- [x] Primary CTA disables and reads `Restoring session…` until the auth hook settles.
- [x] Sign-in failure surfaces an inline `.l-notice .l-notice-warning` below the action row.
- [x] Hero image is `priority` — first paint includes it.
- [x] At ≤900px the title clamp shrinks; at ≤540px buttons stack vertically full-width.

## Tokens used here

| Token | Value | Used for |
|---|---|---|
| `--font-space-grotesk` | Space Grotesk | Hero title (all three lines) |
| `--font-geist-mono` | Geist Mono | Eyebrow chip + feature pills |
| `--accent-strong` | `#4171ff` | Title accent gradient end + primary CTA |
| `--l-fg` / `--l-fg-2` / `--l-fg-3` | `#f5f8ff / #c7cfdf / #8a93a8` | Title · subtitle · pills |
| `--l-line` | `rgba(255,255,255,0.06)` | Artifact image border |
| `--l-radius-lg` | `20px` | Artifact image radius |
| `--l-ease` / `--l-duration` | `cubic-bezier(0.16,1,0.30,1)` / `320ms` | Fade-up + button transitions |

## Variations to consider when redesigning

If a sibling marketing page reuses this hero pattern:

- **Keep the three-line title shape** (two body lines + one accent line). It anchors the page even before the user reads it.
- **Keep the artifact below the fold-of-fold.** The CTAs sit between the headline and the screenshot so the user always reads the value prop first; the screenshot rewards them after they've decided to scroll.
- **Replace the workspace screenshot with whatever the new product's most-data-rich page is.** Don't fall back to a CSS mock — a real screenshot beats a faux one even if it's slightly imperfect.
- **Don't add a third CTA.** The primary + GitHub pair is intentionally constrained. A third CTA dilutes the conversion path.
