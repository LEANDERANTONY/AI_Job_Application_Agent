from fastapi import APIRouter, Depends

from backend.models import (
    JobResolveRequestModel,
    JobResolutionResponseModel,
    JobSearchRequestModel,
    JobSearchResponseModel,
)
from backend.services.job_search_service import JobSearchService, get_job_search_service


router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/search", response_model=JobSearchResponseModel)
def search_jobs(
    payload: JobSearchRequestModel,
    service: JobSearchService = Depends(get_job_search_service),
):
    result = service.search(payload.to_domain())
    return JobSearchResponseModel.from_domain(result)


@router.post("/resolve", response_model=JobResolutionResponseModel)
def resolve_job_url(
    payload: JobResolveRequestModel,
    service: JobSearchService = Depends(get_job_search_service),
):
    result = service.resolve_url(payload.url)
    return JobResolutionResponseModel.from_domain(result)
