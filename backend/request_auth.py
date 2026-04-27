from typing import Optional

from fastapi import Cookie, Header

from backend.services.auth_cookies import (
    ACCESS_TOKEN_COOKIE,
    REFRESH_TOKEN_COOKIE,
)


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
