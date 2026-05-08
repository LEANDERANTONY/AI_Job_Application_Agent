# Bento — Single-Tile Carousel

Section ID `#bento`. Maps to `BentoSection()` in `landing-page.tsx`. The "Everything else worth knowing about" band — non-narrative supporting features that don't fit the four-step flow.

## Layout

```
              BUILT INTO THE WORKBENCH
       Everything else worth knowing about
─────────────────────────────────────────────────────────

   ┌─────────────────────────────────────────────────────┐
   │  12,000+ OPEN JOBS                                  │   ← active tile
   │  Greenhouse · Lever · Ashby · Workday               │     full-width
   │                                                     │
   │  Live listings from 130+ companies including        │
   │  Stripe, Pinterest, Anthropic, Notion, Walmart,    │
   │  and Disney. Refreshed every 30 minutes so          │
   │  you're always seeing what's actually open.        │
   │                                                     │
   │  [greenhouse]  [lever]  [ashby]  [workday]          │
   └─────────────────────────────────────────────────────┘

           ←   ●   ○   ○   ○   →                            ← controls row
```

A single tile fills the visible width at all times. Users click prev/next or a dot to jump tiles, or swipe / two-finger scroll on the strip itself.

## Section head

Same `.l-section-head` pattern as the workbench: mono eyebrow + Space Grotesk title.

```jsx
<div className="l-section-head">
  <span className="l-section-eyebrow">BUILT INTO THE WORKBENCH</span>
  <h2 className="l-section-title">Everything else worth knowing about</h2>
</div>
```

## Strip + tile structure

```jsx
<div ref={stripRef} className="l-bento-strip">
  {tiles.map((tile, i) => (
    <article key={i} className="l-bento-tile">
      <div className="l-bento-eyebrow">{tile.eyebrow}</div>
      <h3 className="l-bento-title">{tile.title}</h3>
      <p className="l-bento-body">{tile.body}</p>
      {tile.chips && (
        <div className="l-bento-chips">
          {tile.chips.map(c => <span key={c} className="l-bento-chip">{c}</span>)}
        </div>
      )}
    </article>
  ))}
</div>
```

Key CSS:

```css
.l-bento-strip {
  display: flex;
  flex-wrap: nowrap;
  overflow-x: auto;
  scroll-snap-type: x mandatory;
  scroll-behavior: smooth;
  scrollbar-width: none;            /* Firefox */
}
.l-bento-strip::-webkit-scrollbar { display: none; }

.l-bento-tile {
  position: relative;
  flex: 0 0 100%;                   /* one tile == full strip width */
  scroll-snap-align: start;
  scroll-snap-stop: always;
  background: rgba(0, 0, 0, 0.40);  /* matches workspace .b-jd-block */
  border: 1px solid var(--l-line-strong);
  border-radius: var(--l-radius-lg);
  padding: 36px 40px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  overflow: hidden;
  min-height: 360px;
}
```

**Why these values:**
- **`flex: 0 0 100%`** so each tile takes the strip's full clientWidth. With `scroll-snap-align: start; scroll-snap-stop: always;`, swipes always land on a tile boundary and never drift between tiles.
- **`overflow-x: auto` + `scrollbar-width: none`** so the underlying scroll mechanic is native (good touch behavior + accessibility) but the scrollbar UI is hidden in favor of the dot indicators.
- **`min-height: 360px`** keeps the carousel a consistent height as the user clicks through varying-content tiles. Without it, a tile with 3 lines of body and one with 6 would cause the carousel to jump.

## Controls

```jsx
<div className="l-bento-controls">
  <button className="l-bento-arrow l-bento-arrow-prev" disabled={activeIndex === 0} …>
    <ArrowGlyph direction="left" />
  </button>
  <div className="l-bento-dots">
    {[...Array(BENTO_TILES_COUNT)].map((_, i) => (
      <button
        className={`l-bento-dot ${i === activeIndex ? "is-active" : ""}`}
        onClick={() => scrollToIndex(i)}
        …
      />
    ))}
  </div>
  <button className="l-bento-arrow l-bento-arrow-next" disabled={activeIndex === BENTO_TILES_COUNT - 1} …>
    <ArrowGlyph direction="right" />
  </button>
</div>
```

CSS:
- `.l-bento-controls` — `display: flex; align-items: center; justify-content: center; gap: 16px; margin-top: 32px;`
- `.l-bento-arrow` — circular 36×36 button, `border: 1px solid var(--l-line-strong);` `background: rgba(0,0,0,0.30)`. `:disabled { opacity: 0.4; cursor: not-allowed; }`
- `.l-bento-dots` — `display: inline-flex; align-items: center; gap: 6px; padding: 4px 8px; background: rgba(0,0,0,0.3); border-radius: 999px;`
- `.l-bento-dot` — 6×6 circle, `background: rgba(255,255,255,0.20)`. `.is-active` widens to a 24×6 pill in `var(--accent-strong)`.

## Imperative scroll

```ts
function scrollToIndex(index: number) {
  const strip = stripRef.current;
  if (!strip) return;
  const clamped = Math.max(0, Math.min(BENTO_TILES_COUNT - 1, index));
  strip.scrollTo({
    left: clamped * strip.clientWidth,
    behavior: "smooth",
  });
}
```

Both the arrow buttons and the dot buttons call `scrollToIndex`. `scrollTo` triggers the strip's own scroll-snap so the final landing is precise even if the math is a hair off.

## Active-index sync (from user scroll)

```ts
useEffect(() => {
  const strip = stripRef.current;
  if (!strip) return;
  let raf = 0;
  const onScroll = () => {
    if (raf) return;
    raf = requestAnimationFrame(() => {
      raf = 0;
      const idx = Math.round(strip.scrollLeft / strip.clientWidth);
      setActiveIndex(idx);
    });
  };
  strip.addEventListener("scroll", onScroll, { passive: true });
  return () => strip.removeEventListener("scroll", onScroll);
}, []);
```

A rAF-debounced scroll listener derives the active index from `scrollLeft / clientWidth`. This keeps the dots correct when the user drags / swipes (instead of clicking buttons). `requestAnimationFrame` debouncing is enough — no 16ms throttle needed.

## Tiles (current data)

`BENTO_TILES_COUNT = 4`. The shipped tile content lives inline inside `BentoSection()`:

1. **12,000+ OPEN JOBS / Greenhouse · Lever · Ashby · Workday** — chips: `greenhouse · lever · ashby · workday`
2. (three more — see the component for current copy)

Earlier the section had 5 tiles including a "FAST SEARCH" tile that duplicated the hero's value prop; we cut it during the build.

## Behavior preservation

- [x] Trackpad / touch swipe on the strip respects scroll-snap (lands on tile boundary).
- [x] Arrow buttons + dots both call `scrollToIndex(i)` — single source of truth.
- [x] Active dot pill widens to a `24×6` pill in accent color.
- [x] Prev arrow disabled at index 0; next arrow disabled at last index.
- [x] Strip scrollbar is hidden across browsers (`scrollbar-width: none` + webkit `display: none`).
- [x] At ≤900px tile padding tightens (`30px 28px`); at ≤540px it tightens again (`24px 22px`).

## Tokens used here

| Token | Value | Used for |
|---|---|---|
| `--font-space-grotesk` | Space Grotesk | Tile title (`.l-bento-title`) |
| `--font-geist-mono` | Geist Mono | Tile eyebrow + chips |
| `--l-card` overlay | `rgba(0, 0, 0, 0.40)` | Tile background (matches `.b-jd-block`) |
| `--l-line-strong` | `rgba(255, 255, 255, 0.10)` | Tile border + arrow border |
| `--l-radius-lg` | `20px` | Tile radius |
| `--accent-strong` | `#4171ff` | Active dot pill |
| `--l-ease` | `cubic-bezier(0.16, 1, 0.30, 1)` | Arrow hover, dot transitions |

## Variations to consider when redesigning

- **Number of tiles.** 4 is comfortable. 5–6 starts to feel hidden — users don't know how many remain. If the brief needs more, switch to a 2×N grid instead of a carousel.
- **Tile composition.** Current pattern is `eyebrow + title + body + chip row`. An optional `image / mock` block could go above the title for product-screenshot tiles.
- **Auto-advance.** None of the current tiles auto-advance. Adding it would require pausing on hover / focus and respecting `prefers-reduced-motion`.
- **Don't add a 2-up grid layout for desktop.** It was tried earlier and read as a "wall of tiles" instead of a focused "now look at this one feature." The single-tile form stays.
