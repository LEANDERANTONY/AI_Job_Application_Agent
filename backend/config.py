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
    return BackendSettings(
        service_name="AI Job Application Agent Backend",
        service_version="0.2.0",
        api_prefix="/api",
        backend_base_url=JOB_BACKEND_BASE_URL,
        frontend_app_url=frontend_app_url,
        cors_allowed_origins=cors_allowed_origins,
        greenhouse_board_count=len(GREENHOUSE_BOARD_TOKENS),
        lever_site_count=len(LEVER_SITE_NAMES),
    )
