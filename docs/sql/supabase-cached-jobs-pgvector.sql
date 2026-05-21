-- ---------------------------------------------------------------------------
-- supabase-cached-jobs-pgvector — pgvector schema for semantic job search
-- ---------------------------------------------------------------------------
-- Tier 2 of the 3-tier job-search relevance upgrade. Tier 1 (shipped) added
-- deterministic synonym expansion before lexical FTS. Tier 2 adds pgvector
-- semantic (embedding) search and fuses it with the lexical ranking via
-- Reciprocal Rank Fusion — see `supabase-cached-jobs-hybrid.sql` for the
-- fusion RPC. This file is JUST the schema: the extension, the column that
-- stores per-job embeddings, and the index that makes nearest-neighbour
-- lookups fast.
--
-- WHAT THIS DOES:
--   1. Enables the `vector` extension (pgvector). Supabase ships it; it is
--      not enabled by default on this project (confirmed 2026-05-21 —
--      `vector` 0.8.0 available, `installed_version` NULL).
--   2. Adds `cached_jobs.embedding vector(1536)`. 1536 is the output
--      dimensionality of OpenAI `text-embedding-3-small`, the model the
--      backfill script (`scripts/backfill_job_embeddings.py`) and the
--      embed-on-write path use. The column is NULLABLE on purpose: a fresh
--      row is cached first and embedded second (embed-on-write is
--      non-fatal), and the backfill only ever touches NULL rows, so NULL
--      means "not embedded yet" and the hybrid RPC degrades that row to
--      lexical-only.
--   3. Creates an HNSW index with `vector_cosine_ops` so the hybrid RPC's
--      `embedding <=> p_query_embedding` (cosine distance) ordering is
--      index-accelerated instead of a full-table scan over ~14k rows.
--
-- WHY HNSW (not IVFFlat): HNSW gives better recall/latency at this corpus
-- size and — crucially — needs no training step, so the index is correct
-- the moment it is built even though most rows are still NULL at apply
-- time (rows get embedded afterwards by the backfill). IVFFlat's list
-- centroids would be meaningless if built before the backfill.
--
-- WHY COSINE: `text-embedding-3-small` vectors are normalized, so cosine
-- distance is the right similarity metric; the hybrid RPC uses the `<=>`
-- (cosine distance) operator, which this opclass indexes.
--
-- IDEMPOTENT: every statement is `IF NOT EXISTS`, so re-applying this file
-- is a no-op and safe. It does NOT backfill any data — run
-- `scripts/backfill_job_embeddings.py` after applying this (see that
-- script's header and the Day 69 DEVLOG operator runbook).
--
-- DEPLOY ORDER (operator action — see DEVLOG Day 69 "OPERATOR ACTION
-- REQUIRED"): apply THIS file first, then run the backfill script, then
-- apply `supabase-cached-jobs-hybrid.sql`, then flip
-- `JOB_SEARCH_HYBRID_ENABLED=true`.
--
-- SECURITY: this file only touches schema on the `public.cached_jobs`
-- table, which already has RLS enabled with no policies (defence in depth
-- — only the service-role client reaches it). Adding a column / index does
-- not change that posture.
-- ---------------------------------------------------------------------------

-- 1. pgvector. `IF NOT EXISTS` so re-applying is a no-op.
CREATE EXTENSION IF NOT EXISTS vector;

-- 2. The embedding column. vector(1536) = text-embedding-3-small output dim.
--    Nullable: a row is cached first, embedded second (NULL = not embedded
--    yet -> hybrid RPC falls back to lexical for that row).
ALTER TABLE public.cached_jobs
    ADD COLUMN IF NOT EXISTS embedding vector(1536);

-- 3. HNSW index for fast cosine-distance ANN search. `vector_cosine_ops`
--    matches the `<=>` operator the hybrid RPC orders by. Defaults for
--    m / ef_construction are fine for a ~14k-row corpus; tune later if
--    recall/latency ever needs it. NULL-embedding rows are simply not
--    represented in the index, which is exactly what we want.
CREATE INDEX IF NOT EXISTS cached_jobs_embedding_hnsw_idx
    ON public.cached_jobs
    USING hnsw (embedding vector_cosine_ops);
