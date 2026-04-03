from dataclasses import dataclass

from src.config import GREENHOUSE_BOARD_TOKENS, JOB_BACKEND_BASE_URL, LEVER_SITE_NAMES


@dataclass(frozen=True)
class BackendSettings:
    service_name: str = "AI Job Application Agent Backend"
    service_version: str = "0.1.0"
    api_prefix: str = "/api"
    backend_base_url: str = JOB_BACKEND_BASE_URL
    greenhouse_board_count: int = len(GREENHOUSE_BOARD_TOKENS)
    lever_site_count: int = len(LEVER_SITE_NAMES)


def get_backend_settings() -> BackendSettings:
    return BackendSettings()
