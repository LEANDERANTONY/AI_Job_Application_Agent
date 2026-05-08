# Final CTA — "Ready to tailor?"

The closing band before the footer. Maps to `FinalCtaSection({ status, isSignedIn, … })` in `landing-page.tsx`.

## Layout

```
                                                                
                                                                
                    Ready to tailor?                            
                                                                
                  [G  Enter workspace]                          
                                                                
                                                                
─────────────────────────── (footer hairline) ────────────────
```

A single short headline + the same dynamic primary CTA from the hero, vertically centered in a tall band before the footer.

## Composition

```jsx
<section className="l-final" aria-labelledby="l-final-title">
  <h2 id="l-final-title" className="l-final-title">Ready to tailor?</h2>
  <button
    className="l-btn l-btn-primary l-btn-lg"
    onClick={handlePrimaryCta}
    disabled={status === 'loading'}
  >
    {primaryGlyph} {primaryLabel}
  </button>
</section>
```

CSS:

```css
.l-final {
  padding: 120px 32px;             /* tall band — gives the closing
                                      moment its own breathing room */
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 32px;
}
.l-final-title {
  font-family: var(--font-space-grotesk), system-ui, sans-serif;
  font-size: clamp(40px, 5vw, 64px);
  font-weight: 600;
  letter-spacing: -0.02em;
  color: var(--l-fg);
}
```

## CTA behavior

The CTA is a **mirror of the hero's primary CTA** — same hook, same labels, same dynamic states:

| `status` | `isSignedIn` | Renders |
|---|---|---|
| `loading` | — | `Restoring session…` (disabled) |
| `ready` | `true` | `Enter workspace` |
| `ready` | `false` | `Sign in with Google` |
| `error` | — | `Sign in with Google` + inline notice |

Why repeat the CTA from the hero? The user has just spent 3+ scroll-pages reading the value prop and the four-step narrative. By the closing band they should be able to convert without scrolling back up.

## Background

Inherits the same `.l-shell` background (orbs + grain). No additional treatment — the band is intentionally minimal so the headline + button carry it. A faint accent glow could be added behind the headline as a future variation but it's not currently shipped.

## Behavior preservation

- [x] CTA delegates to the same `handlePrimaryCta` that the hero uses (single source of truth).
- [x] Disabled state during `status === 'loading'`.
- [x] Mobile responsive — title clamps down at narrow widths; the band's vertical padding tightens at ≤540px (`80px 18px`).

## Tokens used here

| Token | Value | Used for |
|---|---|---|
| `--font-space-grotesk` | Space Grotesk | Title |
| `--accent-strong` | `#4171ff` | Primary CTA fill |
| `--l-fg` | `#f5f8ff` | Title color |

## Variations to consider when redesigning

- **Add a soft subtitle** if the headline becomes too punchy in isolation. e.g. "One workspace, four steps, every application tailored." But test first — short headlines often hit harder than long ones at the closing band.
- **Don't add a third CTA**. Same rule as the hero — keep the conversion path single.
- **Avoid moving this section above the footer.** The "Ready to tailor?" moment needs the entire scroll narrative behind it; placing it earlier (e.g. between hero and workbench) would feel premature.
