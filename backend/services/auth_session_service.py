from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from typing import Any

from backend.config import get_backend_settings
from src.auth_service import AuthService, AuthSession
from src.config import (
    AUTH_DEFAULT_ACCOUNT_STATUS,
    assisted_workflow_requires_login,
    get_default_plan_tier_for_email,
)
from src.errors import AgentExecutionError, AppError, InputValidationError
from src.openai_service import OpenAIService
from src.quota_service import QuotaService
from src.saved_jobs_store import SavedJobsStore
from src.saved_workspace_store import SavedWorkspaceStore
from src.schemas import AppUserRecord
from src.usage_store import UsageStore
from src.user_store import AppUserStore


@dataclass
class AuthenticatedContext:
    auth_service: AuthService
    auth_session: AuthSession
    app_user: AppUserRecord
    daily_quota: Any | None = None


class BackendPkceStorage:
    def __init__(self):
        self._code_verifier: str | None = None

    def get_item(self, key: str):
        if key.endswith("-code-verifier"):
            return self._code_verifier
        return None

    def set_item(self, key: str, value: str):
        if key.endswith("-code-verifier"):
            self._code_verifier = str(value or "").strip() or None

    def remove_item(self, key: str):
        if key.endswith("-code-verifier"):
            self._code_verifier = None


def _serialize(value: Any):
    if is_dataclass(value):
        return {key: _serialize(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


def resolve_auth_redirect_url(explicit_redirect_url: str = ""):
    normalized = str(explicit_redirect_url or "").strip()
    if normalized:
        return normalized
    settings = get_backend_settings()
    return f"{settings.frontend_app_url.rstrip('/')}/workspace"


def _build_fallback_app_user_record(auth_session: AuthSession):
    return AppUserRecord(
        id=auth_session.user.user_id,
        email=auth_session.user.email or "",
        display_name=auth_session.user.display_name or "",
        avatar_url=auth_session.user.avatar_url or "",
        created_at="",
        last_seen_at="",
        plan_tier=get_default_plan_tier_for_email(auth_session.user.email),
        account_status=AUTH_DEFAULT_ACCOUNT_STATUS,
    )


def _sync_or_build_app_user_record(auth_service: AuthService, auth_session: AuthSession):
    user_store = AppUserStore(auth_service)
    if user_store.is_configured():
        return user_store.sync_user_record(auth_session)
    return _build_fallback_app_user_record(auth_session)


def _load_daily_quota(
    auth_service: AuthService,
    access_token: str,
    refresh_token: str,
    app_user: AppUserRecord,
):
    usage_store = UsageStore(auth_service)
    if not usage_store.is_configured():
        return None
    quota_service = QuotaService(auth_service, usage_store)
    return quota_service.get_daily_quota_status(
        access_token,
        refresh_token,
        app_user.id,
        app_user.plan_tier,
    )


def _build_authenticated_payload(context: AuthenticatedContext):
    usage_store = UsageStore(context.auth_service)
    saved_workspace_store = SavedWorkspaceStore(context.auth_service)
    saved_jobs_store = SavedJobsStore(context.auth_service)
    return {
        "authenticated": True,
        "session": {
            "access_token": context.auth_session.access_token,
            "refresh_token": context.auth_session.refresh_token,
        },
        "user": _serialize(context.auth_session.user),
        "app_user": _serialize(context.app_user),
        "daily_quota": _serialize(context.daily_quota) if context.daily_quota else None,
        "features": {
            "saved_workspace_enabled": saved_workspace_store.is_configured(),
            "saved_jobs_enabled": saved_jobs_store.is_configured(),
            "usage_tracking_enabled": usage_store.is_configured(),
            "assisted_workflow_requires_login": assisted_workflow_requires_login(),
        },
    }


def start_google_sign_in(*, redirect_url: str):
    storage = BackendPkceStorage()
    auth_service = AuthService(
        redirect_url=resolve_auth_redirect_url(redirect_url),
        storage=storage,
    )
    request = auth_service.get_google_sign_in_request()
    return {
        "url": request.url,
        "auth_flow": request.auth_flow,
        "redirect_url": auth_service.redirect_url,
    }


def exchange_google_code(*, auth_code: str, auth_flow: str = "", redirect_url: str = ""):
    auth_service = AuthService(redirect_url=resolve_auth_redirect_url(redirect_url))
    auth_session = auth_service.exchange_code_for_session(
        auth_code,
        auth_flow=auth_flow or None,
    )
    app_user = _sync_or_build_app_user_record(auth_service, auth_session)
    daily_quota = _load_daily_quota(
        auth_service,
        auth_session.access_token,
        auth_session.refresh_token,
        app_user,
    )
    return _build_authenticated_payload(
        AuthenticatedContext(
            auth_service=auth_service,
            auth_session=auth_session,
            app_user=app_user,
            daily_quota=daily_quota,
        )
    )


def restore_authenticated_session(*, access_token: str, refresh_token: str):
    context = resolve_authenticated_context(
        access_token=access_token,
        refresh_token=refresh_token,
    )
    return _build_authenticated_payload(context)


def sign_out_authenticated_session(*, access_token: str, refresh_token: str):
    auth_service = AuthService()
    auth_service.sign_out(access_token, refresh_token)
    return {"authenticated": False, "status": "signed_out"}


def resolve_authenticated_context(*, access_token: str, refresh_token: str):
    normalized_access = str(access_token or "").strip()
    normalized_refresh = str(refresh_token or "").strip()
    if not normalized_access or not normalized_refresh:
        raise InputValidationError("Sign in with Google before using this feature.")

    auth_service = AuthService()
    auth_session = auth_service.restore_session(normalized_access, normalized_refresh)
    app_user = _sync_or_build_app_user_record(auth_service, auth_session)
    daily_quota = _load_daily_quota(
        auth_service,
        normalized_access,
        normalized_refresh,
        app_user,
    )
    return AuthenticatedContext(
        auth_service=auth_service,
        auth_session=auth_session,
        app_user=app_user,
        daily_quota=daily_quota,
    )


def build_openai_service_for_context(context: AuthenticatedContext):
    usage_store = UsageStore(context.auth_service)
    if not usage_store.is_configured():
        return OpenAIService(), context.daily_quota

    quota_service = QuotaService(context.auth_service, usage_store)
    daily_quota = context.daily_quota or quota_service.get_daily_quota_status(
        context.auth_session.access_token,
        context.auth_session.refresh_token,
        context.app_user.id,
        context.app_user.plan_tier,
    )

    if daily_quota and daily_quota.quota_exhausted:

        def quota_checker():
            raise AgentExecutionError(
                "Your daily assisted usage limit has been reached. Try again tomorrow or upgrade your plan tier."
            )

    else:

        def quota_checker():
            refreshed_quota = quota_service.get_daily_quota_status(
                context.auth_session.access_token,
                context.auth_session.refresh_token,
                context.app_user.id,
                context.app_user.plan_tier,
            )
            if refreshed_quota and refreshed_quota.quota_exhausted:
                raise AgentExecutionError(
                    "Your daily assisted usage limit has been reached. Try again tomorrow or upgrade your plan tier."
                )

    def usage_event_recorder(event_payload: dict):
        usage_store.record_usage_event(
            context.auth_session.access_token,
            context.auth_session.refresh_token,
            {
                **dict(event_payload or {}),
                "user_id": context.app_user.id,
            },
        )

    return (
        OpenAIService(
            usage_event_recorder=usage_event_recorder,
            quota_checker=quota_checker,
        ),
        daily_quota,
    )
