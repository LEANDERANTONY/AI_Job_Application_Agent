import logging
import secrets

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request

from backend import quota
from backend.models import (
    JobResolveRequestModel,
    JobResolutionResponseModel,
    JobSearchRequestModel,
    JobSearchResponseModel,
)
from backend.observability import (
    CACHED_JOBS_HEALTHCHECK_MONITOR_CONFIG,
    CACHED_JOBS_HEALTHCHECK_MONITOR_SLUG,
    CACHED_JOBS_REFRESH_MONITOR_CONFIG,
    CACHED_JOBS_REFRESH_MONITOR_SLUG,
    capture_event,
    sentry_cron_monitor,
)
from backend.rate_limit import LIMIT_LLM, limiter
from backend.request_auth import get_optional_auth_tokens
from backend.services.auth_session_service import resolve_authenticated_context
from backend.services.job_cache_service import refresh_cached_jobs
from backend.services.job_search_service import JobSearchService, get_job_search_service
from backend.services.refresh_healthcheck_service import run_refresh_healthcheck
from backend.tiers import resolve_user_tier
from src.config import REFRESH_CACHE_SECRET
from src.errors import AppError
from src.logging_utils import get_logger, log_event


LOGGER = get_logger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/search", response_model=JobSearchResponseModel)
@limiter.limit(LIMIT_LLM)
def search_jobs(
    request: Request,
    payload: JobSearchRequestModel,
    live: bool = False,
    service: JobSearchService = Depends(get_job_search_service),
    auth_tokens=Depends(get_optional_auth_tokens),
):
    """Search the job pool.

    Default path (`live=false`): query the cached_jobs Supabase table
    via Postgres full-text -- ~30ms, no upstream load. The cache is
    refreshed every 4 hours by /admin/refresh-cache.

    Escape hatch (`?live=true`): bypass the cache and fan out to
    every configured Greenhouse / Lever board live. Slower (1-3s) and
    costs upstream rate-limit budget -- kept for debugging
    'why doesn't this job appear in the cache?' questions and as a
    fallback if the cache misbehaves.

    Quota gate (Step 6 of tier-enforcement):
      `job_searches` is monthly: Free 50 / Pro UNLIMITED /
      Business UNLIMITED. `check_and_increment` short-circuits when
      the tier cap equals UNLIMITED (-1), so Pro / Business never
      touch the counter row at all.

      No refund-on-failure here: job search is cheap (FTS read,
      30ms), and from the user's perspective an erroring search
      still consumed a "search intent." Charging it matches how the
      product surfaces results -- the search box accepted the
      query, results were returned (even if empty due to error),
      and the user can immediately try another. This is an
      intentional divergence from the assistant_turns /
      resume_parses / tailored_applications pattern, which gate
      LLM-cost-bearing actions where a failure means no work was
      actually done.
    """
    access_token, refresh_token = auth_tokens
    auth_context = None
    if access_token and refresh_token:
        try:
            auth_context = resolve_authenticated_context(
                access_token=access_token,
                refresh_token=refresh_token,
            )
        except AppError:
            # Same defensive fallback the streaming assistant uses:
            # an auth-resolve failure shouldn't block an anonymous
            # search flow. The user just doesn't get metered.
            auth_context = None

    app_user = getattr(auth_context, "app_user", None) if auth_context is not None else None
    tier = resolve_user_tier(app_user)
    quota_user_id = str(getattr(app_user, "id", "") or "") if app_user is not None else ""
    if quota_user_id:
        # Pro / Business have UNLIMITED job_searches; check_and_increment
        # short-circuits on UNLIMITED so the row write is skipped.
        # Free's cap of 50 enforces here; raising propagates to the
        # global QuotaExceededError handler -> canonical 429.
        quota.check_and_increment("job_searches", quota_user_id, tier)

    domain_query = payload.to_domain()
    result = service.search(domain_query) if live else service.search_cached(domain_query)
    # PostHog funnel event — the top of the job-application funnel.
    # Server-side capture, fire-and-forget; carries no PII (counts +
    # tier only). `quota_user_id` is "" for anonymous callers, which
    # capture_event maps to the "anonymous" distinct id.
    capture_event(
        distinct_id=quota_user_id,
        event="job_searched",
        properties={
            "mode": "live" if live else "cached",
            "result_count": len(getattr(result, "results", []) or []),
            "has_query": bool((payload.query or "").strip()),
            "tier": tier,
        },
    )
    return JobSearchResponseModel.from_domain(result)


@router.post("/resolve", response_model=JobResolutionResponseModel)
@limiter.limit(LIMIT_LLM)
def resolve_job_url(
    request: Request,
    payload: JobResolveRequestModel,
    service: JobSearchService = Depends(get_job_search_service),
):
    result = service.resolve_url(payload.url)
    return JobResolutionResponseModel.from_domain(result)


# ----- Admin: cached_jobs refresh ---------------------------------------
# Triggered by Supabase pg_cron via pg_net.http_post with the
# REFRESH_CACHE_SECRET as the bearer token. Not exposed to end users.
# Rate-limited too — even if the secret leaks, the per-IP limiter
# protects the upstream providers from being hammered.

admin_router = APIRouter(prefix="/admin", tags=["admin"])


def _verify_refresh_secret(authorization: str | None = Header(default=None)) -> None:
    """Bearer-token auth for admin endpoints.

    Constant-time comparison via secrets.compare_digest defends against
    timing oracles (probably overkill at our threat model but free).
    Returns 503 if the server has no REFRESH_CACHE_SECRET configured —
    we'd rather fail closed than open.
    """
    if not REFRESH_CACHE_SECRET:
        raise HTTPException(
            status_code=503,
            detail="Refresh-cache secret not configured on the server.",
        )
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token.")
    presented = authorization[len("bearer ") :].strip()
    if not secrets.compare_digest(presented, REFRESH_CACHE_SECRET):
        raise HTTPException(status_code=401, detail="Invalid refresh-cache token.")


def _run_cache_refresh_job() -> None:
    """Background-task body for ``POST /admin/refresh-cache``.

    The refresh fans out across ~130 ATS boards and runs for minutes —
    far longer than the upstream gateway will wait — so it runs here,
    after the endpoint has already returned 202. Running it inline made
    the gateway time the *response* out at ~100s and record a
    misleading ``524`` in the cron logs even though the refresh
    completed server-side.

    The Sentry ``cached-jobs-refresh`` check-in wraps THIS function,
    not the request, so its in_progress -> ok/error window reflects the
    real refresh duration. Never raises: a background task has no
    caller to surface an exception to, so any failure is recorded as an
    errored cron check-in plus an ERROR-level log (a Sentry issue via
    the LoggingIntegration) and swallowed. ``refresh_cached_jobs`` is
    itself crash-safe and idempotent — a failed run is recovered by the
    next 4-hourly tick.
    """
    try:
        with sentry_cron_monitor(
            CACHED_JOBS_REFRESH_MONITOR_SLUG,
            CACHED_JOBS_REFRESH_MONITOR_CONFIG,
        ):
            refresh_cached_jobs()
    except Exception as exc:  # noqa: BLE001 — background-task boundary
        log_event(
            LOGGER,
            logging.ERROR,
            "cached_jobs_refresh_background_failed",
            f"Background cached_jobs refresh failed: "
            f"{type(exc).__name__}: {exc}",
            error=f"{type(exc).__name__}: {exc}",
        )


@admin_router.post("/refresh-cache", status_code=202)
def refresh_cache(
    request: Request,
    background_tasks: BackgroundTasks,
    _: None = Depends(_verify_refresh_secret),
):
    """Trigger a cached_jobs refresh from all configured providers.

    Supabase pg_cron hits this every 4 hours (`0 */4 * * *`). The
    refresh fans out across ~130 ATS boards and runs for minutes —
    longer than the upstream gateway will wait — so the work is handed
    to a background task and the endpoint returns **202 Accepted**
    immediately. Running it synchronously made the gateway time the
    response out at ~100s and record a misleading `524` in the cron
    logs, even though the refresh completed server-side.

    The refresh outcome, its structured report, and the Sentry
    `cached-jobs-refresh` cron check-in are all produced by the
    background job — see `_run_cache_refresh_job`. A failed run
    surfaces as an errored Sentry check-in plus an ERROR-level issue;
    the daily `/admin/refresh-healthcheck` is the backstop.
    """
    background_tasks.add_task(_run_cache_refresh_job)
    return {
        "status": "accepted",
        "detail": "cached_jobs refresh started in the background.",
    }


@admin_router.post("/refresh-healthcheck")
def refresh_healthcheck(
    request: Request,
    _: None = Depends(_verify_refresh_secret),
):
    """Daily health check of the cached_jobs refresh pipeline.

    Supabase pg_cron hits this once a day (`0 6 * * *`). It does NOT
    refresh anything — it reads aggregate stats off cached_jobs and
    asserts the 4-hourly refresh is keeping the table healthy: recent,
    complete, every job board present, embeddings current, corpus not
    collapsed (see `run_refresh_healthcheck`).

    Two distinct signals come out of this endpoint:
      * The Sentry cron check-in (`cached-jobs-healthcheck`) — a
        missed / errored check-in means the healthcheck itself did not
        run.
      * A degraded result is logged at ERROR inside the service, which
        the Sentry LoggingIntegration raises as an issue. The endpoint
        still returns 200 with `overall: "degraded"` — the healthcheck
        DID run, so its cron monitor stays green; the ERROR issue is
        what pages the operator.

    The endpoint only 5xxs when the healthcheck genuinely could not
    run (store unconfigured, stats RPC unavailable).
    """
    try:
        with sentry_cron_monitor(
            CACHED_JOBS_HEALTHCHECK_MONITOR_SLUG,
            CACHED_JOBS_HEALTHCHECK_MONITOR_CONFIG,
        ):
            report = run_refresh_healthcheck()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return report
