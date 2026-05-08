# ADR-013: Cached Jobs Cache Layer With Scheduled Refresh

- Status: Accepted
- Date: 2026-05-08

## Context

The earlier `/jobs/search` endpoint fanned out live to every configured Greenhouse + Lever board on every user query. Once the source pool grew past ~30 boards, two problems showed up immediately:

- end-to-end search latency drifted to ~25 s in the live path because every board fetch hit the upstream API in series under our concurrency cap, and even the parallel branches still paid the slowest-board tax
- the cost model for adding new ATS providers got worse linearly — every new provider made every search slower, even for users searching topics that provider didn't have
- transient board failures leaked into user-facing results: one DNS hiccup at one ATS could drop a whole result set or surface "0 matches" for a query the user had run successfully five minutes earlier

We also needed a way to keep saved-jobs alive even after the upstream board stopped listing the role, so users don't lose their bookmark history when a posting closes.

## Decision

Move the live fan-out behind a Supabase-cached `cached_jobs` table refreshed on a schedule by the backend itself.

The shape:

- A `cached_jobs` table holds one row per (source, job_id), keyed on a composite unique constraint, with the full posting metadata, `last_seen_at`, and a nullable `removed_at` tombstone field.
- A backend worker `refresh_cached_jobs()` iterates the configured ATS adapters (Greenhouse, Lever, Ashby, Workday), bulk-upserts every posting per source into `cached_jobs`, and updates `last_seen_at` to the refresh start time.
- After the upserts, the worker runs a smart cleanup that splits "rows whose `last_seen_at < refresh_start`" into two buckets:
  - **Tombstone** if any user has bookmarked this (source, job_id) in `saved_jobs` — set `removed_at = now()` so the saved-jobs UI can render an "Expired" badge instead of losing the bookmark.
  - **Hard delete** if nobody has bookmarked it.
- Cleanup eligibility is per-source and gated on `boards_succeeded > 0`. A provider where every board failed (transient outage) is excluded from cleanup so a single bad refresh doesn't vaporize the whole cache.
- The refresh runs on a `pg_cron` job that POSTs to `/admin/refresh-cache` via `pg_net.http_post` every ~30 min. Endpoint is protected by a constant-time bearer compare against `REFRESH_CACHE_SECRET`.
- `/jobs/search` reads from the cache by default through `JobSearchService.search_cached(...)`. A `?live=true` query param keeps a live fan-out escape hatch for diagnostics and for the rare case where a user needs strictly-real-time coverage.

The `CachedJobsStore` uses the Supabase service-role key (RLS bypass) because the table is global, not user-scoped. RLS is still enabled on the table with no policies, as defence-in-depth.

## Alternatives Considered

### 1. Per-user cache keyed on the search query
Rejected. The user pool isn't large enough to amortize a per-query cache, and the natural query distribution (long-tail technical role variations) means most queries never repeat exactly. A global posting index avoids the cardinality problem.

### 2. In-memory backend cache only
Rejected. The VPS runs a single uvicorn worker today, but a container restart would lose every cached posting and force the next user to pay the cold fan-out cost. Persisting to Supabase makes restarts cheap and gives the admin endpoint a stable surface for debugging.

### 3. Refresh-on-write inside `/jobs/search` itself
Rejected. Coupling the refresh schedule to user traffic means the first user of a quiet hour pays for the refresh, and a quiet day means the cache silently goes stale. A separate scheduler decouples freshness from request load.

### 4. Scheduled worker on the backend host (cron + curl) instead of `pg_cron + pg_net`
Considered but rejected. Running the cron inside Postgres means the schedule survives a backend redeploy, doesn't need separate orchestration, and is observable through the Supabase dashboard. The `pg_net` extension is already available on Supabase.

## Consequences

### Positive

- Search latency dropped from ~25 s (live fan-out) to ~360 ms warm / ~5.5 s cold against the cache RPC.
- Adding a new ATS provider has constant cost: one adapter that yields `(board_token, status, payload)` triples, one entry in `_adapters_with_fetch_all()`. The user search path stays unchanged.
- Saved-jobs bookmarks survive upstream listing closures with an explicit "Expired" badge.
- Per-source isolation means a Workday outage doesn't poison Greenhouse results.
- Refresh failures are visible in the structured report returned by `/admin/refresh-cache`, so monitoring can alert on `boards_failed` counts per provider.

### Negative

- Cache freshness lags real-time by up to one refresh interval. For high-velocity boards, this can mean a job listed in the last 30 min isn't yet searchable. The `?live=true` escape hatch covers the diagnostic case; the trade-off is acceptable for the user-facing path.
- The cache is now another piece of operational state. A bad migration or accidentally-corrupt upsert could land bad data on every user. Mitigated by:
  - per-board success gating on cleanup
  - the bearer-protected admin endpoint
  - structured per-provider error reporting
- The system depends on `pg_net` and `pg_cron` extensions being enabled on the Supabase project. Documented in `docs/sql/job_cache_cron_setup.sql`.

## Follow-Up

- See [ADR-014](ADR-014-postgres-rpc-for-ranked-search.md) for the search RPC that reads from this cache.
- Track per-provider freshness lag (`scraped_at`/`last_seen_at` distribution) once we have user volume to justify it.
- Consider per-tenant rate-limit budgets on Workday if cache volume grows past the current ~12k active rows.
