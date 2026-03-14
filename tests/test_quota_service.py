from src.auth_service import AuthService
from src.quota_service import QuotaService
from src.schemas import DailyQuotaStatus


class FakeUsageStore:
    def __init__(self, totals):
        self.totals = totals

    def get_daily_usage_totals(self, access_token, refresh_token, user_id):
        return dict(self.totals)


def test_quota_service_computes_remaining_daily_capacity_for_free_tier():
    auth_service = AuthService(
        supabase_url="https://project.supabase.co",
        supabase_anon_key="anon-key",
        redirect_url="http://localhost:8501",
    )
    quota_service = QuotaService(
        auth_service,
        FakeUsageStore(
            {
                "request_count": 3,
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 150,
                "window_start": "2026-03-14T00:00:00+00:00",
                "window_end": "2026-03-15T00:00:00+00:00",
            }
        ),
    )

    status = quota_service.get_daily_quota_status(
        "access-token",
        "refresh-token",
        "user-123",
        "free",
    )

    assert isinstance(status, DailyQuotaStatus)
    assert status.user_id == "user-123"
    assert status.plan_tier == "free"
    assert status.request_count == 3
    assert status.remaining_calls == status.max_calls - 3
    assert status.remaining_total_tokens == status.max_total_tokens - 150
    assert status.quota_exhausted is False


def test_quota_service_marks_quota_exhausted_when_daily_limit_is_reached():
    auth_service = AuthService(
        supabase_url="https://project.supabase.co",
        supabase_anon_key="anon-key",
        redirect_url="http://localhost:8501",
    )
    quota_service = QuotaService(
        auth_service,
        FakeUsageStore(
            {
                "request_count": 12,
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "total_tokens": 60000,
                "window_start": "2026-03-14T00:00:00+00:00",
                "window_end": "2026-03-15T00:00:00+00:00",
            }
        ),
    )

    status = quota_service.get_daily_quota_status(
        "access-token",
        "refresh-token",
        "user-123",
        "free",
    )

    assert status.quota_exhausted is True
    assert status.remaining_calls == 0
    assert status.remaining_total_tokens == 0