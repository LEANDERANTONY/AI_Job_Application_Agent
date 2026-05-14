# Lemon Squeezy subscription integration

Scope: how the AI Job Agent ties its tier-enforcement system to Lemon
Squeezy (LS) for paid Pro / Business plans. The tier-gating itself is
already shipped (see `backend/tiers.py` + `backend/quota.py`); this
doc covers how subscription state lands in the `subscriptions` table
and how the frontend invokes hosted checkout / customer portal.

## Architecture

```
                    LS hosted checkout (sandbox or live)
                         |
   user --> pricing CTA -+--> ?checkout[custom][user_id]=<supabase uid>
                         |
                         v
                    LS webhook delivery
                         |
                         v
   POST /api/webhooks/lemonsqueezy   (HMAC-SHA256 verified)
                         |
                         v
   backend/webhooks/lemonsqueezy.py
       parse → idempotency check → event-to-status mapping
                         |
                         v
   backend/subscriptions.py
       upsert subscriptions row + invalidate LRU cache
                         |
                         v
   backend/tiers.resolve_user_tier()
       reads through 60s LRU keyed by (user_id, UTC minute)
                         |
                         v
                quota gates everywhere
```

## Files

| File | Purpose |
| --- | --- |
| `docs/sql/supabase-subscriptions.sql` | `subscriptions` + `subscription_webhook_log` tables with RLS. Apply in the Supabase SQL editor. |
| `backend/subscriptions.py` | Read/write helper for `subscriptions`. LRU cache keyed by `(user_id, UTC minute)`; webhook upserts also invalidate. |
| `backend/webhooks/lemonsqueezy.py` | HMAC verification + payload parsing + event-to-status mapping + idempotency. Pure logic; no FastAPI. |
| `backend/routers/billing.py` | `POST /api/webhooks/lemonsqueezy` + `POST /api/billing/portal`. |
| `backend/tiers.py` | `resolve_user_tier(app_user)` — now consults `get_active_subscription`. Unchanged contract for all gate callers. |
| `frontend/src/lib/api.ts` | `getCheckoutUrl(tier, userId)`, `isLemonSqueezyEnabled()`, `getCustomerPortalUrl()`. |
| `frontend/src/components/landing-page.tsx` | Pricing CTAs route to LS hosted checkout. Falls back to "Coming soon" / mailto when LS isn't configured. |
| `frontend/src/components/workspace/WorkspaceShell.tsx` | Manage subscription button (paid tiers only) + post-checkout quota refresh. |

## Event → state mapping

| LS event | `status` written | `cancel_at_period_end` | Tier impact |
| --- | --- | --- | --- |
| `subscription_created` | `active` | false | Grants tier from variant_id. |
| `subscription_updated` | `active` | from payload | Refreshes row from payload. |
| `subscription_cancelled` | `cancelled` | true | Tier kept until `current_period_end`. |
| `subscription_resumed` | `active` | false | Cancellation reverted. |
| `subscription_expired` | `expired` | — | Terminal downgrade to Free. |
| `subscription_paused` | `paused` | — | Soft downgrade to Free. |
| `subscription_unpaused` | `active` | — | Tier restored. |
| `subscription_payment_success` | `active` | — | `current_period_end` refreshed. |
| `subscription_payment_failed` | `past_due` | — | Tier kept during dunning. |
| `subscription_payment_recovered` | `active` | — | Dunning cleared. |

Anything else (order events, unknown variant, missing `user_id`) is
logged + skipped with a 200 response so LS doesn't retry.

## Tier resolution semantics

`resolve_user_tier(app_user)` returns:

* `"free"` — no user, no subscription row, status in {`expired`, `paused`}, period elapsed, or unknown tier.
* `sub.tier` (one of `"pro"` / `"business"`) when:
  * `status ∈ {active, cancelled, past_due}` AND
  * `current_period_end > now()`

The read is LRU-cached for up to ~60 seconds. The webhook handler
invalidates the cache on every upsert so a fresh checkout return
sees the new tier on the next /workspace/quota call.

## Idempotency

LS retries on non-2xx and has at-least-once semantics. Two layers
protect against duplicate processing:

1. `subscription_webhook_log` (PK = `event_id` derived from `meta.webhook_id`). A duplicate delivery short-circuits to `{"status": "duplicate"}` and returns 200.
2. The `subscriptions` upsert is keyed on `user_id` and idempotent by construction — even if the log lookup fails open, re-running the upsert produces the same row.

## Setup (post-merge, before flipping to live LS)

1. **Apply the SQL migration** in the Supabase SQL editor:
   ```sql
   \i docs/sql/supabase-subscriptions.sql
   ```
2. **Create LS sandbox store + products**. Two variants: Pro ($9/mo) and Business ($39/mo). Note the numeric `variant_id` from each variant's API resource.
3. **Set env vars on the VPS**:
   * `AIJOBAGENT_LEMONSQUEEZY_API_KEY` — sandbox API key (Settings → API).
   * `AIJOBAGENT_LEMONSQUEEZY_WEBHOOK_SECRET` — generated in step 4 below.
   * `AIJOBAGENT_LEMONSQUEEZY_STORE_ID` — store_id (numeric) from the store settings.
   * `AIJOBAGENT_LEMONSQUEEZY_PRODUCT_VARIANT_PRO` / `_BUSINESS` — variant_ids from step 2.
4. **Register the webhook** in the LS dashboard:
   * URL: `https://<your-backend>/api/webhooks/lemonsqueezy`.
   * Secret: generate a 32+ char random string and paste into both the dashboard and the `_WEBHOOK_SECRET` env var.
   * Events to subscribe to: all `subscription_*` events.
5. **Set frontend env vars**:
   * `NEXT_PUBLIC_LEMONSQUEEZY_STORE_ID` — store *subdomain* (e.g. `yourstore` for `yourstore.lemonsqueezy.com`).
   * `NEXT_PUBLIC_LEMONSQUEEZY_PRODUCT_VARIANT_PRO` / `_BUSINESS` — same numeric variant_ids as the backend.
6. **Test in sandbox** — use the test card numbers from LS docs. A `subscription_created` webhook should arrive within ~5s; verify the `subscriptions` row via the Supabase table editor.
7. **Flip to live mode** — generate live API key + webhook secret, swap env vars, re-register the webhook in the live dashboard. Sandbox and live are entirely separate; nothing else changes in code.

## Local development

Without the env vars set, the backend webhook returns 503 (with a 5
minute Retry-After) and the frontend pricing CTA renders "Coming
soon" for Pro / falls back to the existing `mailto:` for Business.
This keeps `feat/lemonsqueezy-integration` mergeable into `main`
without requiring LS to be live.

To test the webhook locally:

```bash
# Compute a signature for a test body
python -c "
import hmac, hashlib, json
secret = 'your-test-secret'
body = json.dumps({'meta': {...}, 'data': {...}}).encode()
print(hmac.new(secret.encode(), body, hashlib.sha256).hexdigest())
"
# POST with that signature
curl -X POST http://localhost:8000/api/webhooks/lemonsqueezy \
  -H "X-Signature: <hex>" \
  -H "Content-Type: application/json" \
  -d '<body>'
```

The test suite in `tests/backend/test_lemonsqueezy_webhook.py` covers
each event type, signature failure, missing config, and idempotency.

## References

* Hosted checkouts: <https://docs.lemonsqueezy.com/help/checkout/hosted-checkouts>
* Webhook signing: <https://docs.lemonsqueezy.com/help/webhooks>
* Subscription API: <https://docs.lemonsqueezy.com/api/subscriptions>
* Customer object (portal URL field): <https://docs.lemonsqueezy.com/api/customers>
