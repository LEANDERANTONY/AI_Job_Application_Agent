"""Daily health check for the cached_jobs 4-hourly refresh pipeline.

The cached_jobs cache is kept current by ``/admin/refresh-cache``, run
every 4 hours by Supabase pg_cron. That worker is deliberately
resilient — a per-board HTTP failure is caught and logged so one bad
board never poisons a whole refresh (see ``job_cache_service``). The
flip side of that resilience: a *slow* degradation does not announce
itself. A board that quietly starts returning zero jobs, an
embed-on-write backlog, or a pg_cron schedule that silently stopped
firing all leave the API up and the cache merely... wrong. Uptime
monitoring catches a crashed API. It does not catch a stale cache
behind a healthy one.

``run_refresh_healthcheck`` closes that gap. It runs once a day, reads
aggregate stats off ``cached_jobs`` in a single RPC round trip, and
asserts a handful of invariants:

  * refresh_recent     — the freshest row was re-seen within ~5h, so
                         the 4-hourly refresh is still firing at all.
  * refresh_complete   — the stale fraction is small, so the recent
                         refreshes actually covered the corpus.
  * sources_present    — every ATS adapter still contributes rows.
  * embeddings_healthy — the NULL-embedding backlog is bounded (only
                         meaningful while hybrid search is enabled).
  * corpus_sane        — the active corpus has not collapsed.

A degraded result is logged at ERROR, which the Sentry
LoggingIntegration turns into an issue — so a quietly-rotting cache
pages the operator the same way a crash does. This service NEVER
mutates anything; it is a read-only assertion over the table the
refresh worker writes.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from src.cached_jobs_store import CachedJobsStore
from src.config import is_job_search_hybrid_enabled
from src.logging_utils import get_logger, log_event

LOGGER = get_logger(__name__)


# Every ATS adapter the refresh worker fans out to. The healthcheck
# fails if ANY of these contributes zero active rows — the signature
# of a board-token misconfig or a provider that changed its API out
# from under an adapter.
EXPECTED_SOURCES: tuple[str, ...] = ("greenhouse", "lever", "ashby", "workday")

# A row's `last_seen_at` is rewritten by every refresh that still sees
# it upstream. The refresh runs every 4h, so a row not re-seen within
# 5h means at least one refresh failed to cover it.
STALE_AFTER_HOURS = 5

# Fraction of the active corpus allowed to be stale before the refresh
# is treated as broken rather than merely slipping. A few rows aging
# out between a board going quiet and the next cleanup is normal; a
# fifth of the table is not.
MAX_STALE_FRACTION = 0.20

# Ceiling on the NULL-embedding backlog. Embed-on-write embeds every
# newly-cached row, so in steady state this sits near zero; 500+ rows
# without a vector means embed-on-write is failing and Tier 2 recall
# is rotting. Only checked while hybrid search is enabled.
MAX_NULL_EMBEDDINGS = 500

# Floor on the active corpus. The real table is ~13-14k rows; below
# this, a refresh has gone catastrophically wrong (mass cleanup, a
# truncated table) regardless of what the other checks report.
MIN_CORPUS_SIZE = 1000


def run_refresh_healthcheck(store: CachedJobsStore | None = None) -> dict[str, Any]:
    """Evaluate the health of the cached_jobs refresh pipeline.

    Returns a JSON-serializable report::

        {
          "checked_at": "2026-..",
          "overall": "ok" | "degraded",
          "checks": [
            {"name": "refresh_recent", "status": "pass"|"fail", "detail": ".."},
            ...
          ],
          "stats": { ...raw cached_jobs_health_stats payload... },
        }

    A degraded ``overall`` is additionally logged at ERROR so the
    Sentry LoggingIntegration raises an issue. A degraded result does
    NOT raise — degradation is data, returned in the report.

    It DOES raise ``RuntimeError`` when the healthcheck cannot run at
    all (store unconfigured, or the stats RPC failed). "The check
    could not run" is a different failure from "the check ran and
    found problems", and the endpoint maps the two to different
    responses.
    """
    cache = store or CachedJobsStore()
    if not cache.is_configured():
        raise RuntimeError(
            "cached_jobs store is not configured (SUPABASE_URL + "
            "SUPABASE_SERVICE_ROLE_KEY required)."
        )

    try:
        stats = cache.health_stats(stale_after_hours=STALE_AFTER_HOURS)
    except Exception as exc:  # noqa: BLE001 — surfaced as a RuntimeError
        raise RuntimeError(
            "Failed to read cached_jobs health stats: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    checks = _evaluate_checks(stats)
    failed = [c for c in checks if c["status"] != "pass"]
    overall = "degraded" if failed else "ok"
    report: dict[str, Any] = {
        "checked_at": stats.get("checked_at"),
        "overall": overall,
        "checks": checks,
        "stats": stats,
    }

    if failed:
        # ERROR level -> the Sentry LoggingIntegration raises an issue.
        log_event(
            LOGGER,
            logging.ERROR,
            "cached_jobs_refresh_healthcheck_degraded",
            "cached_jobs refresh healthcheck degraded — "
            + "; ".join(f"{c['name']}: {c['detail']}" for c in failed),
            overall=overall,
            failed_checks=[c["name"] for c in failed],
            stats=stats,
        )
    else:
        log_event(
            LOGGER,
            logging.INFO,
            "cached_jobs_refresh_healthcheck_ok",
            "cached_jobs refresh healthcheck passed all checks.",
            total_active=stats.get("total_active"),
        )
    return report


def _evaluate_checks(stats: dict[str, Any]) -> list[dict[str, str]]:
    """Run every invariant against the health-stats payload.

    Each check is independent and total — it never raises, it reports
    pass/fail with a human-readable ``detail``. List order is the
    order the report renders them.
    """
    total = _as_int(stats.get("total_active"))
    stale = _as_int(stats.get("stale_count"))
    null_embeddings = _as_int(stats.get("null_embedding_count"))
    per_source = stats.get("per_source") or {}

    checks: list[dict[str, str]] = []

    # 1. refresh_recent — the most-recently-seen row was touched within
    #    STALE_AFTER_HOURS. If even the freshest row is older than that,
    #    the 4-hourly refresh has stopped firing entirely.
    age_hours = _hours_since(stats.get("newest_last_seen_at"))
    if age_hours is None:
        checks.append(_check(
            "refresh_recent", False,
            "no newest_last_seen_at timestamp — table empty or refresh "
            "never ran",
        ))
    else:
        checks.append(_check(
            "refresh_recent", age_hours <= STALE_AFTER_HOURS,
            f"most recent refresh touched a row {age_hours:.1f}h ago "
            f"(threshold {STALE_AFTER_HOURS}h)",
        ))

    # 2. refresh_complete — the stale fraction is within tolerance. A
    #    refresh that fired but covered only part of the corpus leaves
    #    a wedge of un-touched rows; a large wedge means boards failed.
    if total <= 0:
        checks.append(_check(
            "refresh_complete", False, "no active rows to evaluate",
        ))
    else:
        stale_fraction = stale / total
        checks.append(_check(
            "refresh_complete", stale_fraction <= MAX_STALE_FRACTION,
            f"{stale}/{total} active rows ({stale_fraction:.1%}) not "
            f"re-seen within {STALE_AFTER_HOURS}h "
            f"(threshold {MAX_STALE_FRACTION:.0%})",
        ))

    # 3. sources_present — every ATS adapter contributes >= 1 active row.
    missing = [s for s in EXPECTED_SOURCES if _as_int(per_source.get(s)) <= 0]
    checks.append(_check(
        "sources_present", not missing,
        "all four job boards present"
        if not missing
        else f"job sources with zero active rows: {', '.join(missing)}",
    ))

    # 4. embeddings_healthy — the NULL-embedding backlog is bounded.
    #    Only meaningful with hybrid search on: embed-on-write only runs
    #    then, so with hybrid OFF a growing NULL count is expected, not
    #    a fault.
    if not is_job_search_hybrid_enabled():
        checks.append(_check(
            "embeddings_healthy", True,
            "skipped — hybrid search disabled (JOB_SEARCH_HYBRID_ENABLED)",
        ))
    else:
        checks.append(_check(
            "embeddings_healthy", null_embeddings <= MAX_NULL_EMBEDDINGS,
            f"{null_embeddings} active rows missing an embedding "
            f"(threshold {MAX_NULL_EMBEDDINGS})",
        ))

    # 5. corpus_sane — the active corpus has not collapsed.
    checks.append(_check(
        "corpus_sane", total >= MIN_CORPUS_SIZE,
        f"{total} active rows (floor {MIN_CORPUS_SIZE})",
    ))

    return checks


def _check(name: str, passed: bool, detail: str) -> dict[str, str]:
    """One check-result row for the report."""
    return {
        "name": name,
        "status": "pass" if passed else "fail",
        "detail": detail,
    }


def _as_int(value: Any) -> int:
    """Coerce an RPC numeric field to int; 0 on anything unparseable."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _hours_since(timestamp: Any) -> float | None:
    """Hours between an ISO-8601 timestamp and now (UTC).

    Returns None when the value is missing or unparseable — the caller
    treats that as a failed check rather than silently passing.
    """
    raw = str(timestamp or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - parsed).total_seconds() / 3600.0
