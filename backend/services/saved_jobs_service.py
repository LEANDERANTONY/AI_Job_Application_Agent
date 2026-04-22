from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from backend.services.auth_session_service import resolve_authenticated_context
from src.errors import InputValidationError
from src.saved_jobs_store import SavedJobsStore


def _serialize(value: Any):
    if is_dataclass(value):
        return {key: _serialize(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


def _saved_job_sort_key(job_posting: dict[str, Any]):
    return (
        str(job_posting.get("saved_at", "") or ""),
        str(job_posting.get("posted_at", "") or ""),
        str(job_posting.get("title", "") or "").lower(),
    )


def _normalize_saved_job(payload: dict[str, Any] | Any):
    raw_payload = _serialize(payload)
    metadata = raw_payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    return {
        "id": str(raw_payload.get("job_id", raw_payload.get("id", "")) or ""),
        "source": str(raw_payload.get("source", "") or ""),
        "title": str(raw_payload.get("title", "") or ""),
        "company": str(raw_payload.get("company", "") or ""),
        "location": str(raw_payload.get("location", "") or ""),
        "employment_type": str(raw_payload.get("employment_type", "") or ""),
        "url": str(raw_payload.get("url", "") or ""),
        "summary": str(raw_payload.get("summary", "") or ""),
        "description_text": str(raw_payload.get("description_text", "") or ""),
        "posted_at": str(raw_payload.get("posted_at", "") or ""),
        "scraped_at": str(raw_payload.get("scraped_at", "") or ""),
        "metadata": metadata,
        "saved_at": str(raw_payload.get("saved_at", "") or ""),
        "updated_at": str(raw_payload.get("updated_at", "") or ""),
    }


def list_saved_jobs(*, access_token: str, refresh_token: str):
    context = resolve_authenticated_context(
        access_token=access_token,
        refresh_token=refresh_token,
    )
    saved_jobs_store = SavedJobsStore(context.auth_service)
    if not saved_jobs_store.is_configured():
        raise RuntimeError("Saved jobs persistence is not configured.")

    saved_jobs = [
        _normalize_saved_job(item)
        for item in saved_jobs_store.list_jobs(
            access_token,
            refresh_token,
            context.app_user.id,
        )
    ]
    saved_jobs.sort(key=_saved_job_sort_key, reverse=True)

    latest_saved_at = ""
    for item in saved_jobs:
        saved_at = str(item.get("saved_at", "") or "").strip()
        if saved_at:
            latest_saved_at = max(latest_saved_at, saved_at)

    return {
        "status": "available",
        "saved_jobs": saved_jobs,
        "total_saved_jobs": len(saved_jobs),
        "latest_saved_at": latest_saved_at,
    }


def save_saved_job(
    *,
    access_token: str,
    refresh_token: str,
    job_posting: dict[str, Any] | None,
):
    normalized_job = dict(job_posting or {})
    job_id = str(normalized_job.get("id", "") or "").strip()
    if not job_id:
        raise InputValidationError(
            "This job is missing a stable id and cannot be saved safely."
        )

    context = resolve_authenticated_context(
        access_token=access_token,
        refresh_token=refresh_token,
    )
    saved_jobs_store = SavedJobsStore(context.auth_service)
    if not saved_jobs_store.is_configured():
        raise RuntimeError("Saved jobs persistence is not configured.")

    saved_job = saved_jobs_store.save_job(
        access_token,
        refresh_token,
        {
            "user_id": context.app_user.id,
            "job_id": job_id,
            **normalized_job,
        },
    )
    normalized_saved_job = _normalize_saved_job(saved_job)
    return {
        "status": "saved",
        "saved_job": normalized_saved_job,
        "message": "Saved {title} to your shortlist.".format(
            title=normalized_saved_job.get("title", "job")
        ),
    }


def remove_saved_job(*, access_token: str, refresh_token: str, job_id: str):
    normalized_job_id = str(job_id or "").strip()
    if not normalized_job_id:
        raise InputValidationError(
            "This job is missing a stable id and cannot be removed safely."
        )

    context = resolve_authenticated_context(
        access_token=access_token,
        refresh_token=refresh_token,
    )
    saved_jobs_store = SavedJobsStore(context.auth_service)
    if not saved_jobs_store.is_configured():
        raise RuntimeError("Saved jobs persistence is not configured.")

    saved_jobs_store.delete_job(
        access_token,
        refresh_token,
        context.app_user.id,
        normalized_job_id,
    )
    return {
        "status": "removed",
        "job_id": normalized_job_id,
    }
