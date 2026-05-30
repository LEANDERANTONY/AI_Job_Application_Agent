from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from src.errors import AppError, QuotaExceededError
from src.logging_utils import get_logger, log_event

from backend.observability import (
    add_sentry_breadcrumb,
    set_sentry_tag,
    set_sentry_user,
)
from backend.quota import enforce_llm_budget
from backend.services.workspace_service import run_workspace_analysis


# 10 minutes (review L3). A completed job's multi-KB result dict is handed to
# the first terminal poll and then dropped (see get_workspace_analysis_job), so
# this TTL only bounds how long the small status envelope lingers for a client
# that stopped polling — there's no reason to keep the old 30-minute window that
# kept heavy payloads resident on the 1-2GB container when traffic quieted (the
# pruner only runs on inbound requests, so a lull leaves them sitting).
JOB_TTL_SECONDS = 60 * 10
# One uvicorn worker per the VPS deployment; the semaphore protects that
# single process from runaway thread spawns under burst /analyze-jobs
# traffic. A simultaneously-running agentic workflow holds an LLM client
# + parsed snapshots in memory, and 5 is comfortably below where a 1-2GB
# container starts feeling pressure.
JOB_CONCURRENCY_LIMIT = 5
JOB_RETRY_AFTER_SECONDS = 30
LOGGER = get_logger(__name__)


class WorkspaceRunJobCapacityError(RuntimeError):
    """Raised when `_RUN_SEMAPHORE` is exhausted at request time."""


class WorkspaceRunJobCancelled(Exception):
    """Cooperative-cancellation signal for an in-flight analysis job.

    Deliberately a plain `Exception` (NOT an `AppError` / not an
    `AgentExecutionError`): it must travel UNCHANGED through every
    handler between the stage-boundary progress callback and
    `_run_job`'s terminal handler —
      * the orchestrator's per-agent `except AgentExecutionError` /
        `except OpenAIUnavailableError` (no match → not swallowed),
      * `ApplicationOrchestrator.run`'s `except AgentExecutionError`
        (no match → not turned into a deterministic fallback),
      * `run_workspace_analysis`'s `except BaseException` (matches →
        refunds the consumed quota credit, then re-raises — so a
        cancelled run never costs the user an application credit).
    `_run_job` catches it explicitly and marks the job `cancelled`
    (a normal user action, not a failure).
    """


# Terminal statuses: a job here is done moving and a cancel request is
# a no-op (idempotent — a double-click or a cancel that races
# completion must not error).
_TERMINAL_JOB_STATUSES = frozenset({"completed", "failed", "cancelled"})


@dataclass
class WorkspaceRunJob:
    job_id: str
    status: str = "queued"
    stage_title: str | None = "Workflow crew"
    stage_detail: str | None = "Opening your application brief and preparing the first agent."
    progress_percent: int = 3
    result: dict[str, Any] | None = None
    error_message: str | None = None
    # Structured error envelope mirroring the global 429 body
    # (code/counter/current/cap/reset_period/tier). Populated when a
    # QuotaExceededError fires inside the worker so the polling client
    # renders the SAME upgrade CTA the synchronous 429 path gives,
    # instead of a generic "failed" toast (review CRITICAL-2 / Rec #1).
    error: dict[str, Any] | None = None
    # Identity that created this job, captured from the authenticated
    # request in `start_workspace_analysis_job`. The status / cancel
    # routes pass the *caller's* resolved user_id; a mismatch is treated
    # as 404 (never 403 — we don't confirm the job exists). The job_id is
    # a uuid4 carried in the URL and leaks via access logs / Referer /
    # telemetry, so it is NOT an authorization token on its own. Closes
    # the unauthenticated BOLA (review SECURITY-1).
    owner_user_id: str | None = None
    # Set by `cancel_workspace_analysis_job`; observed by the worker at
    # the next stage boundary (begin_stage → progress callback →
    # `_update_job_progress`). Cooperative because a Python thread
    # blocked inside an OpenAI call cannot be force-killed safely, so
    # cancellation takes effect at the next agent boundary (≤ one
    # agent / ≤ the per-call timeout), never mid-LLM-call.
    cancel_requested: bool = False
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


_JOBS: dict[str, WorkspaceRunJob] = {}
_LOCK = threading.Lock()
_RUN_SEMAPHORE = threading.BoundedSemaphore(JOB_CONCURRENCY_LIMIT)

# Per-user in-flight cap (review BACKEND-2 / BACKEND-4). The global
# semaphore above is a process-MEMORY backstop, not a fairness control:
# one account firing several concurrent /analyze-jobs could hold every
# global slot AND slip multiple full runs past the read-before-write
# weekly-token gate (the meter only records AFTER a run, so concurrent
# entry checks all read the same pre-run total). This per-user
# reservation — taken BEFORE the global slot — bounds how many runs a
# single user can have in flight (default 1). Env-configurable so it can
# be tuned at launch without a redeploy.
_PER_USER_RUN_LIMIT = max(
    1, int(os.getenv("AIJOBAGENT_PER_USER_RUN_LIMIT", "1") or "1")
)
_INFLIGHT_BY_USER: dict[str, int] = {}


def _release_inflight(user_id: str) -> None:
    """Drop one in-flight reservation for ``user_id``.

    No-op when blank or already at zero, so it is safe to call more than
    once on a failure path (the reservation is released exactly once on
    the happy path, by ``_run_job``'s finally)."""
    normalized = str(user_id or "").strip()
    if not normalized:
        return
    with _LOCK:
        current = _INFLIGHT_BY_USER.get(normalized, 0)
        if current <= 1:
            _INFLIGHT_BY_USER.pop(normalized, None)
        else:
            _INFLIGHT_BY_USER[normalized] = current - 1


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
        "error": job.error,
    }


def _update_job_progress(job_id: str, title: str, detail: str, value: int) -> None:
    # This runs on every pipeline stage boundary (the orchestrator's
    # `begin_stage` → `_emit_progress` → this callback), which makes it
    # the natural cooperative-cancellation checkpoint: if a cancel was
    # requested while the previous agent was working, we abandon the
    # progress write and raise so the run unwinds at the boundary
    # instead of advancing into the next (possibly premium) LLM call.
    cancelled = False
    with _LOCK:
        job = _JOBS.get(job_id)
        if job is None:
            return
        if job.cancel_requested:
            cancelled = True
        else:
            job.status = "running"
            job.stage_title = title
            job.stage_detail = detail
            job.progress_percent = max(0, min(100, int(value)))
            job.updated_at = time.time()
    if cancelled:
        # Raise OUTSIDE the lock — the unwinding stack (orchestrator →
        # run_workspace_analysis' refund → _run_job) must never contend
        # on _LOCK while this propagates.
        raise WorkspaceRunJobCancelled(job_id)

    # Leave a Sentry trail at each stage boundary (review M23). The tag is the
    # stage just entered; the breadcrumbs are the full path that led here, so a
    # later crash (captured via LOGGER.exception in _run_job's fallback, same
    # worker thread → same scope) shows which agent stage was last in flight
    # instead of a bare 5xx. Both are no-ops when Sentry is inactive and cannot
    # touch the run on failure — the orchestrator itself stays untouched.
    set_sentry_tag("pipeline_stage", title)
    add_sentry_breadcrumb(
        category="agent",
        message=title,
        data={"job_id": job_id, "detail": detail, "progress": int(value)},
    )


def _run_job(
    *,
    job_id: str,
    resume_text: str,
    resume_filetype: str,
    resume_source: str,
    job_description_text: str,
    imported_job_posting: dict[str, Any] | None,
    premium: bool,
    access_token: str,
    refresh_token: str,
    owner_user_id: str | None = None,
) -> None:
    # Stamp the actor onto this worker thread's Sentry scope (review M23) so a
    # crash captured below (LOGGER.exception) is filterable to one account
    # rather than an anonymous platform-wide failure. No-op when anonymous or
    # when Sentry is inactive.
    set_sentry_user(owner_user_id)
    try:
        try:
            result = run_workspace_analysis(
                resume_text=resume_text,
                resume_filetype=resume_filetype,
                resume_source=resume_source,
                job_description_text=job_description_text,
                imported_job_posting=imported_job_posting,
                run_assisted=True,
                premium=premium,
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
        except WorkspaceRunJobCancelled:
            # A normal user action, not a failure — log at INFO and end
            # the job in a distinct terminal state (NOT "failed", so the
            # UI doesn't show an error banner). The quota credit was
            # already refunded by run_workspace_analysis' BaseException
            # handler on the way up, so the copy can promise that.
            log_event(
                LOGGER,
                20,
                "workspace_run_job_cancelled",
                "The background workspace analysis job was cancelled by the user before completion.",
                job_id=job_id,
            )
            with _LOCK:
                job = _JOBS.get(job_id)
                if job is None:
                    return
                job.status = "cancelled"
                job.stage_title = "Run stopped"
                job.stage_detail = (
                    "You stopped this run before it finished. No credit "
                    "was used — start a new run whenever you're ready."
                )
                job.error_message = None
                job.updated_at = time.time()
        except QuotaExceededError as error:
            # A quota gate fired on the worker thread — most often the
            # monthly application counter (check_and_increment), or the
            # weekly token meter racing the synchronous pre-flight under
            # concurrency. Carry the SAME structured envelope the global
            # 429 handler produces so the polling client renders the
            # upgrade CTA, not a generic "failed" toast (CRITICAL-2).
            message = error.user_message
            log_event(
                LOGGER,
                30,
                "workspace_run_job_quota_blocked",
                "The background workspace analysis job hit a plan limit.",
                job_id=job_id,
                counter=error.counter,
                tier=error.tier,
            )
            with _LOCK:
                job = _JOBS.get(job_id)
                if job is None:
                    return
                job.status = "failed"
                job.error_message = message
                job.error = {
                    "code": "tier_limit_exceeded",
                    "detail": message,
                    "counter": error.counter,
                    "current": error.current,
                    "cap": error.cap,
                    "reset_period": error.reset_period,
                    "tier": error.tier,
                }
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
    finally:
        # Release the global slot AND the per-user reservation regardless
        # of how the worker exits, so a crash never permanently shrinks
        # either cap below its limit.
        _RUN_SEMAPHORE.release()
        _release_inflight(owner_user_id or "")


def start_workspace_analysis_job(
    *,
    resume_text: str,
    resume_filetype: str,
    resume_source: str,
    job_description_text: str,
    imported_job_posting: dict[str, Any] | None,
    premium: bool = False,
    access_token: str,
    refresh_token: str,
    owner_user_id: str | None = None,
    tier: str = "free",
) -> dict[str, Any]:
    # Quota PRE-FLIGHT (review CRITICAL-2 / Rec #1): enforce the weekly
    # LLM-token budget SYNCHRONOUSLY — before acquiring a run slot or
    # spawning the worker — so a capped user gets the canonical 429 out
    # of the POST (which the frontend already renders as an upgrade CTA)
    # instead of a 200 "queued" that later flips to a generic "failed"
    # toast. enforce_llm_budget is a read-only check (it never
    # increments), so it does NOT double-charge the meter the worker
    # records into, and it no-ops on a blank user_id / unlimited tier.
    # The monthly application counter stays inside the worker (it is an
    # atomic increment that can't be pre-checked without double-billing);
    # that gate round-trips to the client via the job's `error` envelope.
    enforce_llm_budget(owner_user_id or "", tier)

    # Per-user in-flight RESERVATION (review BACKEND-2 / BACKEND-4): taken
    # atomically BEFORE the global semaphore so a single account cannot
    # hold multiple global slots or fan out concurrent runs past the
    # read-before-write weekly-token gate. The global semaphore stays as
    # the process-memory backstop. Released by `_run_job`'s finally on the
    # happy path, or by this function's failure path below.
    normalized_owner = str(owner_user_id or "").strip()
    if normalized_owner:
        with _LOCK:
            if _INFLIGHT_BY_USER.get(normalized_owner, 0) >= _PER_USER_RUN_LIMIT:
                raise WorkspaceRunJobCapacityError(
                    "You already have an agentic workflow run in progress. "
                    "Wait for it to finish before starting another."
                )
            _INFLIGHT_BY_USER[normalized_owner] = (
                _INFLIGHT_BY_USER.get(normalized_owner, 0) + 1
            )

    try:
        # Non-blocking acquire so a saturated server fast-fails the request
        # rather than queueing it behind an opaque thread-spawn delay. The
        # matching release lives in `_run_job`'s finally block.
        if not _RUN_SEMAPHORE.acquire(blocking=False):
            raise WorkspaceRunJobCapacityError(
                "Too many agentic workflow runs are in flight right now."
            )

        try:
            with _LOCK:
                _prune_jobs()
                job_id = uuid.uuid4().hex
                job = WorkspaceRunJob(job_id=job_id, owner_user_id=owner_user_id)
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
                    "premium": premium,
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "owner_user_id": owner_user_id,
                },
                daemon=True,
            )
            worker.start()
        except BaseException:
            # Thread spawn (or anything after the acquire) failed before
            # `_run_job` could run; release the slot so capacity isn't lost.
            _RUN_SEMAPHORE.release()
            with _LOCK:
                _JOBS.pop(job_id, None)
            raise
    except BaseException:
        # The per-user reservation was taken above but the run never
        # reached a worker that would release it (global slot exhausted,
        # or spawn failed) — release it here so it isn't leaked.
        _release_inflight(normalized_owner)
        raise

    with _LOCK:
        return _serialize_job(_JOBS[job_id])


def get_workspace_analysis_job(
    job_id: str, owner_user_id: str | None = None
) -> dict[str, Any] | None:
    with _LOCK:
        _prune_jobs()
        job = _JOBS.get(job_id)
        if job is None:
            return None
        if owner_user_id is not None and job.owner_user_id != owner_user_id:
            # The caller is authenticated but is not the job's owner.
            # Return None so the route emits the SAME 404 it gives for an
            # unknown id — never reveal that the job exists (SECURITY-1).
            return None
        serialized = _serialize_job(job)
        # Drop the heavy result payload after it's been delivered once (review
        # L3). The polling client reads the terminal result on this first
        # terminal poll and stops; keeping the multi-KB dict resident for the
        # full TTL just adds memory pressure on the single 1-2GB container the
        # semaphore sizing assumes is tight. The serialized copy above still
        # carries the full result to THIS caller; later polls see result=None
        # alongside the terminal status they already acted on.
        if job.status in _TERMINAL_JOB_STATUSES:
            job.result = None
        return serialized


def cancel_workspace_analysis_job(
    job_id: str, owner_user_id: str | None = None
) -> dict[str, Any] | None:
    """Request cooperative cancellation of an in-flight analysis job.

    Returns the serialized job, or ``None`` when ``job_id`` is unknown
    (pruned past TTL, wrong id, or the single-worker process restarted
    and lost the in-memory registry — the caller maps this to a 404).
    When ``owner_user_id`` is provided and does not match the job's
    owner, also returns ``None`` (same 404) so a non-owner can neither
    confirm the job exists nor cancel a stranger's run (SECURITY-1).

    Idempotent by design: cancelling an already-terminal job
    (completed / failed / cancelled) just returns its current state. A
    double-click, or a Stop that races the run finishing, must never
    error.

    This only *sets the flag*. The worker thread is blocked inside the
    synchronous pipeline (often mid-OpenAI-call) and a Python thread
    can't be force-killed safely, so the request returns immediately
    with the job still ``running``; the worker observes the flag at its
    next stage boundary and flips the job to ``cancelled`` within
    ≤ one agent. The frontend keeps polling until that terminal state.
    """
    with _LOCK:
        _prune_jobs()
        job = _JOBS.get(job_id)
        if job is None:
            return None
        if owner_user_id is not None and job.owner_user_id != owner_user_id:
            # Not the owner — same 404 as an unknown id (SECURITY-1).
            return None
        if job.status not in _TERMINAL_JOB_STATUSES:
            job.cancel_requested = True
            job.updated_at = time.time()
        return _serialize_job(job)
