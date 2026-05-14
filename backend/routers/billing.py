"""Billing routes: LS webhook + customer portal.

Two endpoints:

  * POST /webhooks/lemonsqueezy
        LS-delivered subscription event. Verifies the HMAC signature
        on the raw body, dispatches to
        `backend.webhooks.lemonsqueezy.process_webhook`. Returns 200
        on every signature-valid call (even when the event was
        skipped) so LS doesn't retry. 401 on signature mismatch,
        503 when the webhook secret env var isn't configured.

  * POST /billing/portal
        Authenticated. Calls the LS customer portal API to mint a
        one-time URL the frontend can window.location to. Returns
        503 when the LS_API_KEY env var isn't configured -- lets the
        integration ship to main without LS being live yet.

The webhook endpoint is intentionally hosted at /webhooks/lemonsqueezy
(no /api prefix on the path proper, but the app's settings.api_prefix
still applies in app.include_router) so the LS dashboard registration
URL is short. Tests for the LS-side rendering live in
tests/backend/test_lemonsqueezy_webhook.py.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.request_auth import get_optional_auth_tokens
from backend.services.auth_session_service import resolve_authenticated_context
from backend.webhooks.lemonsqueezy import (
    InvalidWebhookSignature,
    WebhookConfigError,
    process_webhook,
)
from src.errors import AppError


logger = logging.getLogger(__name__)

router = APIRouter(tags=["billing"])


# LS portal API is rate-limited per-customer; we only call it on
# explicit user clicks (Manage subscription button) so we don't
# need additional caching here. The 503 fallback keeps the route
# safe to enable in environments without LS configured.
_LS_API_BASE = "https://api.lemonsqueezy.com/v1"


def _ls_api_key() -> str:
    return os.getenv("AIJOBAGENT_LEMONSQUEEZY_API_KEY", "").strip()


@router.post("/webhooks/lemonsqueezy")
async def lemonsqueezy_webhook(request: Request) -> dict[str, Any]:
    """Handle a single LS subscription webhook delivery.

    Body shape is documented at https://docs.lemonsqueezy.com/help/webhooks.
    We don't bind to a pydantic model here because:
      * The signature is computed over the EXACT raw bytes; FastAPI's
        request body parsing would normalize whitespace and produce
        a signature mismatch.
      * LS may add new fields without warning; we only need a few
        keys (event_name, subscription_id, user_id, variant_id,
        status, renews_at, ends_at) and want to be forward-
        compatible.

    The X-Signature header is hex-encoded HMAC-SHA256; the handler
    in `backend.webhooks.lemonsqueezy.verify_signature` does a
    constant-time compare with the AIJOBAGENT_LEMONSQUEEZY_WEBHOOK_SECRET.
    """
    raw_body = await request.body()
    signature = request.headers.get("X-Signature", "") or ""

    try:
        result = process_webhook(raw_body=raw_body, signature=signature)
    except WebhookConfigError as exc:
        # The endpoint is intentionally offline (no webhook secret
        # configured). 503 with Retry-After tells LS to back off
        # without permanently failing the delivery -- once the secret
        # is set on the VPS and the dashboard webhook is registered,
        # LS will pick up retries from where it left off.
        logger.warning("lemonsqueezy_webhook_not_configured: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Lemon Squeezy webhook is not configured on this environment.",
            headers={"Retry-After": "300"},
        )
    except InvalidWebhookSignature as exc:
        # 401 stops LS from retrying immediately -- a bad signature
        # is a configuration mismatch, not a transient failure, and
        # retrying won't make it pass. The webhook secret in the LS
        # dashboard must match the env var on this server; rotate
        # both together when it changes.
        logger.warning("lemonsqueezy_webhook_invalid_signature: %s", exc)
        raise HTTPException(status_code=401, detail="Invalid webhook signature.")
    except Exception:  # noqa: BLE001 - unexpected handler failure
        # Truly unexpected internal errors propagate as 500 so LS
        # retries -- this is the ONE failure mode where we want a
        # redelivery (transient Supabase outage, network blip).
        logger.exception("lemonsqueezy_webhook_internal_error")
        raise

    return result


# ─── /billing/portal ────────────────────────────────────────────────────


@router.post("/billing/portal")
def get_billing_portal_url(
    request: Request,
    auth_tokens=Depends(get_optional_auth_tokens),
):
    """Return a one-time LS customer portal URL for the signed-in user.

    Implementation note: LS exposes
    GET /v1/customers/{id} which returns an `urls.customer_portal`
    field with a signed JWT URL valid for ~24h. We don't need to call
    a dedicated "create portal session" endpoint -- that's a Stripe
    pattern; LS just returns a long-lived signed URL on the customer
    resource directly.

    Returns:
        {"url": "<https://...>"} on success.
        503 when the API key env var isn't configured (the integration
            isn't live yet on this environment).
        404 when the user has no LS customer record (free tier user
            clicked Manage subscription -- shouldn't happen because the
            frontend gates the button on quota.tier != 'free', but
            defensive).
    """
    access_token, refresh_token = auth_tokens
    api_key = _ls_api_key()
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="Lemon Squeezy is not configured on this environment.",
        )

    if not (access_token and refresh_token):
        raise HTTPException(
            status_code=401,
            detail="Sign in to manage your subscription.",
        )

    try:
        context = resolve_authenticated_context(
            access_token=access_token,
            refresh_token=refresh_token,
        )
    except AppError:
        raise HTTPException(
            status_code=401,
            detail="Your session has expired. Sign in again.",
        )

    user_id = str(getattr(context.app_user, "id", "") or "")
    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Sign in to manage your subscription.",
        )

    # Lookup the LS customer_id from the subscriptions row. Lazy
    # import to keep this route module's import graph small (the
    # webhook route doesn't need the subscriptions lookup at all).
    from backend.subscriptions import get_active_subscription

    sub = get_active_subscription(user_id)
    if sub is None or not sub.processor_customer_id:
        raise HTTPException(
            status_code=404,
            detail="No active subscription found for this account.",
        )

    portal_url = _fetch_customer_portal_url(
        api_key=api_key,
        customer_id=sub.processor_customer_id,
    )
    if not portal_url:
        raise HTTPException(
            status_code=502,
            detail="Lemon Squeezy did not return a portal URL.",
        )
    return {"url": portal_url}


def _fetch_customer_portal_url(*, api_key: str, customer_id: str) -> str:
    """Hit GET /v1/customers/{id} and extract urls.customer_portal.

    Synchronous httpx call (we're inside a regular def route, not an
    async one). Short timeout because the user is waiting on a click;
    a 5s upper bound is consistent with the rest of the backend's
    upstream calls.

    Returns "" on any failure (logged) so the route surfaces 502 to
    the user.
    """
    try:
        import httpx
    except ImportError:  # pragma: no cover - httpx is in the deps
        logger.exception("httpx_not_installed")
        return ""

    try:
        response = httpx.get(
            f"{_LS_API_BASE}/customers/{customer_id}",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/vnd.api+json",
            },
            timeout=5.0,
        )
    except Exception:  # noqa: BLE001 - network exceptions vary
        logger.exception(
            "lemonsqueezy_customer_fetch_failed customer_id=%s", customer_id
        )
        return ""

    if response.status_code != 200:
        logger.warning(
            "lemonsqueezy_customer_fetch_non_200 status=%s customer_id=%s",
            response.status_code,
            customer_id,
        )
        return ""

    try:
        payload = response.json()
    except Exception:  # noqa: BLE001
        return ""

    if not isinstance(payload, dict):
        return ""
    data = payload.get("data") or {}
    attributes = data.get("attributes") if isinstance(data, dict) else {}
    urls = attributes.get("urls") if isinstance(attributes, dict) else {}
    if not isinstance(urls, dict):
        return ""
    return str(urls.get("customer_portal") or "").strip()
