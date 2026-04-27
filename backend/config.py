import os
from dataclasses import dataclass

from src.config import GREENHOUSE_BOARD_TOKENS, JOB_BACKEND_BASE_URL, LEVER_SITE_NAMES


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
    # Auth cookie scoping. Empty domain means "host-only" (correct on
    # localhost, where landing+workspace share the same origin). In prod
    # set AUTH_COOKIE_DOMAIN=.job-application-copilot.xyz so the cookie is
    # valid on both the root and app.* subdomains.
    auth_cookie_domain: str
    auth_cookie_secure: bool
    auth_cookie_samesite: str


def _parse_bool(value: str, default: bool) -> bool:
    normalized = (value or "").strip().lower()
    if not normalized:
        return default
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
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

    return BackendSettings(
        service_name="AI Job Application Agent Backend",
        service_version="0.2.0",
        api_prefix="/api",
        backend_base_url=JOB_BACKEND_BASE_URL,
        frontend_app_url=frontend_app_url,
        cors_allowed_origins=cors_allowed_origins,
        greenhouse_board_count=len(GREENHOUSE_BOARD_TOKENS),
        lever_site_count=len(LEVER_SITE_NAMES),
        auth_cookie_domain=auth_cookie_domain,
        auth_cookie_secure=auth_cookie_secure,
        auth_cookie_samesite=auth_cookie_samesite,
    )
