"""L3 — completed analysis jobs shed their heavy result payload after delivery.

A finished job's multi-KB result dict used to sit in the in-memory registry for
the full TTL (30 min), pruned only lazily on inbound requests — so a traffic lull
left the payloads resident on the 1-2GB container the concurrency sizing treats
as tight. The result is now handed to the first terminal poll and then dropped,
and the TTL is shortened to 10 min.
"""
from __future__ import annotations

import pytest

from backend.services import workspace_run_jobs as wrj
from backend.services.workspace_run_jobs import WorkspaceRunJob


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Clean process-global _JOBS per test, restored afterward (mirrors
    test_analyze_jobs_ownership.py)."""
    with wrj._LOCK:
        saved = dict(wrj._JOBS)
        wrj._JOBS.clear()
    try:
        yield
    finally:
        with wrj._LOCK:
            wrj._JOBS.clear()
            wrj._JOBS.update(saved)


def _put(job_id: str, *, status: str = "completed", result=None) -> None:
    with wrj._LOCK:
        wrj._JOBS[job_id] = WorkspaceRunJob(
            job_id=job_id,
            status=status,
            result=result if result is not None else {"artifacts": {"x": "y" * 1000}},
        )


def test_first_terminal_get_returns_result_then_drops_it():
    _put("job-1", status="completed")
    first = wrj.get_workspace_analysis_job("job-1")
    assert first is not None
    assert first["result"] is not None  # full payload delivered once

    # The in-memory job has shed the payload after that first terminal read...
    with wrj._LOCK:
        assert wrj._JOBS["job-1"].result is None

    # ...and a later poll sees result=None alongside the terminal status the
    # client already acted on.
    second = wrj.get_workspace_analysis_job("job-1")
    assert second is not None
    assert second["status"] == "completed"
    assert second["result"] is None


def test_non_terminal_get_keeps_result():
    _put("job-2", status="running")
    snapshot = wrj.get_workspace_analysis_job("job-2")
    assert snapshot is not None
    assert snapshot["status"] == "running"
    # A still-running job must keep its (partial/None) result slot intact —
    # only terminal jobs shed it.
    with wrj._LOCK:
        assert wrj._JOBS["job-2"].result is not None


def test_job_ttl_lowered_to_ten_minutes():
    assert wrj.JOB_TTL_SECONDS == 600
