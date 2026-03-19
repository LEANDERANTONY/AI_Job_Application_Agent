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
