"""Rate limiting for FastAPI endpoints.

Bucketing strategy:
- Authenticated requests bucket by Supabase user-id (decoded locally
  from the access-token JWT, no signature verification; see
  _extract_user_id_from_jwt for why this is safe).
- Anonymous requests fall back to client IP.
- Both bucket key forms are namespaced so a forged JWT 'sub' cannot
  collide with an IP-bucketed anonymous user.

Limits are exposed as named constants so each route picks a tier
explicitly and the budgets are easy to audit in one place.

A RATE_LIMIT_OVERRIDE env var (e.g. "2/minute") can be set at process
startup to globally override the budgets; used by the test suite to
exercise the limiter without firing dozens of real requests.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from typing import Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from backend.services.auth_cookies import ACCESS_TOKEN_COOKIE
from src.logging_utils import get_logger, log_event


LOGGER = get_logger(__name__)


def _extract_user_id_from_jwt(token: str) -> Optional[str]:
    """Decode a Supabase access-token JWT and return the 'sub' claim.

    This deliberately does NOT verify the signature. Two reasons that's
    safe for rate-limit bucketing only:

    1. The endpoint's auth dependency (resolve_authenticated_context)
       still verifies the token via Supabase before performing any
       privileged action. A forged token cannot do real work.
    2. A forger of someone else's 'sub' would burn through that user's
       rate quota only: a denial-of-service against one account, not
       privilege escalation. To bound that risk further, anonymous and
       authenticated buckets share a namespace prefix below so an
       attacker still has to forge a valid-shape JWT to even attempt it.

    Never use this function for authorization decisions.
    """
    if not token:
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    payload_b64 = parts[1]
    # Pad for base64url decoding
    padding = "=" * (-len(payload_b64) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload_b64 + padding)
        claims = json.loads(decoded)
    except (ValueError, json.JSONDecodeError):
        return None
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub.strip():
        return None
    return sub.strip()


def resolve_rate_limit_key(request: Request) -> str:
    """Stable key for slowapi to bucket by.

    Returns 'user:<sub>' for authenticated requests, 'ip:<addr>'
    otherwise. The namespacing prevents a forged JWT bucket from
    sharing state with an IP bucket.
    """
    access_token = (
        request.cookies.get(ACCESS_TOKEN_COOKIE, "").strip()
        or request.headers.get("X-Auth-Access-Token", "").strip()
    )
    user_id = _extract_user_id_from_jwt(access_token) if access_token else None
    if user_id:
        return f"user:{user_id}"
    return f"ip:{get_remote_address(request)}"


# Allow the test suite (or an operator on a hot fix) to lower limits
# without code changes. Format: "<count>/<window>" e.g. "2/minute".
_LIMIT_OVERRIDE = os.getenv("RATE_LIMIT_OVERRIDE", "").strip()


def _budget(default: str) -> str:
    return _LIMIT_OVERRIDE or default


# Tier 1: heavy LLM workflows (full agent pipeline or comparable).
LIMIT_HEAVY = _budget("10/minute")
# Tier 2: single LLM call or external job-board fan-out.
LIMIT_LLM = _budget("30/minute")
# Tier 3: file parsing, artifact rendering: CPU-bound but cheap.
LIMIT_PARSE = _budget("60/minute")


limiter = Limiter(
    key_func=resolve_rate_limit_key,
    # Headers are injected by SlowAPIMiddleware on the response object
    # (see backend/app.py); the decorator-level injector requires a
    # `response: Response` parameter on every route, which we avoid.
    headers_enabled=False,
)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """Return a clean JSON 429 with a Retry-After header.

    slowapi's default handler returns plain text; we want the same
    {"detail": "..."} shape as the rest of the API so the frontend
    error path is uniform.
    """
    log_event(
        LOGGER,
        logging.WARNING,
        "rate_limit_exceeded",
        "Request exceeded rate limit.",
        path=request.url.path,
        method=request.method,
        bucket_key=resolve_rate_limit_key(request),
        limit=str(exc.detail) if exc.detail else "",
    )
    response = JSONResponse(
        status_code=429,
        content={
            "detail": "Too many requests. Please slow down and try again shortly.",
            "limit": str(exc.detail) if exc.detail else None,
        },
    )
    # slowapi attaches a Retry-After header via the SlowAPIMiddleware,
    # but we set one here too for handlers that don't run middleware.
    response.headers["Retry-After"] = "60"
    return response
