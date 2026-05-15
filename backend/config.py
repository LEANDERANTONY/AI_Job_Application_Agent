import os
from dataclasses import dataclass

from src.config import (
    ASHBY_BOARD_TOKENS,
    GREENHOUSE_BOARD_TOKENS,
    JOB_BACKEND_BASE_URL,
    LEVER_SITE_NAMES,
    WORKDAY_BOARD_TOKENS,
)


@dataclass(frozen=True)
class BackendSettings:
    service_name: str
    service_version: str
    api_prefix: str
    backend_base_url: str
    frontend_app_url: str
    cors_allowed_origins: tuple[str, ...]
    greenhouse_board_count: int
    lever_site_count: int
    ashby_board_count: int
    workday_board_count: int
    # Auth cookie scoping. Empty domain means "host-only" (correct on
    # localhost, where landing+workspace share the same origin). In prod
    # set AUTH_COOKIE_DOMAIN=.job-application-copilot.xyz so the cookie is
    # valid on both the root and app.* subdomains.
    auth_cookie_domain: str
    auth_cookie_secure: bool
    auth_cookie_samesite: str
    # Observability — Sentry + PostHog. All four are optional; when the
    # DSN / API key is empty the observability bootstrap is a no-op (no
    # network, no SDK init). ``environment`` and ``release`` are used
    # by both vendors to slice events by deploy. ``release`` defaults
    # to the service_version when unset so a forgotten SENTRY_RELEASE
    # still groups events by something stable.
    sentry_dsn: str
    sentry_traces_sample_rate: float
    sentry_profiles_sample_rate: float
    sentry_send_default_pii: bool
    sentry_release: str
    posthog_api_key: str
    posthog_host: str
    observability_environment: str


def _parse_bool(value: str, default: bool) -> bool:
    normalized = (value or "").strip().lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_float(value: str, default: float) -> float:
    """Lenient float parser for sample-rate env vars.

    Empty / malformed values fall back to ``default`` rather than
    raising — the observability layer must never crash backend boot
    just because someone fat-fingered a sample rate."""
    stripped = (value or "").strip()
    if not stripped:
        return default
    try:
        return float(stripped)
    except (TypeError, ValueError):
        return default


def get_backend_settings() -> BackendSettings:
    frontend_app_url = (
        os.getenv("FRONTEND_APP_URL", "http://localhost:3000").strip()
        or "http://localhost:3000"
    )
    raw_cors_origins = os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:3000,http://127.0.0.1:3000",
    )
    cors_allowed_origins = tuple(
        origin.strip()
        for origin in raw_cors_origins.split(",")
        if origin.strip()
    )

    auth_cookie_domain = os.getenv("AUTH_COOKIE_DOMAIN", "").strip()
    # Default secure=true so production setups don't accidentally ship
    # plaintext cookies; flip AUTH_COOKIE_SECURE=false explicitly for
    # local HTTP dev.
    auth_cookie_secure = _parse_bool(
        os.getenv("AUTH_COOKIE_SECURE", ""),
        default=True,
    )
    raw_samesite = os.getenv("AUTH_COOKIE_SAMESITE", "lax").strip().lower()
    auth_cookie_samesite = (
        raw_samesite if raw_samesite in {"lax", "strict", "none"} else "lax"
    )

    # Observability — never raise from env parsing; missing values
    # collapse to safe defaults so a fresh checkout boots without any
    # Sentry / PostHog config at all (local dev, CI). The
    # observability bootstrap then sees an empty DSN/key and bails.
    service_version = "0.2.0"
    sentry_dsn = (os.getenv("SENTRY_DSN") or "").strip()
    sentry_traces_sample_rate = _parse_float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", ""), 0.1)
    sentry_profiles_sample_rate = _parse_float(os.getenv("SENTRY_PROFILES_SAMPLE_RATE", ""), 0.05)
    sentry_send_default_pii = _parse_bool(os.getenv("SENTRY_SEND_DEFAULT_PII", ""), False)
    sentry_release = (os.getenv("SENTRY_RELEASE") or service_version).strip() or service_version
    posthog_api_key = (os.getenv("POSTHOG_API_KEY") or "").strip()
    posthog_host = (os.getenv("POSTHOG_HOST") or "https://eu.i.posthog.com").strip()
    observability_environment = (
        os.getenv("AIJOBAGENT_ENVIRONMENT")
        or os.getenv("ENVIRONMENT")
        or "development"
    ).strip()

    return BackendSettings(
        service_name="AI Job Application Agent Backend",
        service_version=service_version,
        api_prefix="/api",
        backend_base_url=JOB_BACKEND_BASE_URL,
        frontend_app_url=frontend_app_url,
        cors_allowed_origins=cors_allowed_origins,
        greenhouse_board_count=len(GREENHOUSE_BOARD_TOKENS),
        lever_site_count=len(LEVER_SITE_NAMES),
        ashby_board_count=len(ASHBY_BOARD_TOKENS),
        workday_board_count=len(WORKDAY_BOARD_TOKENS),
        auth_cookie_domain=auth_cookie_domain,
        auth_cookie_secure=auth_cookie_secure,
        auth_cookie_samesite=auth_cookie_samesite,
        sentry_dsn=sentry_dsn,
        sentry_traces_sample_rate=sentry_traces_sample_rate,
        sentry_profiles_sample_rate=sentry_profiles_sample_rate,
        sentry_send_default_pii=sentry_send_default_pii,
        sentry_release=sentry_release,
        posthog_api_key=posthog_api_key,
        posthog_host=posthog_host,
        observability_environment=observability_environment,
    )
