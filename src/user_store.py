from datetime import datetime, timezone
from typing import Any

from src.auth_service import AuthService, AuthSession
from src.config import (
    AUTH_DEFAULT_ACCOUNT_STATUS,
    AUTH_DEFAULT_PLAN_TIER,
    SUPABASE_APP_USERS_TABLE,
)
from src.errors import AppError
from src.schemas import AppUserRecord


class AppUserStore:
    def __init__(
        self,
        auth_service: AuthService,
        table_name: str = SUPABASE_APP_USERS_TABLE,
        default_plan_tier: str = AUTH_DEFAULT_PLAN_TIER,
        default_account_status: str = AUTH_DEFAULT_ACCOUNT_STATUS,
    ):
        self.auth_service = auth_service
        self.table_name = table_name
        self.default_plan_tier = default_plan_tier
        self.default_account_status = default_account_status

    def is_configured(self):
        return self.auth_service.is_configured() and bool(self.table_name)

    def sync_user_record(self, auth_session: AuthSession):
        if not self.is_configured():
            raise AppError("Persistent user sync is not configured.")

        client = self.auth_service.create_authenticated_client(
            auth_session.access_token,
            auth_session.refresh_token,
        )
        timestamp = datetime.now(timezone.utc).isoformat()
        payload = {
            "id": auth_session.user.user_id,
            "email": auth_session.user.email or "",
            "display_name": auth_session.user.display_name or "",
            "avatar_url": auth_session.user.avatar_url or "",
            "last_seen_at": timestamp,
            "plan_tier": self.default_plan_tier,
            "account_status": self.default_account_status,
        }

        try:
            response = (
                client.table(self.table_name)
                .upsert(payload, on_conflict="id")
                .execute()
            )
        except Exception as exc:
            raise AppError(
                "Google sign-in worked, but the app could not sync your account record.",
                details=str(exc),
            ) from exc

        rows = self._extract_rows(response)
        if not rows:
            return AppUserRecord(
                id=auth_session.user.user_id,
                email=auth_session.user.email or "",
                display_name=auth_session.user.display_name or "",
                avatar_url=auth_session.user.avatar_url or "",
                created_at="",
                last_seen_at=timestamp,
                plan_tier=self.default_plan_tier,
                account_status=self.default_account_status,
            )
        return self._to_record(rows[0])

    @staticmethod
    def _extract_rows(response: Any):
        if response is None:
            return []
        if isinstance(response, list):
            return response
        if isinstance(response, dict):
            return response.get("data") or []
        return getattr(response, "data", None) or []

    @staticmethod
    def _to_record(payload: dict):
        return AppUserRecord(
            id=str(payload.get("id", "")),
            email=str(payload.get("email", "") or ""),
            display_name=str(payload.get("display_name", "") or ""),
            avatar_url=str(payload.get("avatar_url", "") or ""),
            created_at=str(payload.get("created_at", "") or ""),
            last_seen_at=str(payload.get("last_seen_at", "") or ""),
            plan_tier=str(payload.get("plan_tier", AUTH_DEFAULT_PLAN_TIER) or AUTH_DEFAULT_PLAN_TIER),
            account_status=str(payload.get("account_status", AUTH_DEFAULT_ACCOUNT_STATUS) or AUTH_DEFAULT_ACCOUNT_STATUS),
        )