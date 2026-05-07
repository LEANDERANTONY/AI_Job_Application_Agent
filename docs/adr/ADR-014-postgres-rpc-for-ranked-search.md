# ADR-014: Postgres RPC For Ranked Job Search

- Status: Accepted
- Date: 2026-05-08

## Context

[ADR-013](ADR-013-cached-jobs-cache-layer-with-scheduled-refresh.md) introduced the `cached_jobs` table. The user-facing search needs to:

- run full-text search on title + company + description with typed terms
- rank by `ts_rank` when there's a query, fall back to recency when there isn't
- filter by source, location, work mode, employment type, "posted within N days", and explicit remote-only
- return a small page (≤ 50 rows) ordered by the chosen sort key

The first attempt did this with chained PostgREST builders:

```python
client.table("cached_jobs")
    .select(...)
    .text_search("description_tsv", query)
    .ilike("location", f"%{location}%")
    .order("posted_at", desc=True)
    .limit(20)
    .execute()
```

This failed at runtime. PostgREST's `text_search()` returns a *terminating* query builder that only exposes `.execute()` — it does not chain into `.order()`, `.limit()`, or any further filter. We could either:

- Run the FTS as a separate query and JOIN/filter in Python, paying the round-trip cost twice, **or**
- Move the whole ranked-and-filtered query into a Postgres function and call it from PostgREST as an RPC.

We also want the ranking expression (`ts_rank(description_tsv, websearch_to_tsquery(query))`) inside the `ORDER BY`, which PostgREST's `.order()` can't reference because it expects a column name.

## Decision

The ranked search lives in a Supabase-defined Postgres function (`search_cached_jobs_ranked`) called via `client.rpc("search_cached_jobs_ranked", args).execute()`.

The function:

- Accepts `p_query`, `p_location`, `p_sources`, `p_remote_only`, `p_posted_within_days`, `p_limit`, `p_work_modes`, `p_employment_types`, `p_sort_by` as named parameters.
- Builds a single SELECT against `cached_jobs WHERE removed_at IS NULL` with all the filters applied.
- Branches its `ORDER BY` on `p_sort_by`:
  - `relevance` → `ts_rank(description_tsv, websearch_to_tsquery(p_query)) DESC` when query is non-empty, else `posted_at DESC NULLS LAST`
  - `newest` → `posted_at DESC NULLS LAST`
  - `oldest` → `posted_at ASC NULLS LAST`
  - `company_az` → `LOWER(company) ASC`
  - any other value coerces to `relevance`
- Marked `SECURITY DEFINER` and `GRANT`ed to `service_role` so the backend can call it with the same key it already uses for the cache writes.

The Python side (`CachedJobsStore.search`) builds the kwarg dict and forwards it to the RPC. Filter values (sources, work modes, employment types, sort) are whitelisted in Python before they reach the RPC so a malformed UI param can't generate a query that returns zero rows just because of casing, and so the RPC always sees a known sort key.

The schema gained two `GENERATED ALWAYS AS … STORED` columns to support the new filters efficiently:

- `work_mode` — derived from `remote`, `metadata->>'workplace_type'`, and `location` keywords; one of `remote | hybrid | onsite | ''`
- `employment_type_norm` — derived from `employment_type` + `title` with Postgres word-boundary regex (`~* '\mintern(s|ship|ships)?\M'`) so "Internal Systems" and "International" don't false-match as internships; one of `fulltime | parttime | contract | internship | temporary | ''`

Both columns get a partial index filtering on `removed_at IS NULL AND col <> ''` so the active-row scan stays cheap at ~10k+ rows.

## Alternatives Considered

### 1. Two separate PostgREST round trips: FTS, then re-filter + sort in Python
Rejected. Doubles the network cost for every search, doesn't paginate cleanly (you'd have to over-fetch from FTS and trim), and Python-side `ts_rank` isn't possible.

### 2. Drop FTS entirely and use ILIKE + manual ranking
Rejected. Loses the synonym + stemming + phrase support that `websearch_to_tsquery` gives us for free, and ILIKE against a 12k-row table with no trigram index would be slow on common technical terms.

### 3. Keep filter logic in Python, push only the FTS into a function
Considered. Cleaner separation of concerns, but every search would still pay two round trips and the Python side would have to re-query `cached_jobs` to combine results. The single-RPC approach is simpler and doesn't lose anything important.

### 4. Use a Supabase Edge Function instead of a Postgres function
Rejected for now. Edge Functions add a TypeScript runtime + a separate deploy surface for the same logic that fits cleanly in SQL. If we ever need to do something the function language can't express (e.g., calling out to an embeddings API mid-query), we revisit.

## Consequences

### Positive

- Single round trip per user search regardless of how many filters are stacked.
- Ranking expression lives where the data does, so the planner can optimize FTS + sort + filter together.
- The Python side stays small: build a kwargs dict, call rpc, parse rows. The schema contract is the function signature itself, so a contract drift between Python and the migration shows up immediately as a Postgres error in tests.
- Schema-driven filter values (`work_mode`, `employment_type_norm`) keep the dropdown UI honest — if a value isn't in the GENERATED column, it isn't in the dropdown.
- Adding a new sort or filter is a v2 migration on the function plus a Python kwarg change; the API contract stays stable.

### Negative

- Application logic now lives in two places: the Python store (whitelisting + kwarg shape) and the SQL function (ORDER BY branches + filter SQL). Mitigated by:
  - Python tests that pin the RPC arg shape so contract drift surfaces in CI rather than at runtime.
  - The function being short and well-commented; new branches are obvious.
- Supabase function changes need a migration deploy, which is heavier than a Python edit. The trade-off is acceptable because the search shape is stable.
- The `GENERATED STORED` columns make `cached_jobs` rows slightly bigger and inserts very slightly slower. At ~12k active rows this is unmeasurable.

## Follow-Up

- If the cache grows past ~100k rows, add a `tsvector` index on `description_tsv` and consider a `pg_trgm` index for fuzzy company-name matching.
- If we add more sort options (salary band, posted-week relevance), add them as additional `CASE` branches rather than splitting into multiple RPCs.
- See [ADR-013](ADR-013-cached-jobs-cache-layer-with-scheduled-refresh.md) for the cache layer this RPC reads from.
