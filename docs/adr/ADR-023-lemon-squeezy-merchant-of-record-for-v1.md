# ADR-023: Lemon Squeezy as Merchant of Record for v1

- Status: Accepted
- Date: 2026-05-15

## Context

The Day 42 tier-enforcement series shipped the full per-tier gating matrix but with every user resolving to `"free"` because there was no payment processor wired in. Day 43 closes that loop. The choice is not "should we accept payments?" — the enforcement code assumes paid tiers exist — but "which processor, and what does that imply for the architecture?".

Three operational constraints shaped the choice:

1. **The developer is a solo Indian resident, not a registered company.** Stripe and Razorpay both require an incorporated business entity (private limited / LLP / sole proprietorship with GST registration) and a business bank account before they will release payouts. Stripe India in particular gates on a business KYC review that has historically taken 4-8 weeks for new accounts, even for non-resident company structures.
2. **The product needs to handle US, EU, UK, and Indian payments from day one.** The job-application audience skews international; a payment processor that requires per-region setup (e.g. Razorpay for India + Stripe for everywhere else, with separate tax handling on each) doubles the surface area and forces the application to know which processor to route a given user to.
3. **VAT / GST / sales tax handling needs to be solved, not deferred.** EU customers expect a VAT invoice. US customers in tax-collecting states expect sales tax. India expects GST on B2B sales. We don't want to build tax-calculation logic ourselves and we don't want to register for VAT in every EU country individually.

A Merchant of Record (MoR) processor is the one that solves all three at once: the MoR is the legal seller of record, they handle the tax collection and remittance in every jurisdiction they cover, and they pay out to the developer in INR via wire after they've collected and remitted everything else.

## Decision

Use **Lemon Squeezy** as the v1 payment processor, integrated as a Merchant of Record. The `aijobagent_subscriptions.processor` column is a free-form text field so a future Stripe + Razorpay direct integration can land alongside LS without a schema migration.

### What Lemon Squeezy provides

- US-incorporated MoR (Lemon Squeezy LLC, a Stripe-owned subsidiary as of 2024).
- Handles VAT collection + remittance in every EU country, UK VAT, US sales tax in collecting states, and a single 1099 / Form 26AS at year-end for the seller.
- Hosted checkout pages (no PCI scope on our backend), customer portal for self-serve subscription management, and HMAC-signed webhooks for state changes.
- Indian-resident payouts in INR via local bank transfer after the LS payout schedule (weekly to monthly depending on volume).
- Fee structure: 5% + 50¢ per transaction. Higher than Stripe's 2.9% + 30¢, but the spread covers everything LS does on our behalf — and 2.9% + 30¢ wasn't available to us anyway without a business entity.

### Integration shape

The Day 43 LS scaffold (commits `1b8cf95`..`a236c81`) lands four pieces:

1. **`aijobagent_subscriptions` table** holds the LS-authoritative subscription state. One row per (active or past) subscription with columns `user_id`, `processor`, `processor_subscription_id`, `processor_customer_id`, `tier`, `status`, `current_period_end`. Partial unique index on `(user_id) WHERE status = 'active'` enforces at most one active sub per user.
2. **`backend/subscriptions.py`** is the store wrapper. It exposes `find_active(user_id) -> Subscription | None` (consulted by the post-Day-43 `resolve_user_tier` body) and `upsert_from_webhook(event)` (called by the webhook router).
3. **`POST /api/webhooks/lemonsqueezy`** verifies the HMAC-SHA256 signature using `hmac.compare_digest` against `LEMONSQUEEZY_WEBHOOK_SECRET` and dispatches by `meta.event_name`: `subscription_created`, `subscription_updated`, `subscription_payment_success` (refreshes `current_period_end`), `subscription_cancelled` (status → `cancelled`, the user keeps access until `current_period_end`), `subscription_expired` (status → `expired`).
4. **Frontend Upgrade CTA + customer portal link** opens the LS hosted checkout for the appropriate variant ID when `NEXT_PUBLIC_LEMONSQUEEZY_*` env vars are present; falls back to a "Coming soon" disabled-button-plus-tooltip when they're not, so the production frontend keeps shipping without waiting on LS dashboard config.

### Architectural neutrality

The `processor` column is text. When (not if) we move to Stripe + Razorpay direct:

- A user with both an active LS sub and an active Stripe sub has two rows; `find_active` picks the highest tier across them.
- The LS webhook continues to flow as long as legacy LS subscriptions exist. Migration is gradual — new signups use the new processor, existing LS subs ride out their current period.
- No table migration needed at processor #2; the column was always polymorphic.

Variant IDs (LS's primary key for "this thing is purchasable") are kept in env vars (`LEMONSQUEEZY_VARIANT_PRO`, `LEMONSQUEEZY_VARIANT_BUSINESS`) rather than the database, so rotating variants for an A/B test is a deploy, not a migration.

## Alternatives Considered

### 1. Stripe direct (after company incorporation)
Rejected for v1. Incorporating a private limited company in India costs ~₹15-25k, takes 2-4 weeks, requires CA-attested books from month one, and locks the developer into mandatory annual ROC filings + corporate income tax filings even on zero revenue. We're not at the revenue scale where the per-transaction savings justify those overheads. Revisit once monthly recurring revenue justifies the corporate setup — the LS-to-Stripe migration path is documented above and is non-disruptive.

### 2. Razorpay direct
Rejected for v1. Razorpay is the best-in-class processor for Indian buyers but doesn't help with the US/EU/UK audience we're targeting. It also doesn't act as MoR — we'd own the VAT collection problem ourselves for every EU customer. A future "Razorpay for Indian buyers + Stripe for everyone else" architecture is plausible after incorporation, but it's a v2+ decision.

### 3. Paddle
Considered seriously. Paddle is the other major MoR option and is generally cheaper than LS for higher transaction volumes (5% capped vs 5% + 50¢). Two factors tipped the choice to LS: (a) LS's webhook contract is simpler and better-documented than Paddle's V2 API (Paddle has gone through three API versions; the migration cost of being on V2 vs V3 is non-trivial), and (b) LS's hosted checkout is a first-class native UX while Paddle's is more iframe-heavy. If LS ever materially changes terms, Paddle is the documented fallback (the `processor` column accepts a new value).

### 4. Gumroad
Rejected. Gumroad is MoR and has lower friction than LS for one-off digital products, but their subscription support is thin — no native customer portal, weaker webhook contract, and the pricing model favours single-purchase products over recurring revenue.

### 5. Self-managed payments via PayPal
Rejected. PayPal isn't a true MoR; we'd still own VAT/tax handling. The PayPal-only payment surface also has known UX weakness for the US business audience (subscription chargebacks via PayPal historically resolve in the buyer's favour by default).

## Consequences

### Positive

- Payments are live without incorporating a company. The developer remains a solo individual until revenue justifies the business setup, and LS handles every tax obligation in the meantime.
- One processor covers the global audience. No per-region routing logic in the application.
- Hosted checkout means no PCI scope on our backend — the LS-hosted card page is the only surface that sees card data.
- Customer portal is free — no need to build cancel / change-payment-method / view-invoices UI ourselves.
- The architectural neutrality (`processor` column + variant IDs in env vs DB) means migrating to Stripe + Razorpay later is a code change, not a schema change.
- Webhook contract is HMAC-signed and idempotent; the store's `upsert_from_webhook(event)` is safe to call repeatedly on retries.

### Negative

- 5% + 50¢ is higher than Stripe direct (2.9% + 30¢). On a $19/mo Pro plan that's $1.45 vs $0.85 — a $0.60 spread per subscription per month. At 1000 active subs that's $7,200/year in differential fees, which is the threshold at which incorporating becomes economically worth it.
- LS payouts are weekly-to-monthly, not real-time. Cash-flow planning lives on the LS dashboard, not in our books.
- LS's variant IDs are opaque integers — every environment (dev, staging, prod) has its own set, and the frontend + backend each need their own copy via separate `NEXT_PUBLIC_*` / non-prefixed env vars. Mitigated by documenting the env-var matrix in `docs/lemon-squeezy.md`.
- If LS changes terms (fee structure, payout cadence, supported regions), the migration cost is real even with the architectural neutrality — we'd still need to build the second processor's integration. The neutrality just means the *application* code doesn't fight us; the *operational* migration is its own project.
- LS handles disputes and chargebacks on our behalf, but a chargeback still reaches us as a negative balance against the next payout. We have no direct control over LS's dispute-handling policy.

## Follow-Up

- Once the LS variant IDs are configured and the webhook is verified end-to-end against the LS sandbox, flip `feat/lemonsqueezy-integration` from "scaffold ready" to "live". Removing the "Coming soon" frontend fallback is a one-line change.
- Operational runbook for the LS dashboard (variant rotation, webhook secret rotation, refund flow, dispute response) — separate from this ADR, owned by the operator.
- Once 100 active subscriptions are reached, revisit the Stripe-direct cost analysis with real numbers. The migration path is documented; the trigger for executing it is revenue.

## Related

- [ADR-020](ADR-020-tier-resolution-via-single-shim-function.md): the resolver whose post-Day-43 body consults the `aijobagent_subscriptions` table this processor populates.
- [ADR-021](ADR-021-atomic-quota-with-refund-on-failure.md): the enforcement layer that's now fully load-bearing once paid tiers exist.
- [ADR-022](ADR-022-tier-aware-model-selection-via-constructor-injection.md): the premium model routing whose tiered behaviour becomes user-visible once payments go live.
