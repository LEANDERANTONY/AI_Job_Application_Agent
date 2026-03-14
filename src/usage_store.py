from datetime import datetime, timedelta, timezone

from src.auth_service import AuthService
from src.config import SUPABASE_USAGE_EVENTS_TABLE
from src.errors import AppError
from src.schemas import UsageEventRecord


class UsageStore:
    def __init__(
        self,
        auth_service: AuthService,
        table_name: str = SUPABASE_USAGE_EVENTS_TABLE,
    ):
        self.auth_service = auth_service
        self.table_name = table_name

    def is_configured(self):
        return self.auth_service.is_configured() and bool(self.table_name)

    def record_usage_event(self, access_token: str, refresh_token: str, event_payload: dict):
        if not self.is_configured():
            raise AppError("Usage persistence is not configured.")

        client = self.auth_service.create_authenticated_client(access_token, refresh_token)
        payload = {
            "user_id": str(event_payload.get("user_id", "") or ""),
            "task_name": str(event_payload.get("task_name", "") or ""),
            "model_name": str(event_payload.get("model_name", "") or ""),
            "request_count": int(event_payload.get("request_count", 0) or 0),
            "prompt_tokens": int(event_payload.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(event_payload.get("completion_tokens", 0) or 0),
            "total_tokens": int(event_payload.get("total_tokens", 0) or 0),
            "response_id": str(event_payload.get("response_id", "") or ""),
            "status": str(event_payload.get("status", "") or ""),
            "created_at": str(
                event_payload.get("created_at")
                or datetime.now(timezone.utc).isoformat()
            ),
        }
        if not payload["user_id"]:
            raise AppError("Usage persistence requires an authenticated user id.")

        try:
            response = client.table(self.table_name).insert(payload).execute()
        except Exception as exc:
            raise AppError(
                "The app could not persist the usage event.",
                details=str(exc),
            ) from exc

        rows = getattr(response, "data", None) or []
        if not rows:
            return UsageEventRecord(**payload)
        row = rows[0]
        return UsageEventRecord(
            user_id=str(row.get("user_id", payload["user_id"])),
            task_name=str(row.get("task_name", payload["task_name"])),
            model_name=str(row.get("model_name", payload["model_name"])),
            request_count=int(row.get("request_count", payload["request_count"])),
            prompt_tokens=int(row.get("prompt_tokens", payload["prompt_tokens"])),
            completion_tokens=int(row.get("completion_tokens", payload["completion_tokens"])),
            total_tokens=int(row.get("total_tokens", payload["total_tokens"])),
            response_id=str(row.get("response_id", payload["response_id"])),
            status=str(row.get("status", payload["status"])),
            created_at=str(row.get("created_at", payload["created_at"])),
        )

    def get_daily_usage_totals(self, access_token: str, refresh_token: str, user_id: str):
        if not self.is_configured():
            raise AppError("Usage persistence is not configured.")
        if not user_id:
            raise AppError("Usage aggregation requires an authenticated user id.")

        client = self.auth_service.create_authenticated_client(access_token, refresh_token)
        window_start = datetime.now(timezone.utc).replace(
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
        window_end = window_start + timedelta(days=1)

        try:
            response = (
                client.table(self.table_name)
                .select("request_count,prompt_tokens,completion_tokens,total_tokens,created_at")
                .eq("user_id", user_id)
                .gte("created_at", window_start.isoformat())
                .lt("created_at", window_end.isoformat())
                .execute()
            )
        except Exception as exc:
            raise AppError(
                "The app could not read daily usage totals.",
                details=str(exc),
            ) from exc

        rows = getattr(response, "data", None) or []
        totals = {
            "request_count": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
        }
        for row in rows:
            totals["request_count"] += int(row.get("request_count", 0) or 0)
            totals["prompt_tokens"] += int(row.get("prompt_tokens", 0) or 0)
            totals["completion_tokens"] += int(row.get("completion_tokens", 0) or 0)
            totals["total_tokens"] += int(row.get("total_tokens", 0) or 0)
        return totals