from pathlib import Path

from src.config import DEMO_JOB_DESCRIPTION_DIR
from src.schemas import JobPosting, JobResolutionResult, JobSearchQuery, JobSourceSearchResponse
from src.services.job_service import build_job_description_from_text
from src.job_sources.base import JobSourceAdapter


class DemoJobSourceAdapter(JobSourceAdapter):
    source_name = "demo"

    def __init__(self, base_dir: Path | None = None):
        self._base_dir = base_dir or DEMO_JOB_DESCRIPTION_DIR

    def search(self, query: JobSearchQuery) -> JobSourceSearchResponse:
        normalized_query = str(query.query or "").strip().lower()
        normalized_location = str(query.location or "").strip().lower()
        postings: list[JobPosting] = []

        if not self._base_dir.exists():
            return JobSourceSearchResponse(
                source=self.source_name,
                status="unavailable",
                error_message="Demo job source directory is missing.",
            )

        for job_file in sorted(self._base_dir.iterdir()):
            if not job_file.is_file() or job_file.suffix.lower() not in {".txt", ".pdf", ".docx"}:
                continue
            try:
                raw_text = job_file.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            except OSError as exc:
                return JobSourceSearchResponse(
                    source=self.source_name,
                    status="error",
                    error_message=str(exc),
                )

            job_description = build_job_description_from_text(raw_text)
            haystack = " ".join(
                [
                    job_description.title,
                    job_description.location or "",
                    " ".join(job_description.requirements.hard_skills),
                    raw_text,
                ]
            ).lower()
            if normalized_query and normalized_query not in haystack:
                continue
            if normalized_location and normalized_location not in haystack:
                continue

            postings.append(
                JobPosting(
                    id="demo:{name}".format(name=job_file.stem),
                    source=self.source_name,
                    title=job_description.title,
                    company="Demo Company",
                    location=job_description.location or "",
                    employment_type="",
                    url="file://{path}".format(path=job_file.name),
                    summary=(job_description.cleaned_text.splitlines() or [""])[0][:220],
                    description_text=job_description.cleaned_text,
                    metadata={
                        "file_name": job_file.name,
                        "experience_requirement": job_description.requirements.experience_requirement or "",
                        "skills": list(job_description.requirements.hard_skills),
                    },
                )
            )
            if len(postings) >= max(1, min(int(query.page_size or 20), 50)):
                break

        return JobSourceSearchResponse(
            source=self.source_name,
            results=postings,
            status="ok",
        )

    def can_resolve_url(self, url: str) -> bool:
        return str(url or "").strip().lower().startswith("file://")

    def resolve_url(self, url: str) -> JobResolutionResult:
        return JobResolutionResult(
            source=self.source_name,
            status="unsupported",
            error_message="Demo source does not resolve external URLs.",
        )
