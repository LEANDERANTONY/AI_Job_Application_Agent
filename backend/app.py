from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from backend.config import get_backend_settings
from backend.rate_limit import limiter, rate_limit_exceeded_handler
from backend.routers.auth import router as auth_router
from backend.routers.billing import router as billing_router
from backend.routers.health import router as health_router
from backend.routers.jobs import admin_router as jobs_admin_router, router as jobs_router
from backend.routers.workspace import router as workspace_router
from src.errors import QuotaExceededError


settings = get_backend_settings()

app = FastAPI(
    title=settings.service_name,
    version=settings.service_version,
)


@app.exception_handler(QuotaExceededError)
async def quota_exceeded_handler(_request: Request, exc: QuotaExceededError):
    """Translate a `QuotaExceededError` into the canonical 429 payload.

    The error is raised from `backend.quota.check_and_increment` when
    the atomic Supabase RPC reports a P0001 quota_exceeded condition.
    Everything quota-related routes through this single handler so the
    frontend renders a uniform upgrade nudge regardless of which gate
    fired -- no per-endpoint duplication of the response shape.

    Body shape (locked by the brief):
        {
          "detail":       <one-sentence user-facing message>,
          "code":         "tier_limit_exceeded",
          "counter":      <counter_name, e.g. "tailored_applications">,
          "current":      <int, count before the rejected increment>,
          "cap":          <int, the tier's cap for this counter>,
          "reset_period": <"YYYY-MM" | "lifetime" | ...>
        }

    Status 429 mirrors the rate-limit semantics: "you've consumed your
    allowance for this window, retry later (or upgrade)." HelpmateAI
    uses 402 Payment Required for the same concept; we go with 429 per
    the brief because rate-limit middleware on Caddy / proxies already
    treats 429 specially (Retry-After header propagation, log filters)
    and we get that plumbing for free.
    """
    return JSONResponse(
        status_code=429,
        content={
            "detail": exc.user_message,
            "code": "tier_limit_exceeded",
            "counter": exc.counter,
            "current": exc.current,
            "cap": exc.cap,
            "reset_period": exc.reset_period,
            "tier": exc.tier,
        },
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
app.include_router(jobs_admin_router, prefix=settings.api_prefix)
app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(workspace_router, prefix=settings.api_prefix)
# Billing routes (LS webhook + customer portal) live under the same
# api_prefix as everything else. Final paths:
#   POST {api_prefix}/webhooks/lemonsqueezy
#   POST {api_prefix}/billing/portal
# Register the full URL (incl. /api prefix) in the LS dashboard.
app.include_router(billing_router, prefix=settings.api_prefix)
