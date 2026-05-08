-- ===========================================================================
-- One-time setup for the cached_jobs 30-minute refresh schedule.
--
-- Prereqs (already done by migrations):
--   - pg_cron extension installed (Supabase enables by default).
--   - pg_net extension enabled (see migration enable_pg_net_for_cached_jobs_cron).
--   - cached_jobs table exists (see migration create_cached_jobs_table).
--   - Backend deployed with REFRESH_CACHE_SECRET + SUPABASE_SERVICE_ROLE_KEY
--     in env, and the /api/admin/refresh-cache endpoint responding.
--
-- HOW TO USE:
--   1. Replace the two placeholders below with YOUR values:
--        <BACKEND_BASE_URL>    e.g. https://api.job-application-copilot.xyz
--        <REFRESH_CACHE_SECRET> e.g. the same string you set in backend env
--   2. Paste the SELECT statements into the Supabase SQL Editor and run.
--      (Don't run this file as a migration — the schedule shouldn't be
--      tracked in version control, and the schedule call is idempotent
--      via the unique 'jobname' string anyway.)
--
-- TO PAUSE:    SELECT cron.unschedule('cached_jobs_refresh_30min');
-- TO INSPECT:  SELECT * FROM cron.job;
-- TO INSPECT RUNS: SELECT * FROM cron.job_run_details
--                  WHERE jobname = 'cached_jobs_refresh_30min'
--                  ORDER BY start_time DESC LIMIT 20;
-- ===========================================================================

-- 1. Schedule the refresh.  Cron expression: "*/30 * * * *" = every 30 min.
SELECT cron.schedule(
    'cached_jobs_refresh_30min',
    '*/30 * * * *',
    $$
    SELECT net.http_post(
        url := '<BACKEND_BASE_URL>/api/admin/refresh-cache',
        headers := jsonb_build_object(
            'Authorization', 'Bearer <REFRESH_CACHE_SECRET>',
            'Content-Type', 'application/json'
        ),
        timeout_milliseconds := 120000  -- 2 min — refresh can take a minute on a 100+ board run
    );
    $$
);

-- 2. (Optional) Trigger an immediate first refresh so the cache has data
--    before waiting for the next 30-min tick. Same SQL the cron will run.
SELECT net.http_post(
    url := '<BACKEND_BASE_URL>/api/admin/refresh-cache',
    headers := jsonb_build_object(
        'Authorization', 'Bearer <REFRESH_CACHE_SECRET>',
        'Content-Type', 'application/json'
    ),
    timeout_milliseconds := 120000
);

-- 3. Verify the schedule landed.
SELECT jobname, schedule, command FROM cron.job WHERE jobname = 'cached_jobs_refresh_30min';

-- ===========================================================================
-- TROUBLESHOOTING
--
-- Q: "I scheduled it but nothing's in cached_jobs."
-- A: Check `SELECT * FROM cron.job_run_details
--    WHERE jobname = 'cached_jobs_refresh_30min'
--    ORDER BY start_time DESC LIMIT 5;`
--    Look at status + return_message. Common causes:
--      - 401: REFRESH_CACHE_SECRET mismatch. Re-run with the right token.
--      - 503: backend env missing SUPABASE_SERVICE_ROLE_KEY.
--      - timeout: BACKEND_BASE_URL wrong, or backend cold-starting; bump
--        timeout_milliseconds.
--
-- Q: "How do I roll back to live fan-out per request?"
-- A: SELECT cron.unschedule('cached_jobs_refresh_30min');
--    The /jobs/search endpoint already supports `?live=true` for
--    cache-bypass. As long as the cache stops getting refreshed it'll
--    eventually empty itself out via the smart cleanup, OR you can
--    truncate manually: TRUNCATE TABLE public.cached_jobs;
-- ===========================================================================
