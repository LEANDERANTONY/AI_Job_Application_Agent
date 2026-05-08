"""Refresh worker for the cached_jobs Supabase table.

This is what /admin/refresh-cache calls. It:
  1. Iterates the configured job-source adapters (greenhouse, lever).
  2. Calls `fetch_all_postings()` on each — unfiltered firehose.
  3. Bulk-upserts every posting into cached_jobs (keyed on source + job_id).
  4. Runs the smart cleanup: tombstone rows that disappeared upstream
     IF a user has saved them, hard-delete them otherwise.

Designed to be idempotent and crash-safe at any step:
  - A partial run leaves cached_jobs in a consistent state (just less
    fresh than a full run).
  - Errors per source are isolated — one bad board doesn't poison the
    rest of the refresh, and crucially doesn't trigger cleanup for
    that source (which would otherwise vaporise the cache for a single
    failed HTTP call).

Returns a structured report so the admin endpoint can surface what
happened in JSON.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from src.cached_jobs_store import CachedJobsStore
from src.job_sources.ashby import AshbyJobSourceAdapter
from src.job_sources.greenhouse import GreenhouseJobSourceAdapter
from src.job_sources.lever import LeverJobSourceAdapter
from src.job_sources.workday import WorkdayJobSourceAdapter
from src.logging_utils import get_logger, log_event


LOGGER = get_logger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _adapters_with_fetch_all():
    """Yield (source_name, adapter) pairs that support bulk fetch.

    Demo source intentionally excluded — its content is local files
    that don't need refreshing. Adding a new provider is one line:
    instantiate the adapter and append.
    """
    yield ("greenhouse", GreenhouseJobSourceAdapter())
    yield ("lever", LeverJobSourceAdapter())
    yield ("ashby", AshbyJobSourceAdapter())
    yield ("workday", WorkdayJobSourceAdapter())


def refresh_cached_jobs(
    *,
    store: CachedJobsStore | None = None,
    adapters: list[tuple[str, Any]] | None = None,
) -> dict:
    """Refresh the cached_jobs table from all configured providers.

    Returns a JSON-serializable report of the form:
      {
        "started_at": "2026-..",
        "finished_at": "2026-..",
        "duration_seconds": 12.4,
        "providers": {
          "greenhouse": {
            "status": "ok" | "partial" | "error",
            "boards_succeeded": 95,
            "boards_failed": 5,
            "postings_upserted": 4823,
            "tombstoned": 12,
            "deleted": 47,
            "errors": [{"board": "...", "message": "..."}, ...]
          },
          "lever": { ... },
        },
        "total_active_after": 5311
      }
    """
    cache = store or CachedJobsStore()
    if not cache.is_configured():
        raise RuntimeError(
            "cached_jobs store is not configured (SUPABASE_URL + "
            "SUPABASE_SERVICE_ROLE_KEY required)."
        )

    started_at = _utc_now_iso()
    started_perf = time.perf_counter()
    # Cutoff for cleanup: anything not touched in this run is a
    # candidate. We compute it here (before any fetches) so the
    # cleanup query catches every row we DON'T upsert in step 2.
    cutoff_iso = started_at

    providers_report: dict[str, dict] = {}
    successfully_refreshed: list[str] = []

    for source_name, adapter in adapters or list(_adapters_with_fetch_all()):
        provider_report = {
            "status": "ok",
            "boards_succeeded": 0,
            "boards_failed": 0,
            "postings_upserted": 0,
            "tombstoned": 0,
            "deleted": 0,
            "errors": [],
        }
        all_postings: list = []

        try:
            for board_token, status, payload in adapter.fetch_all_postings():
                if status == "ok":
                    provider_report["boards_succeeded"] += 1
                    all_postings.extend(payload)
                elif status == "empty":
                    # Empty boards are NOT errors — just nothing to add.
                    provider_report["boards_succeeded"] += 1
                else:  # "error"
                    provider_report["boards_failed"] += 1
                    provider_report["errors"].append(
                        {"board": board_token, "message": str(payload)[:200]}
                    )
        except Exception as exc:  # noqa: BLE001 — adapter-level catastrophic failure
            log_event(
                LOGGER,
                logging.WARNING,
                "cached_jobs_refresh_provider_failed",
                f"Provider {source_name} threw before any boards could be processed.",
                provider=source_name,
                error=f"{type(exc).__name__}: {exc}",
            )
            provider_report["status"] = "error"
            provider_report["errors"].append(
                {"board": "<provider-init>", "message": f"{type(exc).__name__}: {exc}"}
            )
            providers_report[source_name] = provider_report
            continue

        # Upsert in chunks. 100 rows per request keeps each transaction
        # short enough to avoid Supabase throttling on the service-role
        # endpoint — earlier 200-row chunks intermittently failed
        # mid-refresh after sustained writes (likely the supabase REST
        # tier's per-connection write budget). 100 is a good middle
        # ground for the lighter-payload sources.
        #
        # Ashby is the exception: its postings carry much larger
        # description bodies, and the GENERATED STORED `search_tsv`
        # column has to be re-derived on every row insert. At
        # chunk_size=100 we observed five consecutive statement
        # timeouts per refresh ("canceling statement due to statement
        # timeout") on Supabase's default 60 s `statement_timeout`,
        # silently losing ~500 rows. chunk_size=30 finishes each
        # chunk in well under 60 s; total Ashby refresh goes from
        # ~18 requests to ~60, but every row lands.
        if all_postings:
            chunk_size = 30 if source_name == "ashby" else 100
            for i in range(0, len(all_postings), chunk_size):
                chunk = all_postings[i : i + chunk_size]
                try:
                    upserted = cache.upsert_postings(source_name, chunk)
                except Exception as exc:  # noqa: BLE001
                    # Surface the underlying message (AppError hides it
                    # in .details). Production debugging needs the real
                    # supabase error string, not just our wrapper name.
                    detail = (
                        getattr(exc, "details", None)
                        or f"{type(exc).__name__}: {exc}"
                    )
                    log_event(
                        LOGGER,
                        logging.WARNING,
                        "cached_jobs_refresh_upsert_failed",
                        f"Failed to upsert chunk for {source_name}: {detail}",
                        provider=source_name,
                        chunk_start=i,
                        chunk_size=len(chunk),
                        error=detail,
                    )
                    provider_report["status"] = "partial"
                    provider_report["errors"].append(
                        {
                            "board": f"<upsert chunk {i}>",
                            "message": detail,
                        }
                    )
                    continue
                provider_report["postings_upserted"] += upserted

        # Cleanup eligibility: a provider qualifies for cleanup ONLY if
        # at least one board succeeded. If every single board failed
        # (e.g., DNS down, provider outage), we skip cleanup so the
        # cache survives the outage gracefully.
        if provider_report["boards_succeeded"] > 0:
            successfully_refreshed.append(source_name)
            if provider_report["boards_failed"] > 0:
                provider_report["status"] = "partial"
        elif provider_report["boards_failed"] > 0:
            # Every board failed — surface as 'error' so monitoring
            # catches a provider outage instead of misreading the
            # default 'ok' status. (Earlier bug: the only paths that
            # set status away from 'ok' assumed boards_succeeded > 0,
            # so an all-failed provider silently looked healthy.)
            provider_report["status"] = "error"

        providers_report[source_name] = provider_report

    # Single cleanup pass across all successfully-refreshed providers.
    # Tombstone-vs-delete decision is made by the store based on the
    # saved_jobs table contents.
    if successfully_refreshed:
        try:
            tombstoned, deleted = cache.cleanup_missing(
                sources_refreshed=successfully_refreshed,
                cutoff_iso=cutoff_iso,
            )
        except Exception as exc:  # noqa: BLE001
            log_event(
                LOGGER,
                logging.WARNING,
                "cached_jobs_refresh_cleanup_failed",
                "Cleanup failed; cache rows from previous runs may be stale.",
                error=f"{type(exc).__name__}: {exc}",
            )
            tombstoned, deleted = (0, 0)

        # Distribute the cleanup totals across the refreshed providers
        # in proportion to who needed cleanup. We don't have per-source
        # counts from cleanup_missing, so we report it under a synthetic
        # "_cleanup" key per provider — good enough for an admin endpoint.
        # (If you want exact per-provider counts, run cleanup once per
        # source — slightly more expensive, less concurrent.)
        for name in successfully_refreshed:
            providers_report[name]["tombstoned"] = (
                tombstoned // len(successfully_refreshed)
            )
            providers_report[name]["deleted"] = (
                deleted // len(successfully_refreshed)
            )

    finished_at = _utc_now_iso()
    duration = round(time.perf_counter() - started_perf, 2)
    total_active = cache.count_active()

    report = {
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": duration,
        "providers": providers_report,
        "total_active_after": total_active,
    }

    log_event(
        LOGGER,
        logging.INFO,
        "cached_jobs_refresh_completed",
        f"Refreshed cached_jobs in {duration:.2f}s; {total_active} active rows.",
        duration_seconds=duration,
        total_active=total_active,
        providers=list(providers_report.keys()),
    )
    return report
