from src.auth_service import AuthService
from src.config import (
    FREE_TIER_MAX_CALLS_PER_DAY,
    PAID_TIER_MAX_CALLS_PER_DAY,
    get_daily_quota_for_plan,
)
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


def test_business_tier_gets_paid_daily_caps_not_free():
    """Regression: `get_daily_quota_for_plan` used to lack a "business"
    branch — Business users fell through to the FREE caps (12 calls /
    60k tokens per day), silently throttling paying customers on the
    daily cost-limiter even though the monthly TIER_CAPS table grants
    them generous feature quotas. They should share the Pro daily cap.
    """
    business = get_daily_quota_for_plan("business")
    pro = get_daily_quota_for_plan("pro")
    free = get_daily_quota_for_plan("free")

    assert business["max_calls"] == PAID_TIER_MAX_CALLS_PER_DAY
    assert business["max_calls"] == pro["max_calls"]
    assert business["max_calls"] != free["max_calls"]
    assert business["max_total_tokens"] == pro["max_total_tokens"]
    # plan_tier is echoed lowercase so the downstream label is honest
    # about which tier the user is on.
    assert business["plan_tier"] == "business"


def test_internal_tier_remains_unlimited():
    """Internal / admin emails get no daily cap (None == unlimited).
    The plan_tier label flows through so the UI can render
    "Unlimited (Internal)" when the dev account is signed in."""
    internal = get_daily_quota_for_plan("internal")
    admin = get_daily_quota_for_plan("admin")

    assert internal["max_calls"] is None
    assert internal["max_total_tokens"] is None
    assert internal["plan_tier"] == "internal"
    assert admin["max_calls"] is None
    assert admin["plan_tier"] == "admin"


def test_unknown_tier_falls_back_to_free():
    """Defensive fallback: an unrecognised plan_tier (typo, future
    tier we haven't shipped yet) should resolve to the FREE caps
    rather than crashing or returning unlimited."""
    unknown = get_daily_quota_for_plan("enterprise_xl")
    assert unknown["max_calls"] == FREE_TIER_MAX_CALLS_PER_DAY