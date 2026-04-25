from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from backend.config import get_backend_settings
from backend.rate_limit import limiter, rate_limit_exceeded_handler
from backend.routers.auth import router as auth_router
from backend.routers.health import router as health_router
from backend.routers.jobs import router as jobs_router
from backend.routers.workspace import router as workspace_router


settings = get_backend_settings()

app = FastAPI(
    title=settings.service_name,
    version=settings.service_version,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_allowed_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {
        "status": "ok",
        "service": settings.service_name,
        "frontend_url": settings.frontend_app_url,
        "health_url": f"{settings.api_prefix}/health",
    }


app.include_router(health_router, prefix=settings.api_prefix)
app.include_router(jobs_router, prefix=settings.api_prefix)
app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(workspace_router, prefix=settings.api_prefix)
