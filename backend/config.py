from dataclasses import dataclass

from src.config import JOB_BACKEND_BASE_URL


@dataclass(frozen=True)
class BackendSettings:
    service_name: str = "AI Job Application Agent Backend"
    service_version: str = "0.1.0"
    api_prefix: str = "/api"
    backend_base_url: str = JOB_BACKEND_BASE_URL


def get_backend_settings() -> BackendSettings:
    return BackendSettings()
