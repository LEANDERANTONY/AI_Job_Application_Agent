from fastapi import FastAPI

from backend.config import get_backend_settings
from backend.routers.health import router as health_router
from backend.routers.jobs import router as jobs_router


settings = get_backend_settings()

app = FastAPI(
    title=settings.service_name,
    version=settings.service_version,
)
app.include_router(health_router, prefix=settings.api_prefix)
app.include_router(jobs_router, prefix=settings.api_prefix)
