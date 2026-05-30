"""The daily-quota tier comes from resolve_user_tier, not plan_tier (M1).

``app_users.plan_tier`` is writable by the user's own JWT via the RLS UPDATE
policy, so the legacy daily-quota path trusting it let a self-promoted
``plan_tier='business'`` raise the daily allowance. The fix sources the tier
from ``resolve_user_tier`` (the subscriptions-backed shim every other gate
uses) instead. (The column itself is now also guarded by a DB trigger — see
docs/sql/supabase-bootstrap.sql — which is exercised against real Postgres,
not this unit suite.)
"""

from __future__ import annotations

from types import SimpleNamespace

from backend.services import auth_session_service as svc
from src.schemas import AppUserRecord


def test_load_daily_quota_uses_resolved_tier_not_app_user_plan_tier(monkeypatch):
    captured: dict = {}

    # Let _load_daily_quota proceed past the configuration guard.
    monkeypatch.setattr(svc.UsageStore, "is_configured", lambda self: True)
    # The authoritative tier (subscriptions) resolves to free despite the
    # self-promoted app_user.plan_tier.
    monkeypatch.setattr(svc, "resolve_user_tier", lambda app_user: "free")

    def _capture(self, access_token, refresh_token, user_id, plan_tier):
        captured["plan_tier"] = plan_tier
        captured["user_id"] = user_id
        return {"ok": True}

    monkeypatch.setattr(svc.QuotaService, "get_daily_quota_status", _capture)

    app_user = AppUserRecord(
        id="u1",
        email="",
        display_name="",
        avatar_url="",
        created_at="",
        last_seen_at="",
        plan_tier="business",  # self-promoted — must be ignored
        account_status="active",
    )

    result = svc._load_daily_quota(
        auth_service=SimpleNamespace(),
        access_token="a",
        refresh_token="r",
        app_user=app_user,
    )

    assert result == {"ok": True}
    # The resolved tier (free), NOT the self-promoted plan_tier (business).
    assert captured["plan_tier"] == "free"
    assert captured["user_id"] == "u1"
