from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from src.errors import AppError
from src.logging_utils import get_logger, log_event

from backend.services.workspace_service import run_workspace_analysis


JOB_TTL_SECONDS = 60 * 30
LOGGER = get_logger(__name__)


@dataclass
class WorkspaceRunJob:
    job_id: str
    status: str = "queued"
    stage_title: str | None = "Workflow crew"
    stage_detail: str | None = "Opening your application brief and preparing the first agent."
    progress_percent: int = 3
    result: dict[str, Any] | None = None
    error_message: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


_JOBS: dict[str, WorkspaceRunJob] = {}
_LOCK = threading.Lock()


def _prune_jobs() -> None:
    cutoff = time.time() - JOB_TTL_SECONDS
    stale_job_ids = [job_id for job_id, job in _JOBS.items() if job.updated_at < cutoff]
    for job_id in stale_job_ids:
        _JOBS.pop(job_id, None)


def _serialize_job(job: WorkspaceRunJob) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "status": job.status,
        "stage_title": job.stage_title,
        "stage_detail": job.stage_detail,
        "progress_percent": int(job.progress_percent),
        "result": job.result,
        "error_message": job.error_message,
    }


def _update_job_progress(job_id: str, title: str, detail: str, value: int) -> None:
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        job.status = "running"
        job.stage_title = title
        job.stage_detail = detail
        job.progress_percent = max(0, min(100, int(value)))
        job.updated_at = time.time()


def _run_job(
    *,
    job_id: str,
    resume_text: str,
    resume_filetype: str,
    resume_source: str,
    job_description_text: str,
    imported_job_posting: dict[str, Any] | None,
    access_token: str,
    refresh_token: str,
) -> None:
    try:
        result = run_workspace_analysis(
            resume_text=resume_text,
            resume_filetype=resume_filetype,
            resume_source=resume_source,
            job_description_text=job_description_text,
            imported_job_posting=imported_job_posting,
            run_assisted=True,
            access_token=access_token,
            refresh_token=refresh_token,
            progress_callback=lambda title, detail, value: _update_job_progress(
                job_id,
                title,
                detail,
                value,
            ),
        )
        with _LOCK:
            job = _JOBS.get(job_id)
            if job is None:
                return
            job.status = "completed"
            job.result = result
            job.progress_percent = 100
            job.stage_title = "Workflow crew"
            job.stage_detail = "All agents are done. Your tailored documents are ready to review."
            job.updated_at = time.time()
    except AppError as error:
        message = error.user_message
        log_event(
            LOGGER,
            30,
            "workspace_run_job_failed",
            "The background workspace analysis job failed with an application error.",
            job_id=job_id,
            error_type=type(error).__name__,
            message=message,
        )
        with _LOCK:
            job = _JOBS.get(job_id)
            if job is None:
                return
            job.status = "failed"
            job.error_message = message
            job.updated_at = time.time()
    except Exception as error:  # pragma: no cover - defensive server fallback
        LOGGER.exception("Background workspace analysis job crashed.", extra={"job_id": job_id})
        with _LOCK:
            job = _JOBS.get(job_id)
            if job is None:
                return
            job.status = "failed"
            job.error_message = str(error) or "The agentic workflow failed unexpectedly."
            job.updated_at = time.time()


def start_workspace_analysis_job(
    *,
    resume_text: str,
    resume_filetype: str,
    resume_source: str,
    job_description_text: str,
    imported_job_posting: dict[str, Any] | None,
    access_token: str,
    refresh_token: str,
) -> dict[str, Any]:
    with _LOCK:
        _prune_jobs()
        job_id = uuid.uuid4().hex
        job = WorkspaceRunJob(job_id=job_id)
        _JOBS[job_id] = job

    worker = threading.Thread(
        target=_run_job,
        kwargs={
            "job_id": job_id,
            "resume_text": resume_text,
            "resume_filetype": resume_filetype,
            "resume_source": resume_source,
            "job_description_text": job_description_text,
            "imported_job_posting": imported_job_posting,
            "access_token": access_token,
            "refresh_token": refresh_token,
        },
        daemon=True,
    )
    worker.start()

    with _LOCK:
        return _serialize_job(_JOBS[job_id])


def get_workspace_analysis_job(job_id: str) -> dict[str, Any] | None:
    with _LOCK:
        _prune_jobs()
        job = _JOBS.get(job_id)
        if job is None:
            return None
        return _serialize_job(job)
