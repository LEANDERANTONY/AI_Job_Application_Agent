from typing import Optional

from fastapi import Cookie, Header, HTTPException

from backend.services.auth_cookies import (
    ACCESS_TOKEN_COOKIE,
    REFRESH_TOKEN_COOKIE,
)


def _resolve_request_tokens(
    access_cookie: Optional[str],
    refresh_cookie: Optional[str],
    x_auth_access_token: Optional[str],
    x_auth_refresh_token: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    """Pull the auth token pair from the request — cookie first, header
    fallback. Shared by both the optional and the required dependency
    so the precedence rule lives in exactly one place."""
    access_token = (
        str(access_cookie or "").strip()
        or str(x_auth_access_token or "").strip()
        or None
    )
    refresh_token = (
        str(refresh_cookie or "").strip()
        or str(x_auth_refresh_token or "").strip()
        or None
    )
    return access_token, refresh_token


def get_optional_auth_tokens(
    # Primary path: HttpOnly cookies set on /auth/google/exchange and
    # /auth/session/restore. Frontend never sees them; the browser
    # attaches them automatically on every request.
    access_cookie: Optional[str] = Cookie(default=None, alias=ACCESS_TOKEN_COOKIE),
    refresh_cookie: Optional[str] = Cookie(default=None, alias=REFRESH_TOKEN_COOKIE),
    # Header fallback retained for the deploy window so any tab that
    # was open with localStorage tokens at the moment of cutover still
    # works until its next sign-in. Safe to remove once the rollout has
    # stabilized for a few days.
    x_auth_access_token: Optional[str] = Header(default=None, alias="X-Auth-Access-Token"),
    x_auth_refresh_token: Optional[str] = Header(default=None, alias="X-Auth-Refresh-Token"),
):
    return _resolve_request_tokens(
        access_cookie,
        refresh_cookie,
        x_auth_access_token,
        x_auth_refresh_token,
    )


def get_required_auth_tokens(
    access_cookie: Optional[str] = Cookie(default=None, alias=ACCESS_TOKEN_COOKIE),
    refresh_cookie: Optional[str] = Cookie(default=None, alias=REFRESH_TOKEN_COOKIE),
    x_auth_access_token: Optional[str] = Header(default=None, alias="X-Auth-Access-Token"),
    x_auth_refresh_token: Optional[str] = Header(default=None, alias="X-Auth-Refresh-Token"),
):
    """Like ``get_optional_auth_tokens`` but rejects anonymous requests
    with a 401 instead of returning ``(None, None)``.

    The unified LLM token meter (report.md "Unified LLM token meter")
    requires every LLM operation to be attributable to a ``user_id`` —
    an anonymous call has nothing to meter and would be an un-capped
    abuse vector. Every route that spends model tokens (resume / JD
    parse, analysis run, assistant, résumé-builder start / message /
    generate) depends on THIS, not the optional variant.

    Raising from a dependency means the 401 is committed before the
    route body runs — which also makes it safe for the streaming
    assistant route, where a mid-stream status change is impossible.
    """
    access_token, refresh_token = _resolve_request_tokens(
        access_cookie,
        refresh_cookie,
        x_auth_access_token,
        x_auth_refresh_token,
    )
    if not (access_token and refresh_token):
        raise HTTPException(
            status_code=401,
            detail="Sign in with Google to use the AI workspace.",
        )
    return access_token, refresh_token
