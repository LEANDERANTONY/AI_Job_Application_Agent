from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from src.auth_service import AuthService
from src.config import SAVED_WORKSPACE_TTL_HOURS, SUPABASE_SAVED_WORKSPACES_TABLE
from src.errors import AppError
from src.schemas import SavedWorkspaceRecord


class SavedWorkspaceStore:
    def __init__(
        self,
        auth_service: AuthService,
        table_name: str = SUPABASE_SAVED_WORKSPACES_TABLE,
        ttl_hours: int = SAVED_WORKSPACE_TTL_HOURS,
    ):
        self.auth_service = auth_service
        self.table_name = table_name
        self.ttl_hours = ttl_hours

    def is_configured(self):
        return self.auth_service.is_configured() and bool(self.table_name)

    def save_workspace(self, access_token: str, refresh_token: str, payload: dict):
        client = self._client(access_token, refresh_token)
        updated_at = datetime.now(timezone.utc)
        expires_at = updated_at + timedelta(hours=max(int(self.ttl_hours or 24), 1))
        user_id = str(payload.get("user_id", "") or "")
        if not user_id:
            raise AppError("Saved workspace persistence requires an authenticated user id.")
        self._purge_expired_workspace(client, user_id, updated_at)
        normalized = {
            "user_id": user_id,
            "job_title": str(payload.get("job_title", "") or ""),
            "workflow_signature": str(payload.get("workflow_signature", "") or ""),
            "workflow_snapshot_json": str(payload.get("workflow_snapshot_json", "") or ""),
            "report_payload_json": str(payload.get("report_payload_json", "") or ""),
            "cover_letter_payload_json": str(payload.get("cover_letter_payload_json", "") or ""),
            "tailored_resume_payload_json": str(payload.get("tailored_resume_payload_json", "") or ""),
            "updated_at": str(payload.get("updated_at") or updated_at.isoformat()),
            "expires_at": str(payload.get("expires_at") or expires_at.isoformat()),
        }
        try:
            response = (
                client.table(self.table_name)
                .upsert(normalized, on_conflict="user_id")
                .execute()
            )
        except Exception as exc:
            raise AppError(
                "The app could not save your latest workspace.",
                details=str(exc),
            ) from exc
        rows = self._extract_rows(response)
        if not rows:
            return SavedWorkspaceRecord(**normalized)
        return self._to_record(rows[0], fallback=normalized)

    def load_workspace(self, access_token: str, refresh_token: str, user_id: str, now: Optional[datetime] = None):
        client = self._client(access_token, refresh_token)
        current_time = now or datetime.now(timezone.utc)
        self._purge_expired_workspace(client, user_id, current_time)
        try:
            response = (
                client.table(self.table_name)
                .select(
                    "user_id,job_title,workflow_signature,workflow_snapshot_json,report_payload_json,cover_letter_payload_json,tailored_resume_payload_json,expires_at,updated_at"
                )
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
        except Exception as exc:
            raise AppError(
                "The app could not load your saved workspace.",
                details=str(exc),
            ) from exc
        rows = self._extract_rows(response)
        if not rows:
            return None, "missing"

        record = self._to_record(rows[0])
        if self._is_expired(record.expires_at, current_time):
            self.delete_workspace(access_token, refresh_token, user_id)
            return None, "expired"
        return record, "available"

    def delete_workspace(self, access_token: str, refresh_token: str, user_id: str):
        client = self._client(access_token, refresh_token)
        try:
            (
                client.table(self.table_name)
                .delete()
                .eq("user_id", user_id)
                .execute()
            )
        except Exception as exc:
            raise AppError(
                "The app could not remove your expired saved workspace.",
                details=str(exc),
            ) from exc

    def _client(self, access_token: str, refresh_token: str):
        if not self.is_configured():
            raise AppError("Saved workspace persistence is not configured.")
        return self.auth_service.create_authenticated_client(access_token, refresh_token)

    def _purge_expired_workspace(self, client: Any, user_id: str, current_time: datetime):
        if not user_id:
            return
        try:
            (
                client.table(self.table_name)
                .delete()
                .eq("user_id", user_id)
                .lte("expires_at", current_time.astimezone(timezone.utc).isoformat())
                .execute()
            )
        except Exception:
            return

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
    def _to_record(payload: dict, fallback: Optional[dict] = None):
        fallback = fallback or {}
        return SavedWorkspaceRecord(
            user_id=str(payload.get("user_id", fallback.get("user_id", "")) or ""),
            job_title=str(payload.get("job_title", fallback.get("job_title", "")) or ""),
            workflow_signature=str(payload.get("workflow_signature", fallback.get("workflow_signature", "")) or ""),
            workflow_snapshot_json=str(payload.get("workflow_snapshot_json", fallback.get("workflow_snapshot_json", "")) or ""),
            report_payload_json=str(payload.get("report_payload_json", fallback.get("report_payload_json", "")) or ""),
            cover_letter_payload_json=str(payload.get("cover_letter_payload_json", fallback.get("cover_letter_payload_json", "")) or ""),
            tailored_resume_payload_json=str(payload.get("tailored_resume_payload_json", fallback.get("tailored_resume_payload_json", "")) or ""),
            expires_at=str(payload.get("expires_at", fallback.get("expires_at", "")) or ""),
            updated_at=str(payload.get("updated_at", fallback.get("updated_at", "")) or ""),
        )

    @staticmethod
    def _is_expired(expires_at: str, current_time: datetime):
        if not expires_at:
            return True
        try:
            normalized = expires_at.replace("Z", "+00:00")
            expires_at_dt = datetime.fromisoformat(normalized)
        except ValueError:
            return True
        if expires_at_dt.tzinfo is None:
            expires_at_dt = expires_at_dt.replace(tzinfo=timezone.utc)
        return expires_at_dt <= current_time.astimezone(timezone.utc)