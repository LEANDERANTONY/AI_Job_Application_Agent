"""HttpOnly auth cookie helpers.

Production auth flow stores tokens in two HttpOnly cookies that the
browser attaches automatically on every request to the backend (or any
same-site origin via the frontend's Next.js proxy). The frontend never
touches the raw tokens, so XSS cannot exfiltrate them.

The cookies are scoped to ``settings.auth_cookie_domain`` so the same
session is valid across the landing (``job-application-copilot.xyz``)
and workspace (``app.job-application-copilot.xyz``) subdomains. On
localhost the domain is left empty, which makes the cookies host-only
and works without further configuration.
"""

from __future__ import annotations

from fastapi import Response

from backend.config import get_backend_settings

ACCESS_TOKEN_COOKIE = "ja_access_token"
REFRESH_TOKEN_COOKIE = "ja_refresh_token"

# Sliding expiries. Refresh token controls "stay signed in" duration; the
# access cookie mirrors it so a quiet tab doesn't lose only half its
# credentials. AuthService rotates tokens on restore (Supabase mints a
# fresh access JWT from the still-valid refresh JWT), and the router
# re-issues both cookies on every restore call.
#
# The COOKIE's max_age controls when the browser purges the cookie;
# the JWT inside has its own short-lived exp claim (Supabase rotates
# on restore). Keeping both cookies at the same max_age means a user
# returning within the refresh window always has both cookies present
# for the restore call to use — without that, a 7+ day quiet user
# would lose their access cookie while the refresh cookie is still
# valid and `resolve_authenticated_context` would reject the
# half-credentialed restore, forcing an unnecessary re-login (Codex
# P1 finding on PR #2, May 2026).
_ACCESS_TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24 * 30       # 30 days
_REFRESH_TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24 * 30      # 30 days


def _cookie_kwargs() -> dict:
    settings = get_backend_settings()
    kwargs: dict = {
        "httponly": True,
        "secure": settings.auth_cookie_secure,
        "samesite": settings.auth_cookie_samesite,
        "path": "/",
    }
    if settings.auth_cookie_domain:
        kwargs["domain"] = settings.auth_cookie_domain
    return kwargs


def set_auth_cookies(
    response: Response,
    access_token: str,
    refresh_token: str,
) -> None:
    """Attach HttpOnly access/refresh cookies to ``response``.

    No-ops if either token is empty so we never overwrite a good cookie
    with a blank one.
    """
    normalized_access = (access_token or "").strip()
    normalized_refresh = (refresh_token or "").strip()
    if not normalized_access or not normalized_refresh:
        return

    kwargs = _cookie_kwargs()
    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE,
        value=normalized_access,
        max_age=_ACCESS_TOKEN_MAX_AGE_SECONDS,
        **kwargs,
    )
    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE,
        value=normalized_refresh,
        max_age=_REFRESH_TOKEN_MAX_AGE_SECONDS,
        **kwargs,
    )


def clear_auth_cookies(response: Response) -> None:
    """Remove auth cookies on the client.

    ``delete_cookie`` must be called with the same path/domain that was
    used to set the cookie; otherwise the browser keeps the original
    cookie around and the user appears signed in indefinitely.
    """
    settings = get_backend_settings()
    domain = settings.auth_cookie_domain or None
    response.delete_cookie(
        key=ACCESS_TOKEN_COOKIE,
        path="/",
        domain=domain,
    )
    response.delete_cookie(
        key=REFRESH_TOKEN_COOKIE,
        path="/",
        domain=domain,
    )
