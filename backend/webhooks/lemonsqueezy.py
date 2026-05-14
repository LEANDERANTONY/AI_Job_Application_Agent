"""Lemon Squeezy subscription webhook handler.

The single entry point is `process_webhook(*, raw_body, signature)`,
which:

  1. Verifies the X-Signature header (hex-encoded HMAC-SHA256 of the
     raw body, signed with AIJOBAGENT_LEMONSQUEEZY_WEBHOOK_SECRET).
     Constant-time compare via `hmac.compare_digest`. Failure
     surfaces as `InvalidWebhookSignature` -- the FastAPI route
     converts that to a 401.
  2. Parses the LS event envelope. Unknown / unparseable payloads
     log + return early (200 to LS so it doesn't retry).
  3. Checks the idempotency log via
     `backend.subscriptions.has_processed_event`. Repeated deliveries
     for the same event_id are a no-op (LS retries on non-2xx and
     has at-least-once semantics).
  4. Maps the event_name to a subscription state via
     `_apply_event(...)`. Subscription tier is derived from the LS
     variant_id (env vars
     AIJOBAGENT_LEMONSQUEEZY_PRODUCT_VARIANT_PRO /
     _VARIANT_BUSINESS); unknown variant logs + returns early.
  5. Calls `backend.subscriptions.upsert_subscription(...)` and
     `mark_event_processed(...)`.

The route handler in `backend/routers/billing.py` wraps this with
FastAPI plumbing. Tests in tests/backend/test_lemonsqueezy_webhook.py
exercise each event type's state transition + signature failures.

Event mapping (locked by the brief; matches LS docs):

    EVENT NAME                       OUR STATUS    NOTES
    subscription_created             active        new paid signup
    subscription_updated             active        any field change
    subscription_cancelled           cancelled     cancel_at_period_end=true
    subscription_resumed             active        cancel_at_period_end=false
    subscription_expired             expired       terminal downgrade
    subscription_paused              paused        soft downgrade
    subscription_unpaused            active        resume after pause
    subscription_payment_success     active        renewal cleared
    subscription_payment_failed      past_due      enters dunning
    subscription_payment_recovered   active        dunning recovered

All other events log + return early without writing.

LS API reference: https://docs.lemonsqueezy.com/help/webhooks
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from backend.subscriptions import (
    Subscription,
    has_processed_event,
    invalidate_subscription_cache,
    mark_event_processed,
    upsert_subscription,
)


logger = logging.getLogger(__name__)


# Env-driven configuration. Read at function-call time (not import
# time) so tests can monkeypatch via monkeypatch.setenv without
# reloading the module.
def _webhook_secret() -> str:
    return os.getenv("AIJOBAGENT_LEMONSQUEEZY_WEBHOOK_SECRET", "").strip()


def _variant_pro() -> str:
    return os.getenv("AIJOBAGENT_LEMONSQUEEZY_PRODUCT_VARIANT_PRO", "").strip()


def _variant_business() -> str:
    return os.getenv(
        "AIJOBAGENT_LEMONSQUEEZY_PRODUCT_VARIANT_BUSINESS", ""
    ).strip()


# ─── Event-to-status mapping ────────────────────────────────────────────


# (event_name -> (status_override, cancel_at_period_end_override)).
# Each override is None when the event doesn't dictate that field;
# the handler falls through to the payload's value in that case.
# Events that DO pin the field explicitly (most do, for status; only
# created / cancelled / resumed do for cancel flag) carry a concrete
# value here.
#
# `subscription_updated` deliberately leaves status=None: LS emits
# this event for any field change, including ones that don't reflect
# in a fresh status value. Trusting the payload's status keeps the
# row in sync without `subscription_updated` clobbering a prior
# cancelled / paused state.
_EVENT_TO_STATUS: dict[str, tuple[Optional[str], Optional[bool]]] = {
    "subscription_created": ("active", False),
    "subscription_updated": (None, None),
    "subscription_cancelled": ("cancelled", True),
    "subscription_resumed": ("active", False),
    "subscription_expired": ("expired", None),
    "subscription_paused": ("paused", None),
    "subscription_unpaused": ("active", None),
    "subscription_payment_success": ("active", None),
    "subscription_payment_failed": ("past_due", None),
    "subscription_payment_recovered": ("active", None),
}


# Mapping from LS payload `data.attributes.status` -> our status
# column. LS sends "on_trial" for free-trial subscriptions; we treat
# them as Free until they convert (trial revenue isn't worth the
# additional state). "unpaid" is the legacy name for past_due in
# some LS versions; alias it. Unknown values fall back to "expired"
# so the user is downgraded conservatively.
_LS_STATUS_TO_OUR_STATUS: dict[str, str] = {
    "active": "active",
    "cancelled": "cancelled",
    "expired": "expired",
    "paused": "paused",
    "past_due": "past_due",
    "unpaid": "past_due",
    "on_trial": "active",
}


# ─── Exceptions ─────────────────────────────────────────────────────────


class InvalidWebhookSignature(Exception):
    """X-Signature header mismatch on the raw request body.

    Raised by `verify_signature`. The route converts this to a 401 --
    LS retries on 5xx but NOT on 4xx, so a 401 also stops the retry
    loop on a misconfigured webhook secret (which is what we want;
    we shouldn't quietly accumulate retries on bad signatures)."""


class WebhookConfigError(Exception):
    """The webhook handler isn't configured for production.

    Currently fires when AIJOBAGENT_LEMONSQUEEZY_WEBHOOK_SECRET is
    empty. The route converts this to a 503 so LS doesn't retry the
    way it would for a 5xx -- a 503 with a Retry-After header is the
    correct signal for "this endpoint is intentionally offline right
    now"."""


# ─── Signature verification ─────────────────────────────────────────────


def verify_signature(*, raw_body: bytes, signature: str) -> None:
    """Verify the X-Signature header against the raw body.

    LS signs each delivery with HMAC-SHA256 over the exact raw
    request body, hex-encoded. We use `hmac.compare_digest` to keep
    the comparison constant-time so a timing attack can't recover
    the secret.

    Raises:
        WebhookConfigError -- the AIJOBAGENT_LEMONSQUEEZY_WEBHOOK_SECRET
                              env var isn't set.
        InvalidWebhookSignature -- the signature doesn't match.
    """
    secret = _webhook_secret()
    if not secret:
        raise WebhookConfigError(
            "AIJOBAGENT_LEMONSQUEEZY_WEBHOOK_SECRET is not configured."
        )
    if not signature:
        raise InvalidWebhookSignature("X-Signature header missing.")

    expected = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()

    # Both sides hex-encoded; compare_digest accepts str. The check
    # is case-insensitive on hex but LS sends lowercase; lowercase
    # the incoming signature defensively so a future LS change to
    # uppercase doesn't break verification.
    if not hmac.compare_digest(expected, signature.strip().lower()):
        raise InvalidWebhookSignature("Signature mismatch.")


# ─── Payload parsing ────────────────────────────────────────────────────


@dataclass(frozen=True)
class ParsedWebhook:
    """The fields the handler actually cares about. Pulled out of the
    LS payload by `_parse_payload`. Keeping the dataclass small means
    the rest of the handler doesn't have to deep-index into nested
    dicts at every branch."""

    event_id: str
    event_name: str
    user_id: str
    subscription_id: str
    customer_id: str
    variant_id: str
    status_from_payload: str
    renews_at: Optional[datetime]
    ends_at: Optional[datetime]
    cancelled_flag: bool


def _parse_iso_timestamp(value: Any) -> Optional[datetime]:
    """Parse an LS-shaped ISO-8601 timestamp into a tz-aware
    datetime. LS sends timestamps like "2026-05-31T19:14:21.000000Z"
    or "2026-05-31T19:14:21Z"; both are handled by replacing Z with
    +00:00 before datetime.fromisoformat. Returns None on missing /
    unparseable values."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _parse_payload(raw_body: bytes) -> Optional[ParsedWebhook]:
    """Pull the fields the handler cares about out of the LS envelope.

    LS envelope shape (abbreviated):

        {
          "meta": {
            "event_name": "subscription_created",
            "webhook_id": "uuid-of-this-delivery",
            "custom_data": {"user_id": "<our supabase auth uid>"}
          },
          "data": {
            "id": "12345",        # LS subscription id
            "type": "subscriptions",
            "attributes": {
              "status": "active",
              "variant_id": 67890,
              "customer_id": 54321,
              "cancelled": false,
              "renews_at": "2026-06-14T19:14:21.000000Z",
              "ends_at": null,
              ...
            }
          }
        }

    Returns None when the body isn't valid JSON or doesn't carry the
    expected shape. The route still returns 200 on parse failures
    (logged) so LS doesn't retry a malformed delivery into a
    redelivery storm.
    """
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        logger.warning("lemonsqueezy_webhook_unparseable_body")
        return None
    if not isinstance(payload, dict):
        return None

    meta = payload.get("meta") or {}
    data = payload.get("data") or {}
    attributes = data.get("attributes") if isinstance(data, dict) else {}
    custom_data = meta.get("custom_data") if isinstance(meta, dict) else {}

    if not isinstance(meta, dict):
        meta = {}
    if not isinstance(data, dict):
        data = {}
    if not isinstance(attributes, dict):
        attributes = {}
    if not isinstance(custom_data, dict):
        custom_data = {}

    event_name = str(meta.get("event_name") or "").strip()
    # event_id: prefer meta.webhook_id (LS-managed uuid for the
    # delivery); fall back to a synthetic key combining event_name
    # + subscription_id if absent (older LS payloads). The
    # idempotency log treats this as the PK so it has to be stable
    # across retries of the same delivery.
    webhook_id = str(meta.get("webhook_id") or "").strip()
    subscription_id = str(data.get("id") or "").strip()
    if webhook_id:
        event_id = f"lemonsqueezy:{webhook_id}"
    elif subscription_id and event_name:
        event_id = f"lemonsqueezy:{event_name}:{subscription_id}"
    else:
        event_id = ""

    user_id = str(custom_data.get("user_id") or "").strip()

    variant_id_raw = attributes.get("variant_id")
    variant_id = str(variant_id_raw) if variant_id_raw is not None else ""

    customer_id_raw = attributes.get("customer_id")
    customer_id = str(customer_id_raw) if customer_id_raw is not None else ""

    return ParsedWebhook(
        event_id=event_id,
        event_name=event_name,
        user_id=user_id,
        subscription_id=subscription_id,
        customer_id=customer_id,
        variant_id=variant_id,
        status_from_payload=str(attributes.get("status") or "").strip(),
        renews_at=_parse_iso_timestamp(attributes.get("renews_at")),
        ends_at=_parse_iso_timestamp(attributes.get("ends_at")),
        cancelled_flag=bool(attributes.get("cancelled") or False),
    )


# ─── Variant -> tier mapping ────────────────────────────────────────────


def _tier_for_variant(variant_id: str) -> Optional[str]:
    """Resolve an LS variant_id to our tier name.

    Returns None when the variant isn't recognized -- the handler
    logs + returns early so LS doesn't retry a misconfigured variant
    until the env var is fixed. Both env vars must be set in
    production; the local-dev path keeps them empty and the handler
    short-circuits at the route level via WebhookConfigError if the
    secret is missing.
    """
    variant_id = str(variant_id or "").strip()
    if not variant_id:
        return None
    if variant_id == _variant_pro():
        return "pro"
    if variant_id == _variant_business():
        return "business"
    return None


# ─── Event application ──────────────────────────────────────────────────


def _resolve_period_end(
    event_name: str,
    *,
    renews_at: Optional[datetime],
    ends_at: Optional[datetime],
) -> Optional[datetime]:
    """Pick the right boundary for current_period_end based on event.

    LS sends both `renews_at` (the next renewal, set on active subs)
    and `ends_at` (the cutoff for tier access on cancelled subs).
    On cancellation, the resolver in `backend.tiers` needs ends_at
    so cancelled-but-not-yet-expired subs keep tier access. On
    everything else, renews_at is the right boundary.
    """
    if event_name == "subscription_cancelled":
        return ends_at or renews_at
    if event_name == "subscription_expired":
        # No future boundary; the resolver will see status="expired"
        # and downgrade regardless. Surface ends_at if present so
        # the row is informative.
        return ends_at or renews_at
    return renews_at or ends_at


def _apply_event(parsed: ParsedWebhook) -> bool:
    """Map a parsed webhook to an upsert. Returns True on success,
    False when the event was skipped (unknown event, unknown variant,
    missing user_id).

    Skipped events still consume the idempotency log slot so LS
    doesn't keep redelivering the same dud -- there's no value in
    retrying a webhook for a variant we don't recognize.
    """
    mapping = _EVENT_TO_STATUS.get(parsed.event_name)
    if mapping is None:
        logger.info(
            "lemonsqueezy_webhook_unhandled_event event=%s",
            parsed.event_name,
        )
        return False

    if not parsed.user_id:
        # custom_data.user_id is how we bind an LS subscription to
        # our Supabase user. If the checkout was started without it
        # (manual subscription created in the LS dashboard, for
        # example), we have nothing to write -- log + skip.
        logger.warning(
            "lemonsqueezy_webhook_missing_user_id event=%s subscription_id=%s",
            parsed.event_name,
            parsed.subscription_id,
        )
        return False

    if not parsed.subscription_id:
        logger.warning(
            "lemonsqueezy_webhook_missing_subscription_id event=%s",
            parsed.event_name,
        )
        return False

    tier = _tier_for_variant(parsed.variant_id)
    if tier is None:
        logger.warning(
            "lemonsqueezy_webhook_unknown_variant event=%s variant_id=%s",
            parsed.event_name,
            parsed.variant_id,
        )
        return False

    status_override, cancel_override = mapping
    if status_override is not None:
        status = status_override
    else:
        # subscription_updated falls through here. Mirror the
        # payload's status field through the LS->our mapping so the
        # row reflects the real state (cancelled / paused / etc).
        # Unknown values are mapped to "expired" defensively.
        raw_status = parsed.status_from_payload.lower()
        status = _LS_STATUS_TO_OUR_STATUS.get(raw_status, "expired")
    if cancel_override is not None:
        cancel_at_period_end = cancel_override
    else:
        # Fall back to the payload's cancelled flag. LS sets this on
        # updated events when the user toggles cancel-at-period-end
        # mid-period without re-firing subscription_cancelled.
        cancel_at_period_end = parsed.cancelled_flag

    period_end = _resolve_period_end(
        parsed.event_name,
        renews_at=parsed.renews_at,
        ends_at=parsed.ends_at,
    )

    sub = Subscription(
        user_id=parsed.user_id,
        processor="lemonsqueezy",
        processor_customer_id=parsed.customer_id,
        processor_subscription_id=parsed.subscription_id,
        tier=tier,
        status=status,
        current_period_end=period_end,
        cancel_at_period_end=cancel_at_period_end,
        variant_id=parsed.variant_id,
    )
    upsert_subscription(sub)
    invalidate_subscription_cache()
    return True


# ─── Public entry point ─────────────────────────────────────────────────


def process_webhook(*, raw_body: bytes, signature: str) -> dict[str, Any]:
    """Verify + parse + apply an LS webhook delivery.

    Returns a small status dict describing what happened. The FastAPI
    route renders this as a 200 JSON response on every signature-
    valid call -- even when the event was skipped (unknown event,
    duplicate delivery, missing user_id). The signature check is the
    only failure path that bubbles up; everything else logs + returns
    a "skipped" status so LS doesn't retry.

    The dict shape:
        {
          "status": "applied" | "duplicate" | "skipped" | "ignored",
          "event_name": <str>,
          "event_id": <str>,
          "reason": <optional str>  # for status="skipped"/"ignored"
        }
    """
    # 1. Signature verification. The route wraps WebhookConfigError
    # to a 503; InvalidWebhookSignature to a 401.
    verify_signature(raw_body=raw_body, signature=signature)

    # 2. Parse. Unparseable -> 200 ignored, no idempotency log slot
    # consumed (we don't know event_id, so we can't dedupe anyway).
    parsed = _parse_payload(raw_body)
    if parsed is None:
        return {"status": "ignored", "reason": "unparseable_body"}

    # 3. Idempotency check. LS retries on non-2xx (and has at-least
    # -once semantics), so duplicate deliveries are expected.
    if parsed.event_id and has_processed_event(parsed.event_id):
        return {
            "status": "duplicate",
            "event_name": parsed.event_name,
            "event_id": parsed.event_id,
        }

    # 4. Apply.
    applied = _apply_event(parsed)

    # 5. Mark processed regardless of apply outcome -- a skipped
    # event (unknown variant, missing user_id) shouldn't keep
    # re-delivering. The PK on subscription_webhook_log catches
    # genuine duplicate deliveries before we re-enter this branch.
    if parsed.event_id:
        mark_event_processed(parsed.event_id, parsed.event_name)

    if applied:
        return {
            "status": "applied",
            "event_name": parsed.event_name,
            "event_id": parsed.event_id,
        }
    return {
        "status": "skipped",
        "event_name": parsed.event_name,
        "event_id": parsed.event_id,
    }


__all__ = [
    "InvalidWebhookSignature",
    "ParsedWebhook",
    "WebhookConfigError",
    "process_webhook",
    "verify_signature",
]
