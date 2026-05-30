"""Quota enforcement on the async analysis-job path (CRITICAL-2).

The async ``/analyze-jobs`` route used to spawn the worker WITHOUT
checking quota, so a capped Free user got a 200 "queued" then a generic
"failed" toast instead of the canonical 429 upgrade nudge. The fix has
two halves, both pinned here:

  (a) ``start_workspace_analysis_job`` pre-flights the weekly LLM-token
      budget SYNCHRONOUSLY, before acquiring a run slot, so the
      ``QuotaExceededError`` propagates out of the POST -> global 429 ->
      the frontend's existing upgrade CTA.

  (b) a quota gate that can only fire inside the worker (the monthly
      application counter) is carried back to the polling client as a
      structured ``error`` envelope mirroring the 429 body, so the
      hook's ``failed`` branch can render the same CTA instead of a bare
      warning.
"""

from __future__ import annotations

import pytest

from src.errors import QuotaExceededError
from backend.services import workspace_run_jobs as wrj
from backend.services.workspace_run_jobs import (
    WorkspaceRunJob,
    _run_job,
    get_workspace_analysis_job,
    start_workspace_analysis_job,
)


@pytest.fixture(autouse=True)
def _isolate_registry():
    with wrj._LOCK:
        saved = dict(wrj._JOBS)
        wrj._JOBS.clear()
    try:
        yield
    finally:
        with wrj._LOCK:
            wrj._JOBS.clear()
            wrj._JOBS.update(saved)


def test_start_preflights_quota_before_acquiring_a_slot(monkeypatch):
    """The synchronous pre-flight raises out of ``start_...`` (so the POST
    returns 429) and does so BEFORE creating a job or taking a run slot —
    a capped user never queues work or consumes capacity."""

    def _raise(user_id, tier, **_kwargs):
        raise QuotaExceededError(
            "You've used your weekly AI usage allowance on this plan.",
            counter="llm_tokens",
            current=90_000,
            cap=90_000,
            reset_period="2026-W22",
            tier="free",
        )

    monkeypatch.setattr(wrj, "enforce_llm_budget", _raise)

    with pytest.raises(QuotaExceededError):
        start_workspace_analysis_job(
            resume_text="r",
            resume_filetype="TXT",
            resume_source="workspace",
            job_description_text="jd",
            imported_job_posting=None,
            premium=False,
            access_token="",
            refresh_token="",
            owner_user_id="user-1",
            tier="free",
        )

    # Bailed before job creation ...
    with wrj._LOCK:
        assert wrj._JOBS == {}

    # ... and no run slot leaked: all JOB_CONCURRENCY_LIMIT slots are
    # still acquirable (the pre-flight precedes the semaphore acquire, so
    # a rejected run can't shrink capacity for everyone else).
    acquired = [
        wrj._RUN_SEMAPHORE.acquire(blocking=False)
        for _ in range(wrj.JOB_CONCURRENCY_LIMIT)
    ]
    try:
        assert all(acquired)
    finally:
        for ok in acquired:
            if ok:
                wrj._RUN_SEMAPHORE.release()


def test_worker_quota_error_populates_structured_envelope(monkeypatch):
    """A ``QuotaExceededError`` raised inside the worker (e.g. the monthly
    application counter) ends the job 'failed' AND attaches the structured
    tier-limit envelope the polling client renders as an upgrade CTA."""
    with wrj._LOCK:
        wrj._JOBS["job-q"] = WorkspaceRunJob(job_id="job-q", status="queued")

    def _raise(**_kwargs):
        raise QuotaExceededError(
            "You've reached your monthly tailored-application limit.",
            counter="tailored_applications",
            current=3,
            cap=3,
            reset_period="2026-05",
            tier="free",
        )

    monkeypatch.setattr(wrj, "run_workspace_analysis", _raise)

    wrj._RUN_SEMAPHORE.acquire()
    _run_job(
        job_id="job-q",
        resume_text="r",
        resume_filetype="TXT",
        resume_source="workspace",
        job_description_text="jd",
        imported_job_posting=None,
        premium=False,
        access_token="",
        refresh_token="",
    )

    snap = get_workspace_analysis_job("job-q")
    assert snap is not None
    assert snap["status"] == "failed"
    envelope = snap["error"]
    assert envelope is not None
    assert envelope["code"] == "tier_limit_exceeded"
    assert envelope["counter"] == "tailored_applications"
    assert envelope["current"] == 3
    assert envelope["cap"] == 3
    assert envelope["reset_period"] == "2026-05"
    assert envelope["tier"] == "free"
    # The human-readable message is still present for the fallback path.
    assert "monthly" in (snap["error_message"] or "").lower()


def test_worker_non_quota_error_has_no_envelope(monkeypatch):
    """Regression guard: a non-quota failure still ends 'failed' but
    carries NO structured envelope, so the hook shows the plain warning,
    not a spurious upgrade CTA."""
    with wrj._LOCK:
        wrj._JOBS["job-x"] = WorkspaceRunJob(job_id="job-x", status="queued")

    monkeypatch.setattr(
        wrj,
        "run_workspace_analysis",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("kaboom")),
    )

    wrj._RUN_SEMAPHORE.acquire()
    _run_job(
        job_id="job-x",
        resume_text="r",
        resume_filetype="TXT",
        resume_source="workspace",
        job_description_text="jd",
        imported_job_posting=None,
        premium=False,
        access_token="",
        refresh_token="",
    )

    snap = get_workspace_analysis_job("job-x")
    assert snap is not None
    assert snap["status"] == "failed"
    assert snap["error"] is None
