-- ---------------------------------------------------------------------------
-- search_cached_jobs_ranked — ranked job search RPC over public.cached_jobs
-- ---------------------------------------------------------------------------
-- Source of truth for the ranked-search Postgres function the backend calls
-- via `src/cached_jobs_store.py` (PostgREST `rpc('search_cached_jobs_ranked')`).
--
-- Provenance: this function originally lived ONLY in the Supabase database
-- (it predated the docs/sql tracking convention — a governance gap). It is
-- now tracked here. Re-running this file is idempotent and reproduces the
-- exact production state, INCLUDING the security posture.
--
-- 2026-05-17: added `p_offset` (DEFAULT 0) + the `OFFSET` clause so the
-- frontend "Load more" can paginate the ~14.7k-row corpus. Page size stays
-- hard-capped at 50 via `LEAST(p_limit, 50)`; p_offset advances the window.
-- Applied to prod as migrations `search_cached_jobs_ranked_add_p_offset`
-- and `search_cached_jobs_ranked_restore_service_role_only`.
--
-- 2026-05-21: parse `p_query` with `to_tsquery` instead of
-- `websearch_to_tsquery`. The backend now expands synonyms /
-- abbreviations in `src/job_search_synonyms.py` and passes a
-- `to_tsquery`-syntax string (e.g.
-- `(ml | machine<->learning) & (engineer | developer | dev)`).
-- `websearch_to_tsquery` cannot express that grouping — it has no
-- parentheses and binds OR with the wrong precedence — so the RPC
-- must use `to_tsquery`. `p_query` is therefore a pre-built tsquery
-- expression, NOT raw user text; `src/cached_jobs_store.py` is the
-- only caller and always runs `expand_query` first. NOTE: this
-- function change and the app code MUST deploy together — applying
-- this migration while the old app code still sends raw user text
-- breaks search (raw text with stray `:`/`&`/`(` makes `to_tsquery`
-- raise). The empty-`p_query` short-circuit below is unchanged, so
-- "browse recent jobs" still works.
--
-- SECURITY: SECURITY DEFINER + `SET search_path = public`. EXECUTE is granted
-- ONLY to `service_role` (the backend uses the service-role client) — NOT to
-- anon/authenticated/PUBLIC. This matches the project-wide posture for
-- SECURITY DEFINER functions (see ADR-021). The DROP+CREATE below would
-- otherwise re-introduce Postgres's implicit EXECUTE-to-PUBLIC, so the
-- REVOKEs are mandatory and part of the canonical definition.
-- ---------------------------------------------------------------------------

-- Drop BOTH the legacy 9-arg signature (pre-offset) and the current 10-arg
-- one so this file re-applies cleanly regardless of which version exists.
DROP FUNCTION IF EXISTS public.search_cached_jobs_ranked(text,text,text[],boolean,integer,integer,text[],text[],text);
DROP FUNCTION IF EXISTS public.search_cached_jobs_ranked(text,text,text[],boolean,integer,integer,text[],text[],text,integer);

CREATE OR REPLACE FUNCTION public.search_cached_jobs_ranked(
    p_query text DEFAULT ''::text,
    p_location text DEFAULT ''::text,
    p_sources text[] DEFAULT NULL::text[],
    p_remote_only boolean DEFAULT false,
    p_posted_within_days integer DEFAULT NULL::integer,
    p_limit integer DEFAULT 20,
    p_work_modes text[] DEFAULT NULL::text[],
    p_employment_types text[] DEFAULT NULL::text[],
    p_sort_by text DEFAULT 'relevance'::text,
    p_offset integer DEFAULT 0
)
 RETURNS SETOF cached_jobs
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
DECLARE
    tsquery_obj tsquery;
    has_query   BOOLEAN := COALESCE(p_query, '') <> '';
    sort_mode   TEXT    := LOWER(COALESCE(p_sort_by, 'relevance'));
BEGIN
    IF has_query THEN
        -- p_query is a to_tsquery-syntax string built by the backend's
        -- synonym expander (src/job_search_synonyms.py) — NOT raw user
        -- text. websearch_to_tsquery can't express the `(a|b)&c`
        -- grouping the expander emits, so to_tsquery is required.
        tsquery_obj := to_tsquery('english', p_query);
    END IF;

    RETURN QUERY
    SELECT cj.*
    FROM public.cached_jobs cj
    WHERE cj.removed_at IS NULL
      AND (NOT has_query OR cj.search_tsv @@ tsquery_obj)
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
    ORDER BY
        -- Branch on the sort_mode so each mode picks the right key.
        -- The CASE wraps in a subexpression Postgres can specialize.
        CASE sort_mode
            WHEN 'newest'     THEN extract(epoch from cj.posted_at)
            WHEN 'oldest'     THEN -extract(epoch from cj.posted_at)
            WHEN 'company_az' THEN NULL  -- secondary key carries
            ELSE
                CASE WHEN has_query
                     THEN ts_rank(cj.search_tsv, tsquery_obj)::double precision
                     ELSE extract(epoch from cj.posted_at)
                END
        END DESC NULLS LAST,
        -- Stable secondary keys to break ties:
        CASE sort_mode WHEN 'company_az' THEN LOWER(cj.company) ELSE NULL END
            ASC NULLS LAST,
        cj.posted_at DESC NULLS LAST
    LIMIT GREATEST(1, LEAST(COALESCE(p_limit, 20), 50))
    OFFSET GREATEST(0, COALESCE(p_offset, 0));
END;
$function$;

-- service_role-only execute posture (mandatory — see header).
REVOKE ALL ON FUNCTION public.search_cached_jobs_ranked(text,text,text[],boolean,integer,integer,text[],text[],text,integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.search_cached_jobs_ranked(text,text,text[],boolean,integer,integer,text[],text[],text,integer) FROM anon;
REVOKE ALL ON FUNCTION public.search_cached_jobs_ranked(text,text,text[],boolean,integer,integer,text[],text[],text,integer) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.search_cached_jobs_ranked(text,text,text[],boolean,integer,integer,text[],text[],text,integer) TO service_role;
