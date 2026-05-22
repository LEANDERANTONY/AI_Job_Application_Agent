-- ===========================================================================
-- One-time setup for the cached_jobs daily refresh-healthcheck schedule.
--
-- WHAT THIS IS:
--   The cached_jobs cache is refreshed every 4 hours by the
--   `cached_jobs_refresh_4h` cron (see job_cache_cron_setup.sql). That
--   refresh is resilient — per-board failures are swallowed — so a slow
--   degradation never announces itself. This daily job calls
--   /api/admin/refresh-healthcheck, which reads aggregate stats off
--   cached_jobs and asserts the refresh is keeping the table healthy
--   (recent, complete, every board present, embeddings current, corpus
--   not collapsed). A degraded result is logged at ERROR and becomes a
--   Sentry issue; the endpoint also reports a Sentry cron check-in so a
--   healthcheck that never runs at all is caught too.
--
-- Prereqs:
--   - pg_cron + pg_net enabled (already done for the 4-hourly refresh).
--   - cached_jobs_health_stats RPC applied
--     (docs/sql/supabase-cached-jobs-health.sql).
--   - Backend deployed with the /api/admin/refresh-healthcheck endpoint.
--
-- HOW TO USE:
--   1. Replace the two placeholders below with YOUR values:
--        <BACKEND_BASE_URL>     e.g. https://api.job-application-copilot.xyz
--        <REFRESH_CACHE_SECRET> the same string set in the backend env
--        (the healthcheck endpoint reuses the refresh-cache bearer secret).
--   2. Paste the SELECT statements into the Supabase SQL Editor and run.
--      (Don't run this file as a migration — the schedule shouldn't be
--      tracked in version control, and cron.schedule is idempotent via
--      the unique 'jobname' string anyway.)
--
-- TO PAUSE:    SELECT cron.unschedule('cached_jobs_healthcheck_daily');
-- TO INSPECT:  SELECT * FROM cron.job WHERE jobname = 'cached_jobs_healthcheck_daily';
-- TO INSPECT RUNS: SELECT * FROM cron.job_run_details
--                  WHERE jobname = 'cached_jobs_healthcheck_daily'
--                  ORDER BY start_time DESC LIMIT 20;
-- ===========================================================================

-- 1. Schedule the healthcheck. Cron "0 6 * * *" = 06:00 UTC daily —
--    two hours after the 04:00 refresh, so the most recent refresh has
--    settled and its results are what the healthcheck reads.
SELECT cron.schedule(
    'cached_jobs_healthcheck_daily',
    '0 6 * * *',
    $$
    SELECT net.http_post(
        url := '<BACKEND_BASE_URL>/api/admin/refresh-healthcheck',
        headers := jsonb_build_object(
            'Authorization', 'Bearer <REFRESH_CACHE_SECRET>',
            'Content-Type', 'application/json'
        ),
        timeout_milliseconds := 60000  -- 1 min — healthcheck is a single RPC read
    );
    $$
);

-- 2. (Optional) Trigger an immediate healthcheck so you can confirm the
--    wiring without waiting for 06:00 UTC. Same SQL the cron will run.
SELECT net.http_post(
    url := '<BACKEND_BASE_URL>/api/admin/refresh-healthcheck',
    headers := jsonb_build_object(
        'Authorization', 'Bearer <REFRESH_CACHE_SECRET>',
        'Content-Type', 'application/json'
    ),
    timeout_milliseconds := 60000
);

-- 3. Verify the schedule landed.
SELECT jobname, schedule, command FROM cron.job
WHERE jobname = 'cached_jobs_healthcheck_daily';

-- ===========================================================================
-- TROUBLESHOOTING
--
-- Q: "The cron ran but I see no Sentry check-in."
-- A: The check-in fires from the backend when the endpoint runs. Check
--    `SELECT status, return_message FROM cron.job_run_details
--     WHERE jobname = 'cached_jobs_healthcheck_daily'
--     ORDER BY start_time DESC LIMIT 5;`
--      - 401: REFRESH_CACHE_SECRET mismatch.
--      - 503: backend missing SUPABASE_SERVICE_ROLE_KEY, or the
--             cached_jobs_health_stats RPC is not applied.
--      - 200 with overall=degraded: the healthcheck ran and FOUND a
--             problem — that surfaces as a Sentry *issue*, not a missed
--             check-in. The cron monitor itself stays green.
--
-- Q: "Sentry says the cached-jobs-healthcheck monitor missed a check-in."
-- A: pg_cron didn't fire, or the backend was unreachable. Check
--    cron.job_run_details as above and the VPS uptime.
-- ===========================================================================
