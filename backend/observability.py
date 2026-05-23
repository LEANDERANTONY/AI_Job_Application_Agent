"""Centralized Sentry + PostHog bootstrap for the FastAPI service.

Mirrors the HelpmateAI sibling project (``backend/observability.py``)
so both repos use the same patterns; the two products are tracked in
separate Sentry/PostHog projects (jobagent-* vs helpmate-*) but the
code shape stays identical.

Why a dedicated module:

1. **Single import order.** Sentry's FastAPI integration must be
   initialized BEFORE ``FastAPI()`` is constructed so its ASGI
   middleware wraps the app. Doing that inline in ``backend/app.py``
   would mean spreading SDK-config concerns across the top of the
   bootstrap. Pulling everything into
   ``initialize_observability(settings)`` keeps the call site one line.

2. **Quiet no-op path.** Both clients silently degrade when their
   credentials are missing — there is NO production assert that says
   "Sentry must be configured". Local dev, CI, and the test suite
   should never have to set ``SENTRY_DSN`` to use the app. The
   helpers below check the relevant settings field and bail when
   unset.

PII posture
-----------
``send_default_pii`` defaults to False. We deliberately do NOT ship
request bodies or query params to Sentry by default. The workspace
endpoints can carry user resume content, target-job descriptions, and
free-text "describe yourself" answers — none of that belongs on a
third-party crash log. Setting ``SENTRY_SEND_DEFAULT_PII=true`` is an
explicit opt-in for ops who have decided this is acceptable.

PostHog identification happens AFTER auth resolves (so we get the
Supabase user id), via ``capture_event_for_user`` below — never via
default SDK behavior that would auto-grab cookies / IPs.

Pytest guard
------------
``_running_under_pytest`` short-circuits Sentry init when ``PYTEST_CURRENT_TEST``
is set or ``pytest`` is in ``sys.modules``. Without it, a local
``uv run pytest`` with a real SENTRY_DSN in ``.env`` fires every
test-only crash (mock exceptions, expected HTTPException 4xx paths)
into the production project. HelpmateAI hit this on its first deploy;
the guard kept the issue feed clean.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager, suppress
from typing import Any

from backend.config import BackendSettings


logger = logging.getLogger(__name__)


# Module-level PostHog client handle. Set once in
# ``initialize_observability`` and read by ``capture_event``. Kept on
# the module — rather than passed through every route — because
# PostHog's Python client is itself thread-safe and meant to be
# instantiated once per process.
_posthog_client: Any | None = None


def initialize_observability(settings: BackendSettings) -> None:
    """Initialize Sentry + PostHog using values from ``BackendSettings``.

    Safe to call once at import time. Calling twice is a no-op for
    Sentry (the SDK detects already-initialized state) and reuses the
    existing PostHog client.
    """
    _init_sentry(settings)
    _init_posthog(settings)


def _running_under_pytest() -> bool:
    """True when the current process was launched by pytest.

    The flag matters because the local ``.env`` carries a real
    SENTRY_DSN for dev work; without this guard every ``uv run pytest``
    invocation fires test-only crashes into the production Sentry
    project. ``PYTEST_CURRENT_TEST`` is the canonical signal — pytest
    sets it before each test and unsets it after. ``"pytest" in
    sys.modules`` is the secondary check that catches the import-time
    bootstrap window before the env var lands.
    """
    import os
    import sys

    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    if "pytest" in sys.modules:
        return True
    return False


def _drop_expected_http_exceptions(event, hint):
    """``before_send`` filter — drop FastAPI HTTPException events.

    FastAPI uses HTTPException as a structured-flow-control mechanism:
    every 4xx response (auth failure, validation reject, quota cap) and
    several intentional 5xx ones ("Feature not configured", "Service
    unavailable") raise HTTPException, which then becomes the response.
    These are NOT bugs — they're the contract. Without this filter,
    every rejected workspace request, every disabled-feature ping, and
    every quota cap fills the Sentry issue feed.

    We let through:
      • Bare ``HTTPException`` with status_code >= 500 that ISN'T a
        clean 503 from one of our "not configured" / "temporarily
        unavailable" guards — those still usually represent a backend
        problem worth seeing.
      • Every non-HTTPException error (RuntimeError, IntegrityError,
        OpenAI APIError, Supabase APIError, etc.) — those are the
        high-signal ones.

    Returning None drops the event; returning ``event`` keeps it.
    """
    exc_info = hint.get("exc_info") if hint else None
    if not exc_info:
        return event
    exc_type = exc_info[0]
    if exc_type is None:
        return event
    try:
        from fastapi import HTTPException
    except Exception:
        return event
    if not issubclass(exc_type, HTTPException):
        return event
    exc_value = exc_info[1]
    status_code = getattr(exc_value, "status_code", None)
    if status_code is None or status_code < 500:
        return None
    detail = getattr(exc_value, "detail", "") or ""
    if isinstance(detail, str):
        lowered = detail.lower()
        if "not configured" in lowered or "temporarily unavailable" in lowered:
            return None
    return event


def _init_sentry(settings: BackendSettings) -> None:
    if not settings.sentry_dsn:
        logger.debug("SENTRY_DSN not configured; skipping Sentry init.")
        return
    if _running_under_pytest():
        logger.debug("Pytest detected; skipping Sentry init to avoid polluting prod issues with test fixtures.")
        return
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("sentry_sdk import failed (%s); Sentry disabled.", exc)
        return

    integrations: list = [
        FastApiIntegration(transaction_style="endpoint"),
        StarletteIntegration(transaction_style="endpoint"),
        LoggingIntegration(
            level=logging.INFO,        # breadcrumb threshold
            event_level=logging.ERROR, # event threshold — only ERROR+ becomes a Sentry issue
        ),
    ]
    # OpenAI auto-instrumentation. The SDK ships a first-class
    # OpenAIIntegration that wraps the client's HTTP calls and emits
    # AI-aware spans (token count, model, latency, total cost). Critical
    # for an LLM-heavy product: every workspace endpoint becomes a
    # parent span with the LLM call as a child, so a slow tailoring
    # response can be attributed to OpenAI or to retrieval. The
    # integration is opt-in below; if the SDK rev doesn't ship it
    # (older versions) we silently skip.
    try:
        from sentry_sdk.integrations.openai import OpenAIIntegration

        integrations.append(
            OpenAIIntegration(
                include_prompts=False,  # don't ship user PII to Sentry
            )
        )
    except Exception:
        # SDK doesn't ship the OpenAI integration; not fatal — the
        # rest of Sentry still works, we just lose the AI-aware
        # span attribution.
        pass

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.observability_environment,
        release=settings.sentry_release,
        send_default_pii=settings.sentry_send_default_pii,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        profiles_sample_rate=settings.sentry_profiles_sample_rate,
        # Enable the new Sentry Logs product (separate from breadcrumbs).
        # Requires sentry-sdk>=2.35.0 — we pin >=2.35 in pyproject.
        enable_logs=True,
        integrations=integrations,
        # Drop expected HTTPException events (intentional 4xx + dev
        # 5xx "not configured" guards) before they leave the process.
        # Keeps the issue feed focused on actual bugs.
        before_send=_drop_expected_http_exceptions,
    )
    logger.info(
        "Sentry initialized (environment=%s, traces=%.2f, profiles=%.2f, integrations=%d).",
        settings.observability_environment,
        settings.sentry_traces_sample_rate,
        settings.sentry_profiles_sample_rate,
        len(integrations),
    )


def _init_posthog(settings: BackendSettings) -> None:
    global _posthog_client
    if not settings.posthog_api_key:
        logger.debug("POSTHOG_API_KEY not configured; skipping PostHog init.")
        _posthog_client = None
        return
    if _running_under_pytest():
        # The local .env carries a real POSTHOG_API_KEY for dev work;
        # without this guard every test that exercises an instrumented
        # route (feedback, workspace, resume-builder, a quota reject)
        # ships events into the production analytics project. Discovered
        # when the assistant_turn dashboard showed ~50% thumbs-down
        # purely from test_feedback's user-test fixture firing paired
        # up/down events ~80 ms apart. Mirrors the _init_sentry pytest
        # guard above + HelpmateAI's _init_posthog guard.
        logger.debug("Pytest detected; skipping PostHog init.")
        _posthog_client = None
        return
    try:
        from posthog import Posthog
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("posthog import failed (%s); PostHog disabled.", exc)
        _posthog_client = None
        return

    # Posthog client buffers events and flushes on its own schedule
    # (default 10s or 100 events). For long-running FastAPI workers
    # this is the right behavior — we don't want a synchronous network
    # round-trip on every workspace response. The atexit handler the
    # SDK registers takes care of flushing at process shutdown; the
    # lifespan handler in ``backend/app.py`` also calls
    # ``shutdown_observability()`` explicitly for cases where atexit
    # doesn't fire (SIGTERM from the container orchestrator).
    _posthog_client = Posthog(
        project_api_key=settings.posthog_api_key,
        host=settings.posthog_host,
    )
    logger.info("PostHog initialized (host=%s).", settings.posthog_host)


# Every server-side event auto-tags with ``product: "jobagent"`` so
# the shared PostHog project (179885, free-tier 1-project limit) can
# split AI Job Agent's events from HelpmateAI's via a simple insight
# filter (``where event.product = 'jobagent'``). HelpmateAI's
# capture_event does the same with ``product: "helpmate"``. Keeps the
# two products on the same free-tier quota while still giving us
# product-scoped dashboards.
_PRODUCT_TAG = "jobagent"


def capture_event(
    distinct_id: str,
    event: str,
    properties: dict[str, Any] | None = None,
) -> None:
    """Send a server-side analytics event to PostHog.

    No-op when PostHog is not configured (the module-level client is
    None). All exceptions are swallowed — analytics failures must
    never break a workspace response. The most common failure mode
    (PostHog rate limit on the free tier) just means the event is
    dropped on the floor, which is correct: telemetry is best-effort.

    ``distinct_id`` is the Supabase user id from the auth context on
    the request scope — never a session token or anything that could
    leak credentials. A falsy ``distinct_id`` (an anonymous or
    unresolved caller) falls back to the constant ``"anonymous"`` so
    the event is still counted — funnel volume must not silently drop
    just because a caller wasn't signed in.

    All events automatically include ``product: "jobagent"`` so the
    shared PostHog project can split events by product on the
    dashboards. Caller-supplied ``properties`` win on conflict, but
    a caller would have no reason to override the product tag.
    """
    if _posthog_client is None:
        return
    merged: dict[str, Any] = {"product": _PRODUCT_TAG}
    if properties:
        merged.update(properties)
    with suppress(Exception):
        _posthog_client.capture(
            distinct_id=distinct_id or "anonymous",
            event=event,
            properties=merged,
        )


def shutdown_observability() -> None:
    """Flush + close the PostHog client on process shutdown.

    PostHog buffers events; calling ``shutdown`` synchronously drains
    that buffer to the API. The SDK registers an atexit handler that
    does the same thing — we expose this as an explicit hook so the
    FastAPI lifespan can call it on graceful termination and not rely
    on interpreter atexit timing alone.
    """
    global _posthog_client
    if _posthog_client is None:
        return
    with suppress(Exception):
        _posthog_client.shutdown()
    _posthog_client = None


# ---------------------------------------------------------------------------
# Sentry Cron Monitors — scheduled-job check-ins
# ---------------------------------------------------------------------------
#
# Sentry "Cron Monitors" track whether a scheduled job ran, ran on
# time, and ran to completion. Two pg_cron-driven jobs use them:
#
#   cached-jobs-refresh      — the 4-hourly cached_jobs refresh
#                              (/admin/refresh-cache).
#   cached-jobs-healthcheck  — the daily refresh healthcheck
#                              (/admin/refresh-healthcheck).
#
# A check-in is upsert-style: passing `monitor_config` CREATES or
# UPDATES the monitor (slug, schedule, alert thresholds) — so the
# monitor is defined here in code and never needs setup in the Sentry
# UI. If a job stops calling in, Sentry raises a "missed check-in"
# issue from the schedule alone — the signal that catches "pg_cron
# silently stopped firing", which an in-process logger cannot see.

# Monitor configs, passed as `monitor_config` to `sentry_cron_monitor`.
# `checkin_margin` / `max_runtime` are in MINUTES.
CACHED_JOBS_REFRESH_MONITOR_SLUG = "cached-jobs-refresh"
CACHED_JOBS_REFRESH_MONITOR_CONFIG: dict[str, Any] = {
    "schedule": {"type": "crontab", "value": "0 */4 * * *"},
    "timezone": "UTC",
    "checkin_margin": 30,   # minutes a run may start late before "missed"
    "max_runtime": 25,      # minutes a run may take before "timed out"
    "failure_issue_threshold": 1,
    "recovery_threshold": 1,
}

CACHED_JOBS_HEALTHCHECK_MONITOR_SLUG = "cached-jobs-healthcheck"
CACHED_JOBS_HEALTHCHECK_MONITOR_CONFIG: dict[str, Any] = {
    "schedule": {"type": "crontab", "value": "0 6 * * *"},
    "timezone": "UTC",
    "checkin_margin": 60,
    "max_runtime": 5,
    "failure_issue_threshold": 1,
    "recovery_threshold": 1,
}


def _sentry_active() -> bool:
    """True when cron check-ins should actually be sent.

    The hard requirement is the pytest guard — the test suite must
    never create or ping the production cron monitors (the local
    ``.env`` carries a real DSN). Beyond that, ``capture_checkin`` is
    itself a no-op when Sentry has no active client, so this stays
    deliberately small.
    """
    if _running_under_pytest():
        return False
    try:
        import sentry_sdk
    except Exception:  # pragma: no cover — defensive
        return False
    client = sentry_sdk.get_client()
    return bool(client) and client.is_active()


@contextmanager
def sentry_cron_monitor(
    monitor_slug: str,
    monitor_config: dict[str, Any] | None = None,
):
    """Wrap a scheduled-job body in a Sentry cron check-in.

    Emits an ``in_progress`` check-in on entry and resolves it to
    ``ok`` on a clean exit, or ``error`` if the body raises (the
    exception is always re-raised). A no-op when Sentry is disabled or
    running under pytest.

    ``monitor_config`` — when supplied — upserts the monitor's schedule
    and alert thresholds, so the monitor is defined from code and never
    needs touching in the Sentry UI.

    Telemetry must never break the job it wraps: every Sentry call here
    is defensively guarded, so a check-in failure cannot mask or
    replace the body's own success or exception.
    """
    if not _sentry_active():
        yield
        return

    try:
        from sentry_sdk.crons import capture_checkin
    except Exception:  # pragma: no cover — defensive; never break the job
        yield
        return

    started = time.monotonic()
    check_in_id = None
    try:
        check_in_id = capture_checkin(
            monitor_slug=monitor_slug,
            status="in_progress",
            monitor_config=monitor_config,
        )
    except Exception:  # pragma: no cover — telemetry is best-effort
        logger.debug("Sentry in_progress check-in failed for %s", monitor_slug)

    try:
        yield
    except Exception:
        with suppress(Exception):
            capture_checkin(
                monitor_slug=monitor_slug,
                check_in_id=check_in_id,
                status="error",
                duration=time.monotonic() - started,
                monitor_config=monitor_config,
            )
        raise
    else:
        with suppress(Exception):
            capture_checkin(
                monitor_slug=monitor_slug,
                check_in_id=check_in_id,
                status="ok",
                duration=time.monotonic() - started,
                monitor_config=monitor_config,
            )
