from datetime import datetime, timedelta, timezone
from typing import Any

from src.auth_service import AuthService
from src.config import (
    RESUME_BUILDER_SESSION_TTL_DAYS,
    SUPABASE_RESUME_BUILDER_SESSIONS_TABLE,
)
from src.errors import AppError
from src.schemas import ResumeBuilderSessionRecord


class ResumeBuilderStore:
    def __init__(
        self,
        auth_service: AuthService,
        table_name: str = SUPABASE_RESUME_BUILDER_SESSIONS_TABLE,
    ):
        self.auth_service = auth_service
        self.table_name = table_name

    def is_configured(self):
        return self.auth_service.is_configured() and bool(self.table_name)

    def save_session(self, access_token: str, refresh_token: str, payload: dict):
        if not self.is_configured():
            raise AppError("Resume builder persistence is not configured.")

        client = self.auth_service.create_authenticated_client(access_token, refresh_token)
        now_utc = datetime.now(timezone.utc)
        timestamp = now_utc.isoformat()
        # Refresh the TTL on every save: a user actively editing keeps
        # the draft alive past the original 7-day default that fires
        # on row creation. Inactive drafts age out via the cron once
        # `expires_at <= now()`.
        expires_at = (
            now_utc + timedelta(days=RESUME_BUILDER_SESSION_TTL_DAYS)
        ).isoformat()
        normalized = self._normalize_payload(
            payload,
            timestamp=timestamp,
            expires_at=expires_at,
        )
        if not normalized["user_id"]:
            raise AppError("Saving a resume-builder draft requires an authenticated user id.")
        if not normalized["session_id"]:
            raise AppError("Saving a resume-builder draft requires a stable session id.")

        try:
            response = (
                client.table(self.table_name)
                .upsert(normalized, on_conflict="user_id")
                .execute()
            )
        except Exception as exc:
            raise AppError(
                "The app could not save your resume-builder draft.",
                details=str(exc),
            ) from exc

        rows = self._extract_rows(response)
        if not rows:
            return self._to_record(normalized)
        return self._to_record(rows[0], fallback=normalized)

    def load_latest_session(self, access_token: str, refresh_token: str, user_id: str):
        if not self.is_configured():
            raise AppError("Resume builder persistence is not configured.")
        if not user_id:
            raise AppError("Loading a resume-builder draft requires an authenticated user id.")

        client = self.auth_service.create_authenticated_client(access_token, refresh_token)
        try:
            response = (
                client.table(self.table_name)
                .select(
                    "user_id,session_id,status,current_step,"
                    "session_payload_json,updated_at,expires_at"
                )
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
        except Exception as exc:
            raise AppError(
                "The app could not load your resume-builder draft.",
                details=str(exc),
            ) from exc

        rows = self._extract_rows(response)
        if not rows:
            return None
        return self._to_record(rows[0])

    def delete_session(self, access_token: str, refresh_token: str, user_id: str):
        if not self.is_configured():
            raise AppError("Resume builder persistence is not configured.")
        if not user_id:
            raise AppError("Removing a resume-builder draft requires an authenticated user id.")

        client = self.auth_service.create_authenticated_client(access_token, refresh_token)
        try:
            (
                client.table(self.table_name)
                .delete()
                .eq("user_id", user_id)
                .execute()
            )
        except Exception as exc:
            raise AppError(
                "The app could not clear your resume-builder draft.",
                details=str(exc),
            ) from exc

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
    def _normalize_payload(payload: dict, *, timestamp: str, expires_at: str):
        return {
            "user_id": str(payload.get("user_id", "") or ""),
            "session_id": str(payload.get("session_id", "") or ""),
            "status": str(payload.get("status", "") or ""),
            "current_step": str(payload.get("current_step", "") or ""),
            "session_payload_json": str(payload.get("session_payload_json", "") or ""),
            "updated_at": str(payload.get("updated_at") or timestamp),
            "expires_at": str(payload.get("expires_at") or expires_at),
        }

    @staticmethod
    def _to_record(payload: dict, fallback: dict | None = None):
        fallback = fallback or {}
        return ResumeBuilderSessionRecord(
            user_id=str(payload.get("user_id", fallback.get("user_id", "")) or ""),
            session_id=str(payload.get("session_id", fallback.get("session_id", "")) or ""),
            status=str(payload.get("status", fallback.get("status", "")) or ""),
            current_step=str(payload.get("current_step", fallback.get("current_step", "")) or ""),
            session_payload_json=str(
                payload.get("session_payload_json", fallback.get("session_payload_json", "")) or ""
            ),
            updated_at=str(payload.get("updated_at", fallback.get("updated_at", "")) or ""),
            expires_at=str(payload.get("expires_at", fallback.get("expires_at", "")) or ""),
        )
