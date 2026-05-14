"""Lemon Squeezy webhook signature verification + event routing.

Three layers of coverage:

  * Signature verification: known secret + body produces a stable
    HMAC; mismatched signatures raise InvalidWebhookSignature; an
    unset secret raises WebhookConfigError (the route's 503 branch).

  * Event-to-state mapping: every event in _EVENT_TO_STATUS produces
    the right (status, cancel_at_period_end) tuple on the
    subscriptions row.

  * Edge cases: missing custom_data.user_id, unknown variant_id,
    unparseable body, and idempotency under duplicate delivery.

The TestClient integration tests exercise the FastAPI route end-to-
end: 401 on bad signature, 503 on missing secret, 200 on every
signature-valid call.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from backend import subscriptions
from backend.app import app
from backend.subscriptions import (
    get_active_subscription,
    invalidate_subscription_cache,
    reset_in_memory_backend,
)
from backend.webhooks.lemonsqueezy import (
    InvalidWebhookSignature,
    WebhookConfigError,
    process_webhook,
    verify_signature,
)


_WEBHOOK_SECRET = "test_webhook_secret_value"
_PRO_VARIANT = "1001"
_BUSINESS_VARIANT = "1002"
_USER_ID = "00000000-0000-4000-8000-000000000001"


@pytest.fixture(autouse=True)
def _isolated_env_and_store(monkeypatch):
    """Configure env vars + reset the subscriptions backend before
    each test. Mirrors the autouse fixtures in test_quota.py /
    test_subscriptions.py."""
    monkeypatch.setenv(
        "AIJOBAGENT_LEMONSQUEEZY_WEBHOOK_SECRET", _WEBHOOK_SECRET
    )
    monkeypatch.setenv(
        "AIJOBAGENT_LEMONSQUEEZY_PRODUCT_VARIANT_PRO", _PRO_VARIANT
    )
    monkeypatch.setenv(
        "AIJOBAGENT_LEMONSQUEEZY_PRODUCT_VARIANT_BUSINESS", _BUSINESS_VARIANT
    )

    monkeypatch.setattr(
        subscriptions, "_SUPABASE_BACKEND", _NeverConfiguredBackend()
    )
    invalidate_subscription_cache()
    reset_in_memory_backend()
    yield
    invalidate_subscription_cache()
    reset_in_memory_backend()


class _NeverConfiguredBackend:
    def is_configured(self) -> bool:
        return False


def _sign(body: bytes, secret: str = _WEBHOOK_SECRET) -> str:
    return hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()


def _build_payload(
    *,
    event_name: str,
    user_id: str = _USER_ID,
    variant_id: str = _PRO_VARIANT,
    subscription_id: str = "sub-12345",
    customer_id: str = "cust-67890",
    status: str = "active",
    renews_at: str = "2026-06-14T19:14:21.000000Z",
    ends_at: str | None = None,
    cancelled: bool = False,
    webhook_id: str = "evt-aaa",
) -> dict:
    return {
        "meta": {
            "event_name": event_name,
            "webhook_id": webhook_id,
            "custom_data": {"user_id": user_id} if user_id else {},
        },
        "data": {
            "id": subscription_id,
            "type": "subscriptions",
            "attributes": {
                "status": status,
                "variant_id": variant_id,
                "customer_id": customer_id,
                "cancelled": cancelled,
                "renews_at": renews_at,
                "ends_at": ends_at,
            },
        },
    }


# ─── signature verification ─────────────────────────────────────────────


def test_valid_signature_passes():
    body = b'{"hello":"world"}'
    signature = _sign(body)
    # Should not raise.
    verify_signature(raw_body=body, signature=signature)


def test_signature_mismatch_raises():
    body = b'{"hello":"world"}'
    with pytest.raises(InvalidWebhookSignature):
        verify_signature(raw_body=body, signature="deadbeef" * 8)


def test_signature_against_modified_body_raises():
    """Signing one body and submitting another (e.g. an attacker
    swapping the user_id) must fail verification."""
    body_a = b'{"meta":{"event_name":"subscription_created"}}'
    body_b = b'{"meta":{"event_name":"subscription_cancelled"}}'
    signature_a = _sign(body_a)
    with pytest.raises(InvalidWebhookSignature):
        verify_signature(raw_body=body_b, signature=signature_a)


def test_missing_signature_header_raises():
    with pytest.raises(InvalidWebhookSignature):
        verify_signature(raw_body=b"{}", signature="")


def test_missing_secret_raises_config_error(monkeypatch):
    monkeypatch.setenv("AIJOBAGENT_LEMONSQUEEZY_WEBHOOK_SECRET", "")
    with pytest.raises(WebhookConfigError):
        verify_signature(raw_body=b"{}", signature="abc")


def test_uppercase_signature_accepted():
    """LS sends lowercase hex today, but the handler accepts
    uppercase defensively in case a future LS change capitalizes
    the output. Catches the regression where a strict casing
    comparison breaks every webhook delivery."""
    body = b'{"hello":"world"}'
    signature = _sign(body).upper()
    verify_signature(raw_body=body, signature=signature)


# ─── event -> state mapping ─────────────────────────────────────────────


def _process(payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    return process_webhook(raw_body=body, signature=_sign(body))


def test_subscription_created_writes_active_pro_row():
    result = _process(_build_payload(event_name="subscription_created"))
    assert result["status"] == "applied"
    sub = get_active_subscription(_USER_ID)
    assert sub is not None
    assert sub.tier == "pro"
    assert sub.status == "active"
    assert sub.cancel_at_period_end is False
    assert sub.processor_subscription_id == "sub-12345"


def test_subscription_created_with_business_variant_writes_business_tier():
    result = _process(
        _build_payload(
            event_name="subscription_created",
            variant_id=_BUSINESS_VARIANT,
        )
    )
    assert result["status"] == "applied"
    sub = get_active_subscription(_USER_ID)
    assert sub is not None
    assert sub.tier == "business"


def test_subscription_cancelled_sets_cancel_flag_and_status():
    """LS sends subscription_cancelled when the user clicks cancel.
    The data payload may still report status='active' on LS's side
    (because tier access continues until period end), but we store
    status='cancelled' so the resolver can branch on it."""
    _process(_build_payload(event_name="subscription_created"))
    result = _process(
        _build_payload(
            event_name="subscription_cancelled",
            status="active",  # LS keeps reporting 'active' here
            cancelled=True,
            ends_at="2026-07-14T19:14:21.000000Z",
            webhook_id="evt-bbb",
        )
    )
    assert result["status"] == "applied"
    sub = get_active_subscription(_USER_ID)
    assert sub is not None
    assert sub.status == "cancelled"
    assert sub.cancel_at_period_end is True


def test_subscription_resumed_clears_cancel_flag():
    _process(_build_payload(event_name="subscription_created"))
    _process(
        _build_payload(
            event_name="subscription_cancelled",
            cancelled=True,
            webhook_id="evt-bbb",
        )
    )
    result = _process(
        _build_payload(
            event_name="subscription_resumed",
            cancelled=False,
            webhook_id="evt-ccc",
        )
    )
    assert result["status"] == "applied"
    sub = get_active_subscription(_USER_ID)
    assert sub is not None
    assert sub.status == "active"
    assert sub.cancel_at_period_end is False


def test_subscription_expired_sets_expired_status():
    _process(_build_payload(event_name="subscription_created"))
    result = _process(
        _build_payload(
            event_name="subscription_expired",
            ends_at="2026-06-14T19:14:21.000000Z",
            webhook_id="evt-ddd",
        )
    )
    assert result["status"] == "applied"
    sub = get_active_subscription(_USER_ID)
    assert sub is not None
    assert sub.status == "expired"


def test_subscription_paused_sets_paused_status():
    _process(_build_payload(event_name="subscription_created"))
    result = _process(
        _build_payload(event_name="subscription_paused", webhook_id="evt-eee")
    )
    assert result["status"] == "applied"
    sub = get_active_subscription(_USER_ID)
    assert sub is not None
    assert sub.status == "paused"


def test_subscription_unpaused_sets_active_status():
    _process(_build_payload(event_name="subscription_paused"))
    result = _process(
        _build_payload(
            event_name="subscription_unpaused", webhook_id="evt-fff"
        )
    )
    assert result["status"] == "applied"
    sub = get_active_subscription(_USER_ID)
    assert sub is not None
    assert sub.status == "active"


def test_subscription_payment_success_keeps_active():
    """Renewal payment cleared. Refresh current_period_end from the
    new renews_at on the payload; status stays active."""
    _process(_build_payload(event_name="subscription_created"))
    result = _process(
        _build_payload(
            event_name="subscription_payment_success",
            renews_at="2026-08-14T19:14:21.000000Z",
            webhook_id="evt-ggg",
        )
    )
    assert result["status"] == "applied"
    sub = get_active_subscription(_USER_ID)
    assert sub is not None
    assert sub.status == "active"
    assert sub.current_period_end == datetime(
        2026, 8, 14, 19, 14, 21, tzinfo=timezone.utc
    )


def test_subscription_payment_failed_marks_past_due():
    _process(_build_payload(event_name="subscription_created"))
    result = _process(
        _build_payload(
            event_name="subscription_payment_failed", webhook_id="evt-hhh"
        )
    )
    assert result["status"] == "applied"
    sub = get_active_subscription(_USER_ID)
    assert sub is not None
    assert sub.status == "past_due"


def test_subscription_payment_recovered_returns_to_active():
    _process(_build_payload(event_name="subscription_payment_failed"))
    result = _process(
        _build_payload(
            event_name="subscription_payment_recovered", webhook_id="evt-iii"
        )
    )
    assert result["status"] == "applied"
    sub = get_active_subscription(_USER_ID)
    assert sub is not None
    assert sub.status == "active"


def test_subscription_updated_carries_payload_status():
    """`subscription_updated` is emitted for ANY field change. We
    mirror the payload's status field rather than forcing it back
    to 'active', so an updated event after a cancellation doesn't
    revert the cancelled state."""
    _process(_build_payload(event_name="subscription_created"))
    _process(
        _build_payload(
            event_name="subscription_cancelled",
            cancelled=True,
            webhook_id="evt-bbb",
        )
    )
    # Updated event arrives with status='cancelled' on the LS
    # payload (because the subscription IS cancelled). Our row must
    # carry that through, not flip back to "active".
    result = _process(
        _build_payload(
            event_name="subscription_updated",
            status="cancelled",
            cancelled=True,
            webhook_id="evt-ccc",
        )
    )
    assert result["status"] == "applied"
    sub = get_active_subscription(_USER_ID)
    assert sub is not None
    assert sub.status == "cancelled"
    assert sub.cancel_at_period_end is True


def test_subscription_updated_maps_unpaid_to_past_due():
    """LS legacy installations use 'unpaid' for the dunning state.
    Our handler aliases that to 'past_due' so the resolver branches
    correctly without a second case."""
    _process(_build_payload(event_name="subscription_created"))
    result = _process(
        _build_payload(
            event_name="subscription_updated",
            status="unpaid",
            webhook_id="evt-ddd",
        )
    )
    assert result["status"] == "applied"
    sub = get_active_subscription(_USER_ID)
    assert sub is not None
    assert sub.status == "past_due"


# ─── edge cases ─────────────────────────────────────────────────────────


def test_missing_user_id_skips_without_error():
    """A subscription created via the LS dashboard (no custom_data
    binding) has no user_id we can write to. The handler logs +
    returns status=skipped; LS gets a 200 so it doesn't retry."""
    result = _process(_build_payload(event_name="subscription_created", user_id=""))
    assert result["status"] == "skipped"


def test_unknown_variant_skips_without_writing():
    result = _process(
        _build_payload(
            event_name="subscription_created",
            variant_id="9999",  # not pro, not business
        )
    )
    assert result["status"] == "skipped"
    assert get_active_subscription(_USER_ID) is None


def test_unknown_event_name_ignored():
    """LS may add new event types (e.g. order_created) we don't
    map. Those return status=skipped without crashing or
    retrying."""
    result = _process(
        _build_payload(event_name="order_created")
    )
    assert result["status"] == "skipped"


def test_unparseable_body_returns_ignored():
    body = b"not-valid-json"
    result = process_webhook(raw_body=body, signature=_sign(body))
    assert result["status"] == "ignored"


def test_idempotency_under_duplicate_delivery():
    """LS retries on non-2xx + has at-least-once semantics, so the
    same delivery (same meta.webhook_id) can arrive multiple times.
    The second call must short-circuit at the idempotency log."""
    payload = _build_payload(event_name="subscription_created", webhook_id="dup-1")
    first = _process(payload)
    assert first["status"] == "applied"

    second = _process(payload)
    assert second["status"] == "duplicate"

    sub = get_active_subscription(_USER_ID)
    assert sub is not None


def test_idempotency_when_user_signs_up_twice_keeps_latest():
    """If a user somehow has two subscription_created events with
    DIFFERENT webhook_ids (manual LS-side action, edge case), the
    second event is treated as a normal update and the row is
    overwritten. Each delivery has its own idempotency slot."""
    _process(_build_payload(event_name="subscription_created", webhook_id="evt-aaa"))
    result = _process(
        _build_payload(
            event_name="subscription_created",
            variant_id=_BUSINESS_VARIANT,
            webhook_id="evt-bbb",
        )
    )
    assert result["status"] == "applied"
    sub = get_active_subscription(_USER_ID)
    assert sub is not None
    assert sub.tier == "business"


# ─── tier resolution end-to-end after webhook write ─────────────────────


def test_resolve_user_tier_picks_up_webhook_write():
    """After a subscription_created webhook, the next gate check
    (via resolve_user_tier) sees the new tier without waiting for
    the minute boundary. The handler calls
    invalidate_subscription_cache after every upsert; this test
    pins that behavior."""
    from backend.tiers import resolve_user_tier
    from src.schemas import AppUserRecord

    user = AppUserRecord(id=_USER_ID, email="x@y.z")
    assert resolve_user_tier(user) == "free"

    _process(_build_payload(event_name="subscription_created"))
    assert resolve_user_tier(user) == "pro"

    _process(
        _build_payload(
            event_name="subscription_expired",
            ends_at="2026-06-14T19:14:21.000000Z",
            webhook_id="evt-zzz",
        )
    )
    assert resolve_user_tier(user) == "free"


# ─── route-level integration ────────────────────────────────────────────


_client = TestClient(app)


def test_route_returns_200_on_valid_signature():
    body = json.dumps(_build_payload(event_name="subscription_created")).encode(
        "utf-8"
    )
    response = _client.post(
        "/api/webhooks/lemonsqueezy",
        content=body,
        headers={
            "X-Signature": _sign(body),
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "applied"


def test_route_returns_401_on_bad_signature():
    body = json.dumps(_build_payload(event_name="subscription_created")).encode(
        "utf-8"
    )
    response = _client.post(
        "/api/webhooks/lemonsqueezy",
        content=body,
        headers={
            "X-Signature": "deadbeef" * 8,
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 401


def test_route_returns_503_when_secret_not_configured(monkeypatch):
    """Until the integration goes live, the env var is empty; the
    route returns 503 so LS doesn't retry into a redelivery storm.
    503 carries a Retry-After header so LS backs off rather than
    permanently failing the delivery."""
    monkeypatch.setenv("AIJOBAGENT_LEMONSQUEEZY_WEBHOOK_SECRET", "")
    response = _client.post(
        "/api/webhooks/lemonsqueezy",
        content=b"{}",
        headers={
            "X-Signature": "abc",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 503
    assert "Retry-After" in response.headers
