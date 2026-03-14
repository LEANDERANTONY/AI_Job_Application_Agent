from datetime import datetime, timedelta, timezone

from src.auth_service import AuthService
from src.config import get_daily_quota_for_plan
from src.errors import AppError
from src.schemas import DailyQuotaStatus


class QuotaService:
    def __init__(self, auth_service: AuthService, usage_store):
        self.auth_service = auth_service
        self.usage_store = usage_store

    def get_daily_quota_status(
        self,
        access_token: str,
        refresh_token: str,
        user_id: str,
        plan_tier: str,
    ):
        if not user_id:
            raise AppError("Daily quota checks require an authenticated user id.")

        quota = get_daily_quota_for_plan(plan_tier)
        if quota["max_calls"] is None and quota["max_total_tokens"] is None:
            now = datetime.now(timezone.utc)
            return DailyQuotaStatus(
                user_id=user_id,
                plan_tier=quota["plan_tier"],
                max_calls=None,
                max_total_tokens=None,
                remaining_calls=None,
                remaining_total_tokens=None,
                quota_exhausted=False,
                window_start=now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(),
                window_end=(now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).isoformat(),
            )

        totals = self.usage_store.get_daily_usage_totals(
            access_token,
            refresh_token,
            user_id,
        )
        max_calls = quota["max_calls"]
        max_total_tokens = quota["max_total_tokens"]
        remaining_calls = None if max_calls is None else max(max_calls - totals["request_count"], 0)
        remaining_total_tokens = None if max_total_tokens is None else max(
            max_total_tokens - totals["total_tokens"], 0
        )
        quota_exhausted = (
            (remaining_calls is not None and remaining_calls == 0)
            or (remaining_total_tokens is not None and remaining_total_tokens == 0)
        )
        return DailyQuotaStatus(
            user_id=user_id,
            plan_tier=quota["plan_tier"],
            request_count=totals["request_count"],
            prompt_tokens=totals["prompt_tokens"],
            completion_tokens=totals["completion_tokens"],
            total_tokens=totals["total_tokens"],
            max_calls=max_calls,
            max_total_tokens=max_total_tokens,
            remaining_calls=remaining_calls,
            remaining_total_tokens=remaining_total_tokens,
            quota_exhausted=quota_exhausted,
            window_start=totals["window_start"],
            window_end=totals["window_end"],
        )