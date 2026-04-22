from fastapi import APIRouter, Depends, HTTPException

from backend.auth_models import (
    GoogleSignInExchangeRequestModel,
    GoogleSignInStartRequestModel,
)
from backend.request_auth import get_optional_auth_tokens
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


@router.post("/google/start")
def start_google_sign_in_route(payload: GoogleSignInStartRequestModel):
    try:
        return start_google_sign_in(redirect_url=payload.redirect_url)
    except AppError as error:
        _raise_http_error(error)


@router.post("/google/exchange")
def exchange_google_code_route(payload: GoogleSignInExchangeRequestModel):
    try:
        return exchange_google_code(
            auth_code=payload.auth_code,
            auth_flow=payload.auth_flow,
            redirect_url=payload.redirect_url,
        )
    except AppError as error:
        _raise_http_error(error)


@router.post("/session/restore")
def restore_session_route(auth_tokens=Depends(get_optional_auth_tokens)):
    access_token, refresh_token = auth_tokens
    try:
        return restore_authenticated_session(
            access_token=access_token or "",
            refresh_token=refresh_token or "",
        )
    except AppError as error:
        _raise_http_error(error)


@router.post("/session/sign-out")
def sign_out_route(auth_tokens=Depends(get_optional_auth_tokens)):
    access_token, refresh_token = auth_tokens
    try:
        return sign_out_authenticated_session(
            access_token=access_token or "",
            refresh_token=refresh_token or "",
        )
    except AppError as error:
        _raise_http_error(error)
