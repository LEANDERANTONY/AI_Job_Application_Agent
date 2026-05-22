"""Tests for backend/services/refresh_healthcheck_service.

A fake CachedJobsStore returns canned `cached_jobs_health_stats`
payloads so the check logic is exercised without touching Supabase.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest

from backend.services import refresh_healthcheck_service as svc
from backend.services.refresh_healthcheck_service import run_refresh_healthcheck


# ---------------------------------------------------------------------------
# Helpers + fakes
# ---------------------------------------------------------------------------


def _iso(hours_ago: float) -> str:
    """ISO-8601 timestamp `hours_ago` hours before now (UTC)."""
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


def _healthy_stats(**overrides):
    """A health_stats payload that passes every check."""
    stats = {
        "checked_at": _iso(0),
        "stale_after_hours": 5,
        "total_active": 13500,
        "newest_last_seen_at": _iso(1),
        "oldest_last_seen_at": _iso(3.5),
        "stale_count": 120,
        "null_embedding_count": 8,
        "per_source": {
            "greenhouse": 9000,
            "lever": 500,
            "ashby": 3000,
            "workday": 1000,
        },
    }
    stats.update(overrides)
    return stats


class _FakeStore:
    """Mirrors the slice of CachedJobsStore the healthcheck uses."""

    def __init__(self, stats=None, *, configured=True, raise_on_stats=None):
        self._stats = _healthy_stats() if stats is None else stats
        self._configured = configured
        self._raise = raise_on_stats
        self.health_calls = []

    def is_configured(self):
        return self._configured

    def health_stats(self, *, stale_after_hours=5):
        self.health_calls.append(stale_after_hours)
        if self._raise is not None:
            raise self._raise
        return self._stats


@pytest.fixture(autouse=True)
def _hybrid_on(monkeypatch):
    """Default every test to the 'hybrid enabled' branch so the
    embeddings check actually exercises its threshold. The one test
    that cares about the disabled branch overrides this."""
    monkeypatch.setattr(svc, "is_job_search_hybrid_enabled", lambda: True)


def _status(report, check_name):
    """The status string of a named check within a report."""
    return next(c["status"] for c in report["checks"] if c["name"] == check_name)


def _detail(report, check_name):
    """The detail string of a named check within a report."""
    return next(c["detail"] for c in report["checks"] if c["name"] == check_name)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_healthy_corpus_passes_every_check():
    store = _FakeStore()
    report = run_refresh_healthcheck(store=store)

    assert report["overall"] == "ok"
    assert {c["name"] for c in report["checks"]} == {
        "refresh_recent",
        "refresh_complete",
        "sources_present",
        "embeddings_healthy",
        "corpus_sane",
    }
    assert all(c["status"] == "pass" for c in report["checks"])
    # The staleness threshold reached the store.
    assert store.health_calls == [svc.STALE_AFTER_HOURS]
    # Raw stats are echoed for diagnostics.
    assert report["stats"]["total_active"] == 13500


# ---------------------------------------------------------------------------
# Individual degradation modes
# ---------------------------------------------------------------------------


def test_degraded_when_newest_row_is_stale():
    """Freshest row last seen 9h ago → the 4-hourly refresh stopped."""
    store = _FakeStore(_healthy_stats(newest_last_seen_at=_iso(9)))
    report = run_refresh_healthcheck(store=store)

    assert report["overall"] == "degraded"
    assert _status(report, "refresh_recent") == "fail"


def test_degraded_when_newest_timestamp_missing():
    """A NULL newest_last_seen_at (empty table) fails refresh_recent
    rather than silently passing."""
    store = _FakeStore(_healthy_stats(newest_last_seen_at=None))
    report = run_refresh_healthcheck(store=store)

    assert _status(report, "refresh_recent") == "fail"
    assert report["overall"] == "degraded"


def test_degraded_when_stale_fraction_exceeds_tolerance():
    """A refresh that fired but skipped most of the corpus → a large
    stale wedge → refresh_complete fails."""
    store = _FakeStore(_healthy_stats(total_active=10000, stale_count=4000))
    report = run_refresh_healthcheck(store=store)

    assert _status(report, "refresh_complete") == "fail"
    assert report["overall"] == "degraded"


def test_degraded_when_a_job_board_has_zero_rows():
    """A board contributing zero active rows → sources_present fails
    and names the missing board."""
    stats = _healthy_stats()
    stats["per_source"] = {"greenhouse": 9000, "lever": 500, "ashby": 3000}
    store = _FakeStore(stats)
    report = run_refresh_healthcheck(store=store)

    assert _status(report, "sources_present") == "fail"
    assert "workday" in _detail(report, "sources_present")
    assert report["overall"] == "degraded"


def test_degraded_when_embedding_backlog_is_large():
    """Hybrid on + a big NULL-embedding backlog → embeddings_healthy
    fails (embed-on-write is broken)."""
    store = _FakeStore(_healthy_stats(null_embedding_count=6000))
    report = run_refresh_healthcheck(store=store)

    assert _status(report, "embeddings_healthy") == "fail"
    assert report["overall"] == "degraded"


def test_embeddings_check_skipped_when_hybrid_disabled(monkeypatch):
    """Hybrid OFF → a NULL-embedding backlog is expected, not a fault.
    The embeddings check passes (skipped) and overall stays ok."""
    monkeypatch.setattr(svc, "is_job_search_hybrid_enabled", lambda: False)
    store = _FakeStore(_healthy_stats(null_embedding_count=99999))
    report = run_refresh_healthcheck(store=store)

    assert _status(report, "embeddings_healthy") == "pass"
    assert "skipped" in _detail(report, "embeddings_healthy")
    assert report["overall"] == "ok"


def test_degraded_when_corpus_has_collapsed():
    """An active corpus far below the floor → corpus_sane fails."""
    store = _FakeStore(_healthy_stats(total_active=42, stale_count=0))
    report = run_refresh_healthcheck(store=store)

    assert _status(report, "corpus_sane") == "fail"
    assert report["overall"] == "degraded"


# ---------------------------------------------------------------------------
# Hard failures — the check cannot run at all
# ---------------------------------------------------------------------------


def test_raises_when_store_unconfigured():
    """No service-role key → RuntimeError, not a silent degraded
    report. 'Cannot run' is distinct from 'ran and found problems'."""
    with pytest.raises(RuntimeError, match="not configured"):
        run_refresh_healthcheck(store=_FakeStore(configured=False))


def test_raises_when_health_stats_rpc_fails():
    """The stats RPC raising → RuntimeError. The endpoint maps this to
    a 503, distinct from a 200 degraded report."""
    store = _FakeStore(raise_on_stats=RuntimeError("supabase 500"))
    with pytest.raises(RuntimeError, match="health stats"):
        run_refresh_healthcheck(store=store)


# ---------------------------------------------------------------------------
# Alerting contract — a degraded result must log at ERROR (-> Sentry issue)
# ---------------------------------------------------------------------------


def test_degraded_result_logs_at_error(caplog):
    """A degraded outcome logs at ERROR — that is what the Sentry
    LoggingIntegration turns into an issue."""
    store = _FakeStore(_healthy_stats(newest_last_seen_at=_iso(12)))
    with caplog.at_level(logging.ERROR):
        run_refresh_healthcheck(store=store)

    assert any(
        rec.levelno == logging.ERROR
        and "healthcheck degraded" in rec.getMessage()
        for rec in caplog.records
    )


def test_healthy_result_does_not_log_at_error(caplog):
    """A clean run must NOT log at ERROR — no false Sentry issues."""
    store = _FakeStore()
    with caplog.at_level(logging.ERROR):
        run_refresh_healthcheck(store=store)

    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []
