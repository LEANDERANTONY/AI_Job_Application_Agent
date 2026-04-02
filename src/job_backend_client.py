import requests

from src.config import JOB_BACKEND_BASE_URL
from src.errors import BackendIntegrationError


def _build_backend_url(path: str) -> str:
    base_url = str(JOB_BACKEND_BASE_URL or "").rstrip("/")
    suffix = "/" + str(path or "").lstrip("/")
    if not base_url:
        raise BackendIntegrationError("Job backend base URL is not configured.")
    return base_url + suffix


def resolve_job_url(url: str, timeout_seconds: int = 20) -> dict:
    normalized_url = str(url or "").strip()
    if not normalized_url:
        raise BackendIntegrationError("Add a job URL before trying to import it.")

    try:
        response = requests.post(
            _build_backend_url("/api/jobs/resolve"),
            json={"url": normalized_url},
            timeout=timeout_seconds,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise BackendIntegrationError(
            "The job backend could not resolve that URL right now.",
            details=str(exc),
        ) from exc

    payload = response.json()
    if not isinstance(payload, dict):
        raise BackendIntegrationError("The job backend returned an invalid response.")
    return payload


def search_jobs(
    *,
    query: str,
    location: str = "",
    remote_only: bool = False,
    posted_within_days: int | None = None,
    page_size: int = 12,
    source_filters: list[str] | None = None,
    timeout_seconds: int = 30,
) -> dict:
    normalized_query = str(query or "").strip()
    if not normalized_query:
        raise BackendIntegrationError("Add a search query before trying to find jobs.")

    payload = {
        "query": normalized_query,
        "location": str(location or "").strip(),
        "remote_only": bool(remote_only),
        "page_size": int(page_size),
        "source_filters": list(source_filters or []),
    }
    if posted_within_days is not None:
        payload["posted_within_days"] = int(posted_within_days)

    try:
        response = requests.post(
            _build_backend_url("/api/jobs/search"),
            json=payload,
            timeout=timeout_seconds,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise BackendIntegrationError(
            "The job backend could not search jobs right now.",
            details=str(exc),
        ) from exc

    response_payload = response.json()
    if not isinstance(response_payload, dict):
        raise BackendIntegrationError("The job backend returned an invalid search response.")
    return response_payload
