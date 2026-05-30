from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from backend.quota import current_period_key
from backend.services.auth_session_service import resolve_authenticated_context
from backend.tiers import TIER_CAPS, UNLIMITED, resolve_user_tier
from src.cached_jobs_store import CachedJobsStore
from src.errors import InputValidationError, QuotaExceededError
from src.saved_jobs_store import SavedJobsCapExceeded, SavedJobsStore


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
        # Default optimistic — overwritten by _annotate_listing_status
        # when we have a cache to consult. The UI shows an "Expired"
        # badge when this is False.
        "is_listing_active": True,
    }


def _annotate_listing_status(jobs: list[dict[str, Any]]):
    """Look up the cache to find which saved jobs are still listed
    upstream. Mutates `jobs` in place — sets is_listing_active=False
    on any whose cached_jobs row has removed_at set (the smart cleanup
    tombstoned it after the upstream board stopped returning it).

    No-ops gracefully when the cache isn't configured, so local-dev
    workflows without SUPABASE_SERVICE_ROLE_KEY don't break."""
    if not jobs:
        return
    cache = CachedJobsStore()
    if not cache.is_configured():
        return
    keys = [(str(j.get("source", "")), str(j.get("id", ""))) for j in jobs]
    try:
        status_map = cache.get_listing_status_map(keys)
    except Exception:
        # Don't poison the saved-jobs response on a cache outage.
        return
    for job in jobs:
        key = (str(job.get("source", "")), str(job.get("id", "")))
        is_active = status_map.get(key, True)
        job["is_listing_active"] = bool(is_active)


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
    _annotate_listing_status(saved_jobs)

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
    """Persist one job to the user's shortlist.

    Quota gate (Step 6 of tier-enforcement):
      `saved_jobs` is a PERSISTENT row-count cap, not a period-keyed
      counter: Free 5 / Pro 1000 / Business UNLIMITED. The brief calls
      this out as a different pattern from the period-keyed counters
      -- we count existing rows via `SavedJobsStore.list_jobs` and
      compare to `TIER_CAPS[tier]["saved_jobs"]`, rather than going
      through `quota.check_and_increment`. No refund logic because
      we're not incrementing anything.

      The cap check is skipped when the tier cap is UNLIMITED (-1) so
      Business saves never read the existing-row count -- they go
      straight to the upsert. The store's upsert key is
      (user_id, job_id), so re-saving the SAME job at the cap is
      allowed (it's an update, not a new row).
    """
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

    # Persistent-count quota gate. Skip when the tier cap is UNLIMITED
    # (Business) so we don't even pay the list-jobs round-trip. For
    # capped tiers, count existing rows and compare to the cap; re-saving
    # the SAME job_id is fine (the upsert below is an update, not a new
    # row).
    tier = resolve_user_tier(context.app_user)
    cap = TIER_CAPS[tier]["saved_jobs"]
    quota_user_id = str(getattr(context.app_user, "id", "") or "")
    if cap != UNLIMITED and quota_user_id:
        # The store's default page size of 20 is too small to inspect a
        # capped quota -- a Pro user at 999 saved jobs would silently
        # bypass the gate. Pass an explicit limit one above the cap so
        # we always know whether the user is at-or-over.
        existing_jobs = saved_jobs_store.list_jobs(
            access_token,
            refresh_token,
            quota_user_id,
            limit=cap + 1,
        )
        existing_ids = {str(getattr(record, "job_id", "")) for record in existing_jobs}
        # Allow re-saves of an already-saved job_id -- the upsert below
        # treats that as an UPDATE (same row), not a new row. Without
        # this carve-out a user at the cap could never re-save a job
        # they edited.
        if job_id not in existing_ids and len(existing_jobs) >= cap:
            raise QuotaExceededError(
                "You have reached the saved-jobs limit for your plan. "
                "Remove an existing saved job to make room, or upgrade "
                "to continue saving more.",
                counter="saved_jobs",
                current=len(existing_jobs),
                cap=cap,
                reset_period=current_period_key(),  # informational only -- persistent counters don't reset
                tier=tier,
            )

    # Atomic cap-enforced write (review M2). The pre-check above is a fast
    # path that gives a nice early 429 and keeps the common case cheap, but
    # it is a count-then-write TOCTOU; save_job_atomic re-checks the cap
    # under a per-user advisory lock in ONE transaction, so two concurrent
    # saves of distinct jobs can't both slip past the cap. The race loses
    # here and is translated to the same canonical 429.
    try:
        saved_job = saved_jobs_store.save_job_atomic(
            access_token,
            refresh_token,
            {
                "user_id": context.app_user.id,
                "job_id": job_id,
                **normalized_job,
            },
            cap=cap,
        )
    except SavedJobsCapExceeded as exc:
        raise QuotaExceededError(
            "You have reached the saved-jobs limit for your plan. "
            "Remove an existing saved job to make room, or upgrade "
            "to continue saving more.",
            counter="saved_jobs",
            current=cap,
            cap=cap,
            reset_period=current_period_key(),
            tier=tier,
        ) from exc
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
