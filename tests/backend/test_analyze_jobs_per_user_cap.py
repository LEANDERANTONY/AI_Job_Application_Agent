"""Per-user in-flight cap on the analysis-job runner (BACKEND-2/BACKEND-4).

The process-global run semaphore is a memory backstop, not a fairness
control: one account firing several concurrent /analyze-jobs could hold
every global slot AND slip multiple full runs past the read-before-write
weekly-token gate (the meter records only AFTER a run, so concurrent
entry checks all read the same pre-run total). ``start_workspace_analysis_job``
now reserves a per-user slot (default 1) BEFORE the global semaphore and
releases it when the run finishes.

The reservation is exercised deterministically: the rejection path is
white-box (pre-seed the counter), and the release path polls the counter
to zero (the worker drains it in ``_run_job``'s finally).
"""

from __future__ import annotations

import time

import pytest

from backend.services import workspace_run_jobs as wrj
from backend.services.workspace_run_jobs import (
    WorkspaceRunJobCapacityError,
    start_workspace_analysis_job,
)


@pytest.fixture(autouse=True)
def _isolate_registry(monkeypatch):
    # No real LLM run; a trivial fake completes the worker fast so the
    # per-user reservation drains via _run_job's finally.
    monkeypatch.setattr(wrj, "enforce_llm_budget", lambda *args, **kwargs: None)
    monkeypatch.setattr(wrj, "run_workspace_analysis", lambda **_kwargs: {"ok": True})
    monkeypatch.setattr(wrj, "_PER_USER_RUN_LIMIT", 1)
    with wrj._LOCK:
        saved_jobs = dict(wrj._JOBS)
        saved_inflight = dict(wrj._INFLIGHT_BY_USER)
        wrj._JOBS.clear()
        wrj._INFLIGHT_BY_USER.clear()
    try:
        yield
    finally:
        with wrj._LOCK:
            wrj._JOBS.clear()
            wrj._JOBS.update(saved_jobs)
            wrj._INFLIGHT_BY_USER.clear()
            wrj._INFLIGHT_BY_USER.update(saved_inflight)


def _start(**over):
    kwargs = dict(
        resume_text="r",
        resume_filetype="TXT",
        resume_source="workspace",
        job_description_text="jd",
        imported_job_posting=None,
        premium=False,
        access_token="",
        refresh_token="",
        tier="free",
    )
    kwargs.update(over)
    return start_workspace_analysis_job(**kwargs)


def _wait_inflight_zero(user, timeout=3.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        with wrj._LOCK:
            if wrj._INFLIGHT_BY_USER.get(user, 0) == 0:
                return
        time.sleep(0.01)
    raise AssertionError(f"in-flight reservation for {user!r} did not drain")


def test_per_user_cap_rejects_a_second_concurrent_run():
    # u1 already has a run in flight.
    with wrj._LOCK:
        wrj._INFLIGHT_BY_USER["u1"] = 1

    with pytest.raises(WorkspaceRunJobCapacityError):
        _start(owner_user_id="u1")

    # The rejected run created no job and did not touch the reservation
    # (no double-count, no leak).
    with wrj._LOCK:
        assert wrj._JOBS == {}
        assert wrj._INFLIGHT_BY_USER["u1"] == 1


def test_a_different_user_is_not_capped():
    # u1 is at its limit; u2 is unaffected and can start.
    with wrj._LOCK:
        wrj._INFLIGHT_BY_USER["u1"] = 1

    handle = _start(owner_user_id="u2")
    assert handle["job_id"]
    _wait_inflight_zero("u2")


def test_slot_released_after_run_finishes_allows_a_new_run():
    first = _start(owner_user_id="u1")
    _wait_inflight_zero("u1")  # worker finished and released the reservation

    second = _start(owner_user_id="u1")
    assert second["job_id"] != first["job_id"]
    _wait_inflight_zero("u1")


def test_anonymous_runs_are_not_per_user_capped():
    # Owner-less runs (owner_user_id=None) bypass the per-user cap — they
    # are still bounded by the global semaphore. Two in a row must both
    # start (no reservation keyed on a blank id).
    one = _start(owner_user_id=None)
    two = _start(owner_user_id=None)
    assert one["job_id"] and two["job_id"] and one["job_id"] != two["job_id"]
    with wrj._LOCK:
        assert "" not in wrj._INFLIGHT_BY_USER
