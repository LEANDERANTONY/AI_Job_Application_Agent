"""Cooperative-cancellation unit tests for the analysis job runner.

Covers the seam added for user-initiated Stop:
  * `cancel_workspace_analysis_job` sets the flag on an active job,
    is idempotent on terminal jobs, and returns None for an unknown id
  * `_update_job_progress` raises `WorkspaceRunJobCancelled` once the
    flag is set (and behaves normally otherwise)
  * `_run_job` ends a flagged run in the terminal "cancelled" state
    (NOT "failed", no error_message) and still releases the slot, while
    a genuine failure is still recorded as "failed" (regression guard
    that the new except-branch doesn't swallow real errors)

No network, no real orchestrator: a fake `run_workspace_analysis`
drives the very same `progress_callback` the orchestrator's
`begin_stage` calls at each agent boundary, so the cooperative seam is
exercised faithfully.
"""

from __future__ import annotations

import pytest

from backend.services import workspace_run_jobs as wrj
from backend.services.workspace_run_jobs import (
    WorkspaceRunJob,
    WorkspaceRunJobCancelled,
    _run_job,
    _update_job_progress,
    cancel_workspace_analysis_job,
    get_workspace_analysis_job,
)


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Give each test a clean process-global `_JOBS` and restore the
    prior contents afterward so this module never leaks job state into
    (or out of) the rest of the suite."""
    with wrj._LOCK:
        saved = dict(wrj._JOBS)
        wrj._JOBS.clear()
    try:
        yield
    finally:
        with wrj._LOCK:
            wrj._JOBS.clear()
            wrj._JOBS.update(saved)


def _put(job: WorkspaceRunJob) -> None:
    with wrj._LOCK:
        wrj._JOBS[job.job_id] = job


def test_cancel_sets_flag_on_active_job():
    _put(WorkspaceRunJob(job_id="j1", status="running"))
    out = cancel_workspace_analysis_job("j1")
    assert out is not None and out["job_id"] == "j1"
    with wrj._LOCK:
        assert wrj._JOBS["j1"].cancel_requested is True


def test_cancel_unknown_job_returns_none():
    assert cancel_workspace_analysis_job("does-not-exist") is None


@pytest.mark.parametrize("terminal", ["completed", "failed", "cancelled"])
def test_cancel_is_noop_on_terminal_job(terminal):
    _put(WorkspaceRunJob(job_id="t", status=terminal))
    out = cancel_workspace_analysis_job("t")
    assert out is not None and out["status"] == terminal
    with wrj._LOCK:
        # A finished job has nothing running to observe the flag;
        # leaving it unset avoids a stale flag flipping any future
        # state and keeps cancel idempotent.
        assert wrj._JOBS["t"].cancel_requested is False


def test_update_progress_raises_once_flagged():
    _put(WorkspaceRunJob(job_id="p", status="running", cancel_requested=True))
    with pytest.raises(WorkspaceRunJobCancelled):
        _update_job_progress("p", "Forge agent", "drafting", 41)


def test_update_progress_normal_when_not_flagged():
    _put(WorkspaceRunJob(job_id="p2", status="queued"))
    _update_job_progress("p2", "Forge agent", "drafting", 41)
    snap = get_workspace_analysis_job("p2")
    assert snap is not None
    assert snap["status"] == "running"
    assert snap["stage_title"] == "Forge agent"
    assert snap["progress_percent"] == 41


def test_update_progress_missing_job_is_silent():
    # The worker can outlive a pruned job; a progress emit for an
    # unknown id must be a quiet no-op, never an exception.
    _update_job_progress("ghost", "x", "y", 5)


def test_run_job_marks_cancelled_not_failed(monkeypatch):
    """Faithful worker path: the fake drives the orchestrator's
    progress_callback, the user 'stops' between stages, the next
    boundary raises, and `_run_job` ends the job 'cancelled' (not
    'failed') with no error_message."""
    _put(WorkspaceRunJob(job_id="run", status="queued"))

    def fake_run(**kwargs):
        cb = kwargs["progress_callback"]
        cb("Workflow crew", "opening brief", 3)  # 1st boundary — fine
        # Simulate the user pressing Stop while an agent works:
        cancel_workspace_analysis_job("run")
        cb("Forge agent", "drafting", 41)  # observes the flag → raises
        raise AssertionError("unreachable: cancel should have unwound")

    monkeypatch.setattr(wrj, "run_workspace_analysis", fake_run)

    # `_run_job`'s finally releases the BoundedSemaphore; acquire first
    # so the test stays balanced (mirrors start_workspace_analysis_job).
    wrj._RUN_SEMAPHORE.acquire()
    _run_job(
        job_id="run",
        resume_text="r",
        resume_filetype="TXT",
        resume_source="workspace",
        job_description_text="jd",
        imported_job_posting=None,
        premium=False,
        access_token="",
        refresh_token="",
    )

    snap = get_workspace_analysis_job("run")
    assert snap is not None
    assert snap["status"] == "cancelled"
    assert snap["error_message"] is None
    assert "stopped" in (snap["stage_detail"] or "").lower()


def test_run_job_real_failure_still_failed(monkeypatch):
    """Regression guard: the new `except WorkspaceRunJobCancelled`
    branch sits before the failure handlers — a genuine non-cancel
    exception must still land the job in 'failed', not be swallowed."""
    _put(WorkspaceRunJob(job_id="boom", status="queued"))

    def fake_run(**_kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(wrj, "run_workspace_analysis", fake_run)
    wrj._RUN_SEMAPHORE.acquire()
    _run_job(
        job_id="boom",
        resume_text="r",
        resume_filetype="TXT",
        resume_source="workspace",
        job_description_text="jd",
        imported_job_posting=None,
        premium=False,
        access_token="",
        refresh_token="",
    )

    snap = get_workspace_analysis_job("boom")
    assert snap is not None
    assert snap["status"] == "failed"
