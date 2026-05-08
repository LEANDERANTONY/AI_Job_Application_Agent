# Step 2 — Job Search

Maps to `frontend/src/components/workspace/JobSearch.tsx`. The shipped surface diverged from the original "filter chips + 3-column grid" sketch — it now has multi-select dropdowns, a sort selector, a saved-jobs collapsible drawer, and an "Expired" badge for tombstoned cache entries. The component contract changed alongside it.

## Layout

```
┌─ Region head ──────────────────────────────────────────────────────┐
│ Find a role                                              STEP 02   │
│ Search live listings, paste a posting URL, or open a saved job.    │
└────────────────────────────────────────────────────────────────────┘

┌─ Search bar ───────────────────────────────────────────────────────┐
│ 🔍 [Keywords ............] │ [Location · or remote] │  [ Search ]  │
└────────────────────────────────────────────────────────────────────┘

┌─ Filter row ───────────────────────────────────────────────────────┐
│ [Source ▾]  [Work mode ▾]  [Type ▾]  Posted within [Any time ▾]    │
│ Sort [Relevance ▾]                                                 │
│                                  Or paste URL: [...] [ Import ]    │
└────────────────────────────────────────────────────────────────────┘

┌─ Saved jobs (collapsible drawer) ──────────────────────────────────┐
│ ▸ Saved jobs                                          2 saved      │
└────────────────────────────────────────────────────────────────────┘

┌─ Results header ───────────────────────────────────────────────────┐
│ MATCHES · 12 ROLES                          Sorted by relevance    │
└────────────────────────────────────────────────────────────────────┘

┌─ Results grid (2-col, wraps to 1-col below 540px) ─────────────────┐
│ ┌─ Top match ──────┐  ┌──────────────────┐                         │
│ │ ★ TOP MATCH      │  │ Job Card          │                        │
│ │ Anthropic        │  │ Stripe            │                        │
│ │ Staff ML Eng     │  │ Senior ML Eng     │                        │
│ │ Remote · …       │  │ SF · …            │                        │
│ │ [Review] [Open]  │  │ [Review] [Open]   │                        │
│ └──────────────────┘  └──────────────────┘                         │
│ …                                                                  │
└────────────────────────────────────────────────────────────────────┘
```

## Filter dropdowns

The original handoff proposed "filter chips" (single-tap toggles). That doesn't compose with five facets, multi-select on three of them, and a single-select sort, so the shipped version uses a **chip + popover** pattern built on native `<details>`/`<summary>`:

| Control | Type | Options | Backend kwarg |
|---|---|---|---|
| **Source** | multi-select | Greenhouse / Lever / Ashby / Workday | `source_filters` |
| **Work mode** | multi-select | Remote / Hybrid / On-site | `work_modes` |
| **Type** | multi-select | Full-time / Part-time / Contract / Internship / Temporary | `employment_types` |
| **Posted within** | single-select (native) | Any time / Last 3 / 7 / 14 / 30 days | `posted_within_days` |
| **Sort** | single-select (native) | Relevance / Most recent / Oldest / Company A → Z | `sort_by` |

Multi-select chip label rules:
- Empty → `"Any source"` / `"Any mode"` / `"Any type"`
- Single pick → the actual option label (e.g. `Remote`, not `1 selected`)
- Two or more picks → `"N selected"`

Popover dismissal:
- Click the chip again → close (native `<details>` behavior)
- Click outside the `<details>` element → close (handled by an extra `mousedown` listener in `MultiSelectFilter`)
- Escape key → close + return focus to the summary chip

The Sort native-select chip updates the right-side header text live (`Sorted by relevance` / `…by company a → z` / etc.) so the user always sees the current sort state.

CSS: `.b-filter-popover`, `.b-filter-popover > summary`, `.b-filter-popover-label`, `.b-filter-popover-value`, `.b-filter-popover-caret`, `.b-filter-popover-panel`, `.b-filter-popover-item`.

## Top-match badge

Shipped rule is simpler than the original handoff sketch:

- The first card in the result set gets a `★ TOP MATCH` badge **only when there are ≥ 2 results total** (so a one-result page doesn't crown its only entry).
- The card gets a subtle accent ring (`box-shadow: 0 0 0 1px var(--accent)` analog).
- There is **no numeric match score** in the UI today. The earlier `JobPosting.matchScore` field doesn't exist on the live posting type. If a score lands later, this is the place it surfaces.

## Expired badge

Cards from sources we cache (`source: greenhouse | lever | ashby | workday`) display an **"Expired"** badge in the card header when the upstream board stopped listing the role. Driven by `JobPosting.is_listing_active === false`; `undefined` and `true` both render as active so old responses (before the field landed) and jobs from sources we don't cache stay rendered as active.

The cache cleanup pass tombstones (instead of deleting) any listing a user has bookmarked, so a saved job's "Expired" state is honest about why the apply link probably doesn't work anymore. See ADR-013 in the project docs for the cleanup policy.

CSS: `.b-saved-mark[data-expired="true"]`.

## Saved jobs drawer

Lives **inline on the search page**, above the results grid — not in the topbar, not in a sidebar.

- Button row: `▸ Saved jobs · N saved`. Closed by default.
- When expanded: a grid of saved-job cards with `Load into workspace` + `Remove` buttons (the workspace-load action picks up where the user left off; remove is a soft-confirm).
- Sign-out state collapses the drawer to a "Sign in to save" hint.
- Server-synced via `useSavedJobs`; persistence is per-user.

CSS: `.b-saved-section`, `.b-saved-toggle`, `.b-saved-caret`, `.b-saved-title`, `.b-saved-count`, `.b-saved-empty`.

## URL import

Lives on the right side of the filter row as a small `<form>`:

```
Or paste URL: [greenhouse.io/...]  [ Import ]
```

Paste a supported job URL (Greenhouse / Lever / Ashby / Workday board URL) → backend resolves the posting via `resolveJobUrl` → workspace navigates to Step 3 with that job preloaded. This is **not** a search escape hatch in the keyword input; the user types the URL into the dedicated import field.

CSS: `.b-search-import`, `.b-search-import-input`.

## Component contract (shipped)

The component is fully controlled — every piece of state is lifted into `WorkspaceShell`:

```ts
type WorkMode = "remote" | "hybrid" | "onsite";
type EmploymentType = "fulltime" | "parttime" | "contract" | "internship" | "temporary";
type JobSortBy = "relevance" | "newest" | "oldest" | "company_az";

interface JobSearchProps {
  // Search bar
  searchQuery: string;
  onSearchQueryChange: (value: string) => void;
  searchLocation: string;
  onSearchLocationChange: (value: string) => void;
  postedWithinDays: string;
  onPostedWithinDaysChange: (value: string) => void;

  // Multi-select dropdowns
  sourceFilters: string[];
  onSourceFiltersChange: (value: string[]) => void;
  workModes: WorkMode[];
  onWorkModesChange: (value: WorkMode[]) => void;
  employmentTypes: EmploymentType[];
  onEmploymentTypesChange: (value: EmploymentType[]) => void;

  // Sort dropdown
  sortBy: JobSortBy;
  onSortByChange: (value: JobSortBy) => void;

  searching: boolean;
  onSearchSubmit: (event: FormEvent<HTMLFormElement>) => void;

  // URL import
  jobUrl: string;
  onJobUrlChange: (value: string) => void;
  importing: boolean;
  onImportSubmit: (event: FormEvent<HTMLFormElement>) => void;

  // Results + selection
  searchResults: JobSearchResponse | null;
  searchNotice: JobSearchNotice | null;
  activeJob: JobPosting | null;
  onReviewRole: (job: JobPosting) => void;

  // Saved-jobs drawer
  savedJobIds: Set<string>;
  savedJobActionId: string | null;
  authSignedIn: boolean;
  onSaveJob: (job: JobPosting) => void;
  savedJobsEnabled: boolean;
  savedJobs: JobPosting[];
  savedJobsNotice: JobSearchNotice | null;
  savedJobsLoading: boolean;
  latestSavedJobAt: string;
  onLoadSavedJob: (job: JobPosting) => void;
  onRemoveSavedJob: (job: JobPosting) => void;
}
```

## Behavior preservation

- `searchJobs(...)` runs on **submit**, not debounced on input. Submit hits `POST /api/jobs/search` with the full filter set.
- Filter dropdowns drive query re-runs only after the user clicks Search — they don't auto-fire so a user mid-selection isn't penalized for every checkbox click.
- Save / unsave persists via `useSavedJobs`; saved-job list is server-synced.
- Selected job (`Review role`) drives Step 3 — selection persists when navigating away and back.
- URL import is its own form; doesn't share state with the search input.

## States

| State | Visual |
|---|---|
| Empty (no query yet) | Search header only; results area shows `"Search for roles to load one into your workspace."` empty hint |
| Loading | `Searching…` button label + filter row stays interactive |
| Results | Grid of cards; top-match badge on the leader if `results.length >= 2` |
| No results | `"No roles matched this search. Try different keywords."` empty card |
| URL import in flight | `Importing…` button label on the right form |
| Cached source unavailable | Search returns results from live fan-out fallback; `source_status.cache` field surfaces in the notice |

## CSS classes

- `.b-region`, `.b-region-head`, `.b-region-title`, `.b-region-sub`, `.b-region-tag`
- `.b-search-bar`, `.b-search-icon`, `.b-search-divider`
- `.b-search-row`, `.b-search-filters`, `.b-search-toggle`
- `.b-filter-popover` and children (see Filter dropdowns above)
- `.b-search-import`, `.b-search-import-input`
- `.b-saved-section`, `.b-saved-toggle`, `.b-saved-caret`, `.b-saved-title`, `.b-saved-count`, `.b-saved-empty`
- `.b-results-head`, `.b-section-label`
- `.b-job-grid`, `.b-job-card`, `.b-job-card-head`, `.b-job-card-title`, `.b-job-card-company`, `.b-job-card-aside`
- `.b-job-card-summary`, `.b-job-card-meta`, `.b-job-card-meta-dot`, `.b-job-card-actions`
- `.b-top-match-badge`, `.b-saved-mark`, `.b-saved-mark[data-expired="true"]`
- `.b-notice` + `.b-notice-success` / `.b-notice-warning`

## Backend integration notes

- The search endpoint is `POST /api/jobs/search`; `?live=true` fans out live to upstream ATSes for diagnostics; default reads from the cached-jobs Supabase index via the `search_cached_jobs_ranked` RPC.
- The four supported ATS providers are Greenhouse, Lever, Ashby, Workday. Adding a new one means a new `JobSourceAdapter` + an entry in `_adapters_with_fetch_all()` + a `<MultiSelectFilter>` option here.
- `is_listing_active` flips to `false` when the cleanup pass tombstones a row (saved-by-someone case). Hard-deleted unsaved rows just disappear from results.
- The `source_status` map in the response surfaces `cache: ok | not_configured | error: ...` so the client can render a banner when the cache is misbehaving without losing the user-visible result.

See project ADR-013 (cache layer) and ADR-014 (search RPC) for the design rationale.
