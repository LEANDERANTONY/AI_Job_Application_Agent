from fastapi import APIRouter, Depends, HTTPException, Response

from backend.auth_models import (
    GoogleSignInExchangeRequestModel,
    GoogleSignInStartRequestModel,
)
from backend.request_auth import get_optional_auth_tokens
from backend.services.auth_cookies import (
    clear_auth_cookies,
    set_auth_cookies,
)
from backend.services.auth_session_service import (
    exchange_google_code,
    restore_authenticated_session,
    sign_out_authenticated_session,
    start_google_sign_in,
)
from src.errors import AppError


router = APIRouter(prefix="/auth", tags=["auth"])


def _raise_http_error(error: AppError):
    raise HTTPException(status_code=400, detail=error.user_message)


def _scrub_session_tokens(payload: dict) -> dict:
    """Strip raw access/refresh tokens out of the JSON body.

    Tokens live in HttpOnly cookies now; the frontend has no business
    reading them, so we don't ship them to the browser. We keep the
    ``session`` key with a non-token shape so the existing TS type
    can still pattern-match against authenticated responses.
    """
    if not isinstance(payload, dict):
        return payload
    if payload.get("session"):
        payload["session"] = {"authenticated": True}
    return payload


def _apply_session_cookies(response: Response, payload: dict) -> None:
    session = payload.get("session") if isinstance(payload, dict) else None
    if not isinstance(session, dict):
        return
    access_token = str(session.get("access_token") or "").strip()
    refresh_token = str(session.get("refresh_token") or "").strip()
    if access_token and refresh_token:
        set_auth_cookies(response, access_token, refresh_token)


@router.post("/google/start")
def start_google_sign_in_route(payload: GoogleSignInStartRequestModel):
    try:
        return start_google_sign_in(redirect_url=payload.redirect_url)
    except AppError as error:
        _raise_http_error(error)


@router.post("/google/exchange")
def exchange_google_code_route(
    payload: GoogleSignInExchangeRequestModel,
    response: Response,
):
    try:
        result = exchange_google_code(
            auth_code=payload.auth_code,
            auth_flow=payload.auth_flow,
            redirect_url=payload.redirect_url,
        )
        _apply_session_cookies(response, result)
        return _scrub_session_tokens(result)
    except AppError as error:
        _raise_http_error(error)


@router.post("/session/restore")
def restore_session_route(
    response: Response,
    auth_tokens=Depends(get_optional_auth_tokens),
):
    access_token, refresh_token = auth_tokens
    try:
        result = restore_authenticated_session(
            access_token=access_token or "",
            refresh_token=refresh_token or "",
        )
        # Re-issue the cookies on each restore. Even if the underlying
        # tokens didn't rotate, this slides the browser-side expiry so a
        # daily-active user effectively stays signed in indefinitely.
        _apply_session_cookies(response, result)
        return _scrub_session_tokens(result)
    except AppError as error:
        _raise_http_error(error)


@router.post("/session/sign-out")
def sign_out_route(
    response: Response,
    auth_tokens=Depends(get_optional_auth_tokens),
):
    access_token, refresh_token = auth_tokens
    try:
        result = sign_out_authenticated_session(
            access_token=access_token or "",
            refresh_token=refresh_token or "",
        )
        clear_auth_cookies(response)
        return result
    except AppError as error:
        # Always clear cookies on sign-out attempts, even if upstream
        # revocation fails, we don't want stale cookies lingering on
        # the client.
        clear_auth_cookies(response)
        _raise_http_error(error)
