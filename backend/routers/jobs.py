import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from backend.models import (
    JobResolveRequestModel,
    JobResolutionResponseModel,
    JobSearchRequestModel,
    JobSearchResponseModel,
)
from backend.rate_limit import LIMIT_LLM, limiter
from backend.services.job_cache_service import refresh_cached_jobs
from backend.services.job_search_service import JobSearchService, get_job_search_service
from src.config import REFRESH_CACHE_SECRET


router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/search", response_model=JobSearchResponseModel)
@limiter.limit(LIMIT_LLM)
def search_jobs(
    request: Request,
    payload: JobSearchRequestModel,
    service: JobSearchService = Depends(get_job_search_service),
):
    result = service.search(payload.to_domain())
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


@admin_router.post("/refresh-cache")
def refresh_cache(
    request: Request,
    _: None = Depends(_verify_refresh_secret),
):
    """Refresh cached_jobs from all configured providers.

    This is what Supabase pg_cron hits every 30 min. Returns the
    structured refresh report (see `refresh_cached_jobs`) so cron
    output can be inspected when something goes wrong.
    """
    try:
        report = refresh_cached_jobs()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return report
