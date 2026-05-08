# Chrome — Topbar, Step Rail, Hero, ⌘K Palette, FAB

The frame around the four steps. Lives in `WorkspaceShell.tsx`. All shipped values reflect what's in production; the original handoff had a slightly different token namespacing (`--ink-*`, `--line-*`) that did not survive the build. The shipped names use `--fg-*`, `--border`, `--hairline`.

## Topbar

```
┌────────────────────────────────────────────────────────────────────┐
│ [logo] Job Application Copilot      [⌘K Search workspace…]   [👤▾] │
└────────────────────────────────────────────────────────────────────┘
```

- **Logo + product name** on the left. Logo links back to the landing page on the marketing host.
- **Center:** ⌘K trigger pill — `<button>` styled like an input, label "Search or run command…", trailing `⌘K` mono kbd. Click opens the palette overlay; same global key listener handles the keyboard shortcut.
- **Right:** account popover — collapsed shows the user's avatar initial + name; expanded shows plan tier, daily quota usage strip, saved-workspace TTL hint, and Sign out. **Daily quota lives here, not in a separate topbar pill.**
- Hairline bottom border (`--hairline`).

If the user is signed out the right slot becomes a "Sign in" button instead of the popover.

## Step rail

```
        ┌───────────────────────────────────────┐
        │ ① Resume   ✓ Job Search  ○ JD ...     │
        │ ━━━━━━━━━━━━●━━━━━━╌╌╌╌╌╌╌╌╌╌╌╌╌╌╌  │
        └───────────────────────────────────────┘
```

A unified pill nav with a progress connector, centered horizontally below the topbar. Each step:

- **Mono number** (or `✓` if complete) in a square chip — uses `--font-mono`.
- **Step name** in `--font-body`.
- **Active step:** solid accent chip + bold label.
- **Done steps:** check chip + normal label, clickable to revisit.
- **Future steps:** outlined chip + muted label, **disabled** until the gate passes. The disabled tooltip surfaces an honest reason: `"Upload a resume to unlock."`, `"Need a parsed resume + job description first."`, etc.
- **Progress connector** runs underneath the chips and fills proportionally with `(done_count + 0.5 * is_active) / (total - 1)`. Uses `--accent-glow` for the filled segment.

Gating rules (existing logic, unchanged from the original handoff):

- `resume` → always available
- `jobs` → available once a candidate profile exists
- `jd` → available once a candidate profile exists (and either a selected job or paste/url ready)
- `analysis` → available once both resume + jd are parsed

CSS: `.b-rail`, `.b-rail-row`, `.b-rail-step`, `.b-rail-num`. The connector is a `::after` pseudo on `.b-rail` driven by a `--b-rail-progress` custom property set inline on the element.

## Hero

```
┌────────────────────────────────────────────────────────────────────┐
│ Job Search                                  [Resume · uploaded]    │
│ Find live listings, paste a posting URL,    [Role · ML Engineer]   │
│ or open a saved job.                        [● 12 matches]         │
└────────────────────────────────────────────────────────────────────┘
```

Below the rail, the hero band shows:

- Title + sub for the active tab (dynamic per tab, e.g. "Resume" / "Job Search" / "Job Detail" / "Analysis").
- A right-side cluster of **stat pills** (`b-hero-stat`) summarizing workspace state:
  - Resume — "Resume not uploaded" / "Resume uploaded"
  - Role — "No role loaded yet" / job title
  - Per-tab status — "Start here" / `N matches` / `Streaming` / etc., with a status pip color (`b-hero-stat-ok`, `b-hero-stat-warn`, `b-hero-stat-info`)

CSS: `.b-hero`, `.b-hero-title`, `.b-hero-sub`, `.b-hero-stats`, `.b-hero-stat`, status modifiers.

## ⌘K Command Palette

- Trigger: `Cmd+K` / `Ctrl+K` (global key listener), or click the topbar pill.
- Overlay: dark backdrop + centered card (max-width 640px).
- Sections (collapse to whichever has results):
  1. **Jump to** — Resume, Job Search, JD Review, Analysis (gated; locked steps still appear with their lock-reason tooltip).
  2. **Saved jobs** — from `useSavedJobs`; selecting one navigates to Step 3 with that job preloaded.
  3. **Recent assistant turns** — last 5 from `useAssistantHistory`.
  4. **Actions** — "Run analysis" (gated by ready), "Re-upload resume", "Clear workspace".
- Keyboard: ↑/↓ to navigate, Enter to select, Esc to close.
- Empty query shows all sections; typing filters across all entries.

Lives in `CommandPalette.tsx`, mounted by `WorkspaceShell`.

## Floating Assistant FAB

- Anchored bottom-right (24px from edges).
- Collapsed: 56×56 circular button with assistant icon + small "● online" dot.
- Expanded: 380×560 panel mounted at the same anchor, slide-up + fade-in (~`--duration-base`).
- Panel body is the `AssistantPanel` component, including the SSE streaming chat (see `04-analysis.md` for the SSE event contract — same surface).
- History persists across open/close via `useAssistantHistory`.
- Closing collapses to the FAB; clearing history is inside the panel header.

## Mobile (≤ 540px)

A single 540px breakpoint covers every surface. Below it:

- **Topbar** stacks brand + ⌘K pill above the account popover row.
- **Rail** wraps onto multiple lines if needed; each step pill takes its natural width.
- **Hero** stat pills stack vertically and the hero sub line wraps.
- **Regions** (the canvas blocks for each tab) drop their two-up grids to a single column.
- **Account popover** stat sections inset horizontally to fit narrow widths.
- **Search filter row** (Step 2) wraps via `flex-wrap: wrap`; the URL import form moves below the filter row.

## Tokens (Direction B — shipped values)

The full token table lives in the design-system README and in `prototype/tokens.css`. Highlights for chrome:

| Group | Token | Value |
|---|---|---|
| Background | `--bg-page` | `#04070f` (with a layered radial gradient over it) |
| | `--bg-card` | `rgba(10, 14, 22, 0.72)` |
| | `--bg-card-2` | `rgba(20, 26, 40, 0.70)` (inset / hover) |
| Ink | `--fg` | `#f5f8ff` |
| | `--fg-2` | `#c7cfdf` |
| | `--fg-3` | `#8a93a8` (eyebrow + caption) |
| | `--fg-4` | `#5e6677` (placeholder + disabled) |
| Lines | `--hairline` | `rgba(160, 178, 218, 0.07)` |
| | `--border` | `rgba(160, 178, 218, 0.12)` |
| | `--border-strong` | `rgba(160, 178, 218, 0.20)` |
| Accent | `--accent` | `#4171ff` |
| | `--accent-strong` | `#5a86ff` |
| | `--accent-glow` | `rgba(48, 100, 255, 0.45)` |
| | `--accent-tint` | `rgba(48, 100, 255, 0.14)` |
| Status | `--success` | `#7fe0b0` |
| | `--warning` | `#ffcb94` |
| | `--danger` | `#ff8b8b` |
| Radius | `--radius-sm / --radius / --radius-lg / --radius-xl` | `6 / 10 / 14 / 20px` |
| Motion | `--ease-out` | `cubic-bezier(0.16, 1, 0.30, 1)` |
| | `--ease-spring` | `cubic-bezier(0.34, 1.56, 0.64, 1)` |
| | `--duration-fast / --duration-base` | `150 / 240ms` |
| Type | `--font-display` | Space Grotesk (display) |
| | `--font-body` | DM Sans (body) |
| | `--font-mono` | Geist Mono (eyebrows, kbd, step numbers) |

## Eyebrow rule

Every region starts with a mono eyebrow: `STEP {NN} · {SECTION NAME}` in `--fg-3`, `letter-spacing: 0.04em`, `font-size: 11px`, `font-weight: 500`. This is the visual rhythm that ties the whole workspace together — do not skip it. Exceptions: topbar + FAB.
