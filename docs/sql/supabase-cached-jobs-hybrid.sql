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
-- PREREQUISITES (operator must do these first — see DEVLOG Day 69
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
-- p_query = no lexical filter.
--
-- RRF FUSION: for each job, with k = 60 (the standard RRF constant):
--     rrf = 1.0/(k + lexical_rank) + 1.0/(k + semantic_rank)
--   - lexical_rank: 1-based rank by ts_rank DESC among lexical matches.
--   - semantic_rank: 1-based rank by cosine distance ASC among rows that
--     have an embedding.
--   - A job present in only ONE ranked list contributes ONLY that list's
--     term (the other term is 0) — implemented via a FULL OUTER JOIN and
--     treating a missing rank's term as 0.
--
-- DEGENERATE CASES (all must still return sensible rows):
--   - empty p_query                -> lexical list is "all filtered rows"
--                                     unranked-by-text; effectively the
--                                     semantic ranking (or recency)
--                                     drives ordering. No to_tsquery call.
--   - NULL p_query_embedding       -> semantic list empty; pure lexical.
--   - both empty/NULL              -> filtered rows ordered by recency
--                                     (same as browse mode).
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
    rrf_k         CONSTANT integer := 60;
BEGIN
    IF has_query THEN
        -- Same contract as the Tier 1 RPC: p_query is a to_tsquery-
        -- syntax string from the backend synonym expander, not raw
        -- user text.
        tsquery_obj := to_tsquery('english', p_query);
    END IF;

    RETURN QUERY
    -- ----------------------------------------------------------------
    -- candidates: every row that survives the (non-text, non-vector)
    -- FILTERS. Both ranked lists below draw from this same pool, so a
    -- job's rank reflects its standing among ELIGIBLE jobs only.
    -- ----------------------------------------------------------------
    WITH candidates AS (
        SELECT cj.*
        FROM public.cached_jobs cj
        WHERE cj.removed_at IS NULL
          AND (
              COALESCE(p_location, '') = ''
              OR cj.location ILIKE '%' || p_location || '%'
          )
          AND (
              p_sources IS NULL
              OR cardinality(p_sources) = 0
              OR cj.source = ANY (p_sources)
          )
          AND (NOT p_remote_only OR cj.work_mode = 'remote')
          AND (
              p_work_modes IS NULL
              OR cardinality(p_work_modes) = 0
              OR cj.work_mode = ANY (p_work_modes)
          )
          AND (
              p_employment_types IS NULL
              OR cardinality(p_employment_types) = 0
              OR cj.employment_type_norm = ANY (p_employment_types)
          )
          AND (
              p_posted_within_days IS NULL
              OR cj.posted_at > NOW() - (p_posted_within_days || ' days')::INTERVAL
          )
    ),
    -- ----------------------------------------------------------------
    -- lexical: 1-based rank by ts_rank DESC among rows whose tsvector
    -- matches the query. When p_query is empty there is no FTS filter
    -- and no meaningful text rank — every candidate is included with a
    -- NULL lexical_rank so it contributes 0 to the lexical RRF term
    -- (its placement then comes from the semantic side / recency).
    -- ----------------------------------------------------------------
    lexical AS (
        SELECT
            c.id,
            CASE
                WHEN has_query
                THEN row_number() OVER (
                    ORDER BY ts_rank(c.search_tsv, tsquery_obj) DESC,
                             c.posted_at DESC NULLS LAST,
                             c.id
                )
                ELSE NULL::bigint
            END AS lexical_rank
        FROM candidates c
        WHERE NOT has_query OR c.search_tsv @@ tsquery_obj
    ),
    -- ----------------------------------------------------------------
    -- semantic: 1-based rank by cosine distance ASC among candidates
    -- that HAVE an embedding. Empty when p_query_embedding is NULL ->
    -- pure-lexical fallback. `<=>` is pgvector cosine distance; the
    -- HNSW vector_cosine_ops index from the pgvector schema file
    -- accelerates this ordering.
    -- ----------------------------------------------------------------
    semantic AS (
        SELECT
            c.id,
            row_number() OVER (
                ORDER BY c.embedding <=> p_query_embedding,
                         c.posted_at DESC NULLS LAST,
                         c.id
            ) AS semantic_rank
        FROM candidates c
        WHERE has_embedding
          AND c.embedding IS NOT NULL
    ),
    -- ----------------------------------------------------------------
    -- fused: FULL OUTER JOIN the two ranked lists so a job appearing in
    -- only one still survives. RRF score sums the per-list terms; a
    -- missing rank contributes 0 (COALESCE(..., 0.0)).
    -- ----------------------------------------------------------------
    fused AS (
        SELECT
            COALESCE(l.id, s.id) AS id,
            COALESCE(
                CASE WHEN l.lexical_rank IS NOT NULL
                     THEN 1.0 / (rrf_k + l.lexical_rank)
                     ELSE 0.0 END,
                0.0
            )
            +
            COALESCE(
                CASE WHEN s.semantic_rank IS NOT NULL
                     THEN 1.0 / (rrf_k + s.semantic_rank)
                     ELSE 0.0 END,
                0.0
            ) AS rrf_score
        FROM lexical l
        FULL OUTER JOIN semantic s ON s.id = l.id
    )
    -- ----------------------------------------------------------------
    -- Final projection: join the fused scores back to the candidate
    -- rows (so the SETOF cached_jobs shape is returned) and order by
    -- the requested sort mode. 'relevance' uses the RRF score.
    -- ----------------------------------------------------------------
    SELECT c.*
    FROM fused f
    JOIN candidates c ON c.id = f.id
    ORDER BY
        CASE sort_mode
            WHEN 'newest'     THEN extract(epoch from c.posted_at)
            WHEN 'oldest'     THEN -extract(epoch from c.posted_at)
            WHEN 'company_az' THEN NULL  -- secondary key carries
            ELSE f.rrf_score  -- 'relevance' (default): fused RRF score
        END DESC NULLS LAST,
        -- Stable secondary keys to break ties — mirrors the Tier 1 RPC.
        CASE sort_mode WHEN 'company_az' THEN LOWER(c.company) ELSE NULL END
            ASC NULLS LAST,
        c.posted_at DESC NULLS LAST,
        c.id DESC
    LIMIT GREATEST(1, LEAST(COALESCE(p_limit, 20), 50))
    OFFSET GREATEST(0, COALESCE(p_offset, 0));
END;
$function$;

-- service_role-only execute posture (mandatory — see header).
REVOKE ALL ON FUNCTION public.search_cached_jobs_hybrid(text,text,text[],boolean,integer,integer,text[],text[],text,integer,vector) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.search_cached_jobs_hybrid(text,text,text[],boolean,integer,integer,text[],text[],text,integer,vector) FROM anon;
REVOKE ALL ON FUNCTION public.search_cached_jobs_hybrid(text,text,text[],boolean,integer,integer,text[],text[],text,integer,vector) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.search_cached_jobs_hybrid(text,text,text[],boolean,integer,integer,text[],text[],text,integer,vector) TO service_role;
