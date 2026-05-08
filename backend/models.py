from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.schemas import JobPosting, JobResolutionResult, JobSearchQuery, JobSearchResult


class JobSearchRequestModel(BaseModel):
    query: str = Field(min_length=1, max_length=200)
    location: str = Field(default="", max_length=200)
    source_filters: list[str] = Field(default_factory=list)
    remote_only: bool = False
    posted_within_days: int | None = Field(default=None, ge=1, le=30)
    page_size: int = Field(default=20, ge=1, le=50)
    # New filter dropdowns. work_modes is multi-select among
    # ('remote', 'hybrid', 'onsite'). employment_types is multi-
    # select among ('fulltime', 'parttime', 'contract', 'internship',
    # 'temporary'). Empty list = no filter applied (all values pass).
    work_modes: list[str] = Field(default_factory=list)
    employment_types: list[str] = Field(default_factory=list)
    # Single-select sort. 'relevance' (default — ts_rank then
    # posted_at), 'newest' (posted_at DESC), 'oldest' (posted_at
    # ASC), 'company_az' (alphabetical company). Unknown values
    # coerce to 'relevance' downstream.
    sort_by: str = Field(default="relevance", max_length=32)

    @field_validator("query", "location", mode="before")
    @classmethod
    def _strip_text(cls, value):
        return str(value or "").strip()

    @field_validator("query")
    @classmethod
    def _require_non_blank_query(cls, value: str):
        if not value.strip():
            raise ValueError("query must not be blank")
        return value

    @field_validator("source_filters", mode="before")
    @classmethod
    def _normalize_source_filters(cls, value):
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("source_filters must be a list")
        return [str(item).strip().lower() for item in value if str(item).strip()]

    @field_validator("work_modes", "employment_types", mode="before")
    @classmethod
    def _normalize_dropdown_list(cls, value):
        # Same pattern as source_filters — accept a list of strings,
        # lower-case + strip empties. Whitelisting against the
        # allowed-values set happens in CachedJobsStore.search()
        # so the schema layer stays decoupled from RPC vocabulary.
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("must be a list of strings")
        return [str(item).strip().lower() for item in value if str(item).strip()]

    @field_validator("sort_by", mode="before")
    @classmethod
    def _normalize_sort_by(cls, value):
        return str(value or "relevance").strip().lower() or "relevance"

    def to_domain(self) -> JobSearchQuery:
        return JobSearchQuery(
            query=self.query,
            location=self.location,
            source_filters=self.source_filters,
            remote_only=self.remote_only,
            posted_within_days=self.posted_within_days,
            page_size=self.page_size,
            work_modes=self.work_modes,
            employment_types=self.employment_types,
            sort_by=self.sort_by,
        )


class JobPostingModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source: str
    title: str
    company: str
    location: str = ""
    employment_type: str = ""
    url: str = ""
    summary: str = ""
    description_text: str = ""
    posted_at: str = ""
    scraped_at: str = ""
    metadata: dict = Field(default_factory=dict)

    @classmethod
    def from_domain(cls, posting: JobPosting) -> "JobPostingModel":
        return cls(**posting.__dict__)


class JobSearchResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: JobSearchRequestModel
    results: list[JobPostingModel] = Field(default_factory=list)
    total_results: int = 0
    source_status: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def from_domain(cls, result: JobSearchResult) -> "JobSearchResponseModel":
        return cls(
            query=JobSearchRequestModel.model_validate(result.query.__dict__),
            results=[JobPostingModel.from_domain(item) for item in result.results],
            total_results=result.total_results,
            source_status=dict(result.source_status),
        )


class JobResolveRequestModel(BaseModel):
    url: str = Field(min_length=1, max_length=500)

    @field_validator("url", mode="before")
    @classmethod
    def _strip_url(cls, value):
        return str(value or "").strip()

    @field_validator("url")
    @classmethod
    def _require_non_blank_url(cls, value: str):
        if not value.strip():
            raise ValueError("url must not be blank")
        return value


class JobResolutionResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    status: str
    job_posting: JobPostingModel | None = None
    error_message: str = ""
    source_details: dict[str, str] = Field(default_factory=dict)

    @classmethod
    def from_domain(cls, result: JobResolutionResult) -> "JobResolutionResponseModel":
        return cls(
            source=result.source,
            status=result.status,
            job_posting=None if result.job_posting is None else JobPostingModel.from_domain(result.job_posting),
            error_message=result.error_message,
            source_details=dict(result.source_details),
        )
