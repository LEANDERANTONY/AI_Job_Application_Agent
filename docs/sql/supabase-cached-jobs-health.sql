-- ---------------------------------------------------------------------------
-- cached_jobs_health_stats — aggregate health snapshot for cached_jobs
-- ---------------------------------------------------------------------------
-- Powers the daily refresh healthcheck
-- (backend/services/refresh_healthcheck_service.py, reached via
-- /api/admin/refresh-healthcheck). The cached_jobs cache is refreshed
-- every 4 hours by a worker built to be resilient — per-board HTTP
-- failures are swallowed so one dead board never poisons a whole
-- refresh. The flip side: a SLOW degradation never announces itself (a
-- board that quietly returns zero jobs, an embed-on-write backlog, a
-- pg_cron schedule that stopped firing). This RPC is the read side of
-- the healthcheck that closes that gap: it computes every aggregate the
-- checks need in ONE round trip, so the backend never ships a ~14k-row
-- table over the wire just to count it.
--
-- RETURNS a single jsonb object:
--   {
--     "checked_at":           timestamptz,  -- now()
--     "stale_after_hours":    integer,      -- the threshold actually used
--     "total_active":         integer,      -- rows with removed_at IS NULL
--     "newest_last_seen_at":  timestamptz,  -- max(last_seen_at)
--     "oldest_last_seen_at":  timestamptz,  -- min(last_seen_at)
--     "stale_count":          integer,      -- active rows not re-seen
--                                           --   within p_stale_after_hours
--     "null_embedding_count": integer|null, -- active rows, embedding IS NULL
--                                           --   JSON null in LEAN MODE (see below)
--     "per_source":           { "<source>": <active row count>, ... }
--   }
-- max/min are JSON null when the table is empty — the caller treats a
-- missing newest_last_seen_at as a failed check, not a silent pass.
--
-- PARAM:
--   p_stale_after_hours integer DEFAULT 5 — a row whose last_seen_at is
--     older than this counts toward stale_count. The refresh runs every
--     4h, so 5h means "missed at least one refresh". Floored at 1.
--
-- ---------------------------------------------------------------------------
-- LEAN/FULL MODE COMPATIBILITY — why this is plpgsql and not plain SQL
-- ---------------------------------------------------------------------------
-- `cached_jobs.embedding` is the Tier 2 semantic column: it EXISTS in full
-- mode and is DROPPED in lean mode (supabase-cached-jobs-lean-mode.sql).
-- The original version of this function was `LANGUAGE sql` with a literal
-- `count(*) FILTER (WHERE cj.embedding IS NULL)`. When lean mode dropped
-- the column on 2026-06-23, that reference became unresolvable and EVERY
-- daily healthcheck failed with:
--
--     APIError: column cj.embedding does not exist
--   → AppError: Failed to query cached_jobs health stats.
--   → HTTP 503 from /admin/refresh-healthcheck
--
-- ...which is Sentry JOBAGENT-BACKEND-7 (the 503) and -8 (the missed cron
-- check-in), failing daily from 2026-06-24 until 2026-07-21. See DEVLOG
-- Day 83.
--
-- The fix: probe `information_schema.columns` for the column and read the
-- NULL count through DYNAMIC SQL, so the function body PARSES in both
-- modes. `null_embedding_count` is a real count in full mode and JSON
-- null in lean mode. The backend already tolerates this — its
-- `embeddings_healthy` check is skipped entirely when
-- JOB_SEARCH_HYBRID_ENABLED=false, and `_as_int(None)` coerces to 0.
--
-- CONSEQUENCE: this ONE function is valid in BOTH modes, so neither the
-- lean-mode downgrade nor the restore-to-Pro upgrade needs to swap it.
-- Any FUTURE function that references `cached_jobs.embedding` must either
-- follow this probe pattern or be added to the lean-mode drop/recreate
-- pair — a plain-SQL reference to that column is a lean-mode landmine.
--
-- READ-ONLY: this function only SELECTs. It never mutates cached_jobs.
--
-- SECURITY: SECURITY DEFINER + `SET search_path = public`. EXECUTE
-- granted ONLY to service_role — NOT anon/authenticated/PUBLIC. Mirrors
-- the search RPCs and the project-wide posture for SECURITY DEFINER
-- functions. The DROP+CREATE re-introduces Postgres's implicit
-- EXECUTE-to-PUBLIC, so the REVOKEs below are mandatory.
--
-- IDEMPOTENT: DROP FUNCTION IF EXISTS + CREATE so re-applying reproduces
-- the exact state.
-- ---------------------------------------------------------------------------

DROP FUNCTION IF EXISTS public.cached_jobs_health_stats(integer);

CREATE OR REPLACE FUNCTION public.cached_jobs_health_stats(
    p_stale_after_hours integer DEFAULT 5
)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
DECLARE
    v_null_embedding_count bigint := NULL;
    v_result jsonb;
BEGIN
    -- Tier 2 is optional: the embedding column exists in full mode and
    -- is dropped in lean mode. Only count NULL embeddings when present
    -- (dynamic SQL so this function parses in both modes).
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'cached_jobs'
          AND column_name = 'embedding'
    ) THEN
        EXECUTE 'SELECT count(*) FROM public.cached_jobs
                 WHERE removed_at IS NULL AND embedding IS NULL'
        INTO v_null_embedding_count;
    END IF;

    SELECT jsonb_build_object(
        'checked_at',           now(),
        'stale_after_hours',    GREATEST(1, COALESCE(p_stale_after_hours, 5)),
        'total_active',         count(*),
        'newest_last_seen_at',  max(cj.last_seen_at),
        'oldest_last_seen_at',  min(cj.last_seen_at),
        -- A row's last_seen_at is rewritten by every refresh that still
        -- sees it upstream; one older than the threshold was missed by
        -- at least one refresh.
        'stale_count',          count(*) FILTER (
            WHERE cj.last_seen_at < now()
                  - (GREATEST(1, COALESCE(p_stale_after_hours, 5)) || ' hours')::interval
        ),
        -- NULL (not 0) in lean mode — "not measured", not "none missing".
        'null_embedding_count', v_null_embedding_count,
        -- per-source active row counts -> { "greenhouse": 9241, ... }.
        -- COALESCE so an empty table yields {} rather than JSON null.
        'per_source',           COALESCE(
            (
                SELECT jsonb_object_agg(s.source, s.cnt)
                FROM (
                    SELECT source, count(*) AS cnt
                    FROM public.cached_jobs
                    WHERE removed_at IS NULL
                    GROUP BY source
                ) s
            ),
            '{}'::jsonb
        )
    )
    INTO v_result
    FROM public.cached_jobs cj
    WHERE cj.removed_at IS NULL;

    RETURN v_result;
END;
$function$;

-- service_role-only execute posture (mandatory — see header).
REVOKE ALL ON FUNCTION public.cached_jobs_health_stats(integer) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.cached_jobs_health_stats(integer) FROM anon;
REVOKE ALL ON FUNCTION public.cached_jobs_health_stats(integer) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.cached_jobs_health_stats(integer) TO service_role;
