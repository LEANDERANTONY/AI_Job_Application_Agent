from fastapi import APIRouter, Depends, Request

from backend.models import (
    JobResolveRequestModel,
    JobResolutionResponseModel,
    JobSearchRequestModel,
    JobSearchResponseModel,
)
from backend.rate_limit import LIMIT_LLM, limiter
from backend.services.job_search_service import JobSearchService, get_job_search_service


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
