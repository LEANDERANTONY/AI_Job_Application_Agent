-- ---------------------------------------------------------------------------
-- search_cached_jobs_hybrid — hybrid (lexical + semantic) job search RPC
-- ---------------------------------------------------------------------------
-- Tier 2 of the 3-tier job-search relevance upgrade. This RPC fuses the
-- Tier 1 lexical full-text ranking with a pgvector semantic (embedding)
-- ranking using Reciprocal Rank Fusion (RRF). The backend calls it via
-- `src/cached_jobs_store.py` (PostgREST `rpc('search_cached_jobs_hybrid')`)
-- when JOB_SEARCH_HYBRID_ENABLED is on; otherwise the store stays on the
-- Tier 1 `search_cached_jobs_ranked` RPC.
--
-- WHY HYBRID: lexical FTS nails exact-keyword matches but misses
-- conceptually-related jobs that share no keywords; semantic search nails
-- conceptual similarity but can drift off precise terms. RRF combines the
-- two RANKINGS (not their raw scores — which live on incomparable scales)
-- so a job ranked highly by EITHER signal surfaces.
--
-- PREREQUISITES (operator must do these first — see DEVLOG Day 70
-- "OPERATOR ACTION REQUIRED"):
--   1. `docs/sql/supabase-cached-jobs-pgvector.sql` applied — the
--      `vector` extension, `cached_jobs.embedding vector(1536)` column,
--      and the HNSW cosine index must exist.
--   2. `scripts/backfill_job_embeddings.py` run — rows need embeddings or
--      the semantic side of every fusion is empty (RPC still works, it
--      just degrades to pure lexical for un-embedded rows).
-- This file (the RPC) is applied AFTER those two steps, then the operator
-- flips JOB_SEARCH_HYBRID_ENABLED=true.
--
-- ARCHITECTURE — HNSW CANDIDATE POOLS (the v2 rewrite, DEVLOG Day 74):
-- Each retriever is its OWN top-N query reading `cached_jobs` directly,
-- so the index can drive candidate selection:
--   - lexical  — GIN on search_tsv; `ORDER BY ts_rank DESC LIMIT 200`.
--   - semantic — HNSW vector_cosine_ops on embedding; `ORDER BY <=>
--                LIMIT 200`.
-- The first cut ranked BOTH lists with window functions over one shared
-- `candidates` CTE of every filtered row; the semantic `row_number()`
-- then had to sort all ~14k embeddings with no usable index and hit the
-- statement timeout against the real corpus. Per-retriever top-N queries
-- keep the HNSW/GIN index in the plan — verified via EXPLAIN ANALYZE.
--
-- NOTE ON hnsw.ef_search: left at the pgvector default (40), so the HNSW
-- scan yields ~40 semantic candidates regardless of the `LIMIT 200` above.
-- That is ample fused against 200 lexical candidates for a 20-50 row page.
-- It is deliberately NOT widened in-function: a function-level `SET`
-- clause is rejected (`42501 permission denied to set parameter` — the
-- migration role lacks the privilege) and a body-level `SET LOCAL` is
-- rejected too (`0A000 SET is not allowed in a non-volatile function` —
-- this RPC is STABLE). An operator with privilege can widen recall
-- globally via `ALTER DATABASE postgres SET hnsw.ef_search = <n>` if the
-- semantic pool ever needs to be deeper.
--
-- PARAMS: identical to `search_cached_jobs_ranked` (p_query, p_location,
-- p_sources, p_remote_only, p_posted_within_days, p_limit, p_work_modes,
-- p_employment_types, p_sort_by, p_offset) PLUS:
--   p_query_embedding vector(1536) — the embedding of the (Tier-1-expanded)
--     query, computed backend-side with text-embedding-3-small. NULL means
--     "no semantic signal" -> the RPC degrades to pure lexical.
--
-- p_query CONTRACT: same as the Tier 1 RPC — p_query is a `to_tsquery`-
-- syntax string already built by the backend's synonym expander
-- (src/job_search_synonyms.py), NOT raw user text. Parsed with
-- `to_tsquery` (not websearch_to_tsquery) for the same reason. Empty
-- p_query = no lexical retriever.
--
-- RRF FUSION: for each job, with k = 60 (the standard RRF constant):
--     rrf = 1.0/(k + lexical_rank) + 1.0/(k + semantic_rank)
--   - lexical_rank: 1-based rank by ts_rank DESC among lexical matches.
--   - semantic_rank: 1-based rank by cosine distance ASC among rows that
--     have an embedding.
--   - A job present in only ONE ranked list contributes ONLY that list's
--     term (the other term is 0) — implemented via a FULL OUTER JOIN and
--     COALESCE(..., 0.0) on the missing term.
--
-- DEGENERATE CASES (all must still return sensible rows):
--   - query present, NULL embedding -> semantic pool empty; pure lexical.
--   - empty query, embedding present -> lexical pool empty; pure semantic.
--   - both empty/NULL -> browse mode: an early-return branch lists the
--     filtered rows ordered by recency (no retriever / fusion needed).
--
-- SORTING: same p_sort_by modes as the Tier 1 RPC. 'relevance' (default)
-- orders by the fused RRF score DESC; 'newest'/'oldest'/'company_az'
-- behave exactly as in `search_cached_jobs_ranked`.
--
-- SECURITY: SECURITY DEFINER + `SET search_path = public`. EXECUTE granted
-- ONLY to `service_role` — NOT anon/authenticated/PUBLIC. Mirrors the
-- Tier 1 RPC and the project-wide posture for SECURITY DEFINER functions
-- (ADR-021). The DROP+CREATE would re-introduce Postgres's implicit
-- EXECUTE-to-PUBLIC, so the REVOKEs below are mandatory.
--
-- IDEMPOTENT: DROP FUNCTION IF EXISTS + CREATE so re-applying reproduces
-- the exact state.
-- ---------------------------------------------------------------------------

-- Drop any prior revision so this file re-applies cleanly. The signature
-- is the Tier 1 param list with `p_query_embedding vector` appended.
DROP FUNCTION IF EXISTS public.search_cached_jobs_hybrid(text,text,text[],boolean,integer,integer,text[],text[],text,integer,vector);

CREATE OR REPLACE FUNCTION public.search_cached_jobs_hybrid(
    p_query text DEFAULT ''::text,
    p_location text DEFAULT ''::text,
    p_sources text[] DEFAULT NULL::text[],
    p_remote_only boolean DEFAULT false,
    p_posted_within_days integer DEFAULT NULL::integer,
    p_limit integer DEFAULT 20,
    p_work_modes text[] DEFAULT NULL::text[],
    p_employment_types text[] DEFAULT NULL::text[],
    p_sort_by text DEFAULT 'relevance'::text,
    p_offset integer DEFAULT 0,
    p_query_embedding vector(1536) DEFAULT NULL::vector(1536)
)
 RETURNS SETOF cached_jobs
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
DECLARE
    tsquery_obj   tsquery;
    has_query     BOOLEAN := COALESCE(p_query, '') <> '';
    has_embedding BOOLEAN := p_query_embedding IS NOT NULL;
    sort_mode     TEXT    := LOWER(COALESCE(p_sort_by, 'relevance'));
    -- RRF damping constant. 60 is the value from the original RRF paper
    -- and the de-facto production default; larger k flattens the
    -- contribution curve, smaller k sharpens it toward rank-1.
    rrf_k    CONSTANT integer := 60;
BEGIN
    IF has_query THEN
        -- Same contract as the Tier 1 RPC: p_query is a to_tsquery-
        -- syntax string from the backend synonym expander, not raw
        -- user text.
        tsquery_obj := to_tsquery('english', p_query);
    END IF;

    -- ----------------------------------------------------------------
    -- Browse mode (no text query, no query embedding): there is no
    -- ranking signal, so skip the retrievers / fusion entirely and
    -- return the filtered rows ordered by recency.
    -- ----------------------------------------------------------------
    IF NOT has_query AND NOT has_embedding THEN
        RETURN QUERY
        SELECT cj.*
        FROM public.cached_jobs cj
        WHERE cj.removed_at IS NULL
          AND (COALESCE(p_location, '') = '' OR cj.location ILIKE '%' || p_location || '%')
          AND (p_sources IS NULL OR cardinality(p_sources) = 0 OR cj.source = ANY (p_sources))
          AND (NOT p_remote_only OR cj.work_mode = 'remote')
          AND (p_work_modes IS NULL OR cardinality(p_work_modes) = 0 OR cj.work_mode = ANY (p_work_modes))
          AND (p_employment_types IS NULL OR cardinality(p_employment_types) = 0 OR cj.employment_type_norm = ANY (p_employment_types))
          AND (p_posted_within_days IS NULL OR cj.posted_at > NOW() - (p_posted_within_days || ' days')::INTERVAL)
        ORDER BY
            CASE sort_mode
                WHEN 'oldest' THEN -extract(epoch from cj.posted_at)
                ELSE extract(epoch from cj.posted_at)
            END DESC NULLS LAST,
            CASE sort_mode WHEN 'company_az' THEN LOWER(cj.company) ELSE NULL END ASC NULLS LAST,
            cj.posted_at DESC NULLS LAST,
            cj.id DESC
        LIMIT GREATEST(1, LEAST(COALESCE(p_limit, 20), 50))
        OFFSET GREATEST(0, COALESCE(p_offset, 0));
        RETURN;
    END IF;

    -- ----------------------------------------------------------------
    -- Hybrid path: at least one of (text query, query embedding) is
    -- present. Each retriever is its own top-N query on `cached_jobs`
    -- so the GIN / HNSW index drives candidate selection (see the
    -- ARCHITECTURE note in the header); RRF then fuses the two
    -- rankings.
    -- ----------------------------------------------------------------
    RETURN QUERY
    WITH
    -- lexical: top-200 by ts_rank among rows whose tsvector matches the
    -- query. Empty when has_query is false (-> pure-semantic fallback).
    -- The GIN index on search_tsv accelerates the `@@` filter; the
    -- outer row_number() assigns the 1-based lexical rank for RRF.
    lexical AS (
        SELECT l.id,
               row_number() OVER (
                   ORDER BY l.rank_score DESC, l.posted_at DESC NULLS LAST, l.id
               ) AS lexical_rank
        FROM (
            SELECT cj.id, cj.posted_at,
                   ts_rank(cj.search_tsv, tsquery_obj) AS rank_score
            FROM public.cached_jobs cj
            WHERE has_query
              AND cj.removed_at IS NULL
              AND cj.search_tsv @@ tsquery_obj
              AND (COALESCE(p_location, '') = '' OR cj.location ILIKE '%' || p_location || '%')
              AND (p_sources IS NULL OR cardinality(p_sources) = 0 OR cj.source = ANY (p_sources))
              AND (NOT p_remote_only OR cj.work_mode = 'remote')
              AND (p_work_modes IS NULL OR cardinality(p_work_modes) = 0 OR cj.work_mode = ANY (p_work_modes))
              AND (p_employment_types IS NULL OR cardinality(p_employment_types) = 0 OR cj.employment_type_norm = ANY (p_employment_types))
              AND (p_posted_within_days IS NULL OR cj.posted_at > NOW() - (p_posted_within_days || ' days')::INTERVAL)
            ORDER BY ts_rank(cj.search_tsv, tsquery_obj) DESC
            LIMIT 200
        ) l
    ),
    -- semantic: top-200 by cosine distance among rows that HAVE an
    -- embedding. Empty when p_query_embedding is NULL (-> pure-lexical
    -- fallback). `<=>` is pgvector cosine distance; the HNSW
    -- vector_cosine_ops index serves this ORDER BY ... LIMIT directly.
    semantic AS (
        SELECT s.id,
               row_number() OVER (
                   ORDER BY s.dist ASC, s.posted_at DESC NULLS LAST, s.id
               ) AS semantic_rank
        FROM (
            SELECT cj.id, cj.posted_at,
                   cj.embedding <=> p_query_embedding AS dist
            FROM public.cached_jobs cj
            WHERE has_embedding
              AND cj.embedding IS NOT NULL
              AND cj.removed_at IS NULL
              AND (COALESCE(p_location, '') = '' OR cj.location ILIKE '%' || p_location || '%')
              AND (p_sources IS NULL OR cardinality(p_sources) = 0 OR cj.source = ANY (p_sources))
              AND (NOT p_remote_only OR cj.work_mode = 'remote')
              AND (p_work_modes IS NULL OR cardinality(p_work_modes) = 0 OR cj.work_mode = ANY (p_work_modes))
              AND (p_employment_types IS NULL OR cardinality(p_employment_types) = 0 OR cj.employment_type_norm = ANY (p_employment_types))
              AND (p_posted_within_days IS NULL OR cj.posted_at > NOW() - (p_posted_within_days || ' days')::INTERVAL)
            ORDER BY cj.embedding <=> p_query_embedding
            LIMIT 200
        ) s
    ),
    -- fused: FULL OUTER JOIN the two ranked lists so a job appearing in
    -- only one still survives. RRF score sums the per-list terms; a
    -- missing rank contributes 0 (COALESCE(..., 0.0)).
    fused AS (
        SELECT
            COALESCE(l.id, s.id) AS id,
            COALESCE(1.0 / (rrf_k + l.lexical_rank), 0.0)
          + COALESCE(1.0 / (rrf_k + s.semantic_rank), 0.0) AS rrf_score
        FROM lexical l
        FULL OUTER JOIN semantic s ON s.id = l.id
    )
    -- Final projection: join the fused scores back to `cached_jobs` (so
    -- the SETOF cached_jobs shape is returned) and order by the
    -- requested sort mode. 'relevance' uses the fused RRF score.
    SELECT cj.*
    FROM fused f
    JOIN public.cached_jobs cj ON cj.id = f.id
    ORDER BY
        CASE sort_mode
            WHEN 'newest'     THEN extract(epoch from cj.posted_at)
            WHEN 'oldest'     THEN -extract(epoch from cj.posted_at)
            WHEN 'company_az' THEN NULL  -- secondary key carries
            ELSE f.rrf_score  -- 'relevance' (default): fused RRF score
        END DESC NULLS LAST,
        -- Stable secondary keys to break ties — mirrors the Tier 1 RPC.
        CASE sort_mode WHEN 'company_az' THEN LOWER(cj.company) ELSE NULL END
            ASC NULLS LAST,
        cj.posted_at DESC NULLS LAST,
        cj.id DESC
    LIMIT GREATEST(1, LEAST(COALESCE(p_limit, 20), 50))
    OFFSET GREATEST(0, COALESCE(p_offset, 0));
END;
$function$;

-- service_role-only execute posture (mandatory — see header).
REVOKE ALL ON FUNCTION public.search_cached_jobs_hybrid(text,text,text[],boolean,integer,integer,text[],text[],text,integer,vector) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.search_cached_jobs_hybrid(text,text,text[],boolean,integer,integer,text[],text[],text,integer,vector) FROM anon;
REVOKE ALL ON FUNCTION public.search_cached_jobs_hybrid(text,text,text[],boolean,integer,integer,text[],text[],text,integer,vector) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.search_cached_jobs_hybrid(text,text,text[],boolean,integer,integer,text[],text[],text,integer,vector) TO service_role;
