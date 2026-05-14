-- AI Job Agent subscriptions table.
--
-- Apply this in the Supabase SQL editor alongside docs/sql/supabase-bootstrap.sql
-- and docs/sql/supabase-quota-counters.sql. Adds the row that
-- `backend.subscriptions.get_active_subscription` reads from, which in
-- turn drives the Lemon Squeezy-powered `resolve_user_tier`.
--
-- One row per user. The webhook upserts on `processor_subscription_id`
-- and replaces the row's `user_id`/`tier`/`status` columns; the
-- application reads the row by user_id, which is the PK. Multi-seat
-- Business subscriptions (one LS subscription, many users) are out of
-- scope for v1 — when that ships, drop the `user_id PRIMARY KEY` and
-- add a separate `subscription_seats` table.
--
-- Same style as supabase-quota-counters.sql:
--   * RLS so users can read their own row.
--   * No client-side write policies — webhook writes via service_role.
--   * Service_role bypasses RLS so the FastAPI service can read on
--     every gate check without a JWT round-trip.

create table if not exists public.subscriptions (
    user_id uuid primary key references auth.users (id) on delete cascade,
    -- "lemonsqueezy" today, "stripe" / "razorpay" stubs reserved so a
    -- future payment processor swap doesn't need a schema migration —
    -- just a new `resolve_user_tier` branch.
    processor text not null check (processor in ('lemonsqueezy', 'stripe', 'razorpay')),
    -- LS-side identifiers. processor_customer_id is the LS "customer"
    -- (one per email) so a portal redirect can target the right
    -- account. processor_subscription_id is unique across all
    -- processors -- it's the natural idempotency key for webhook
    -- upserts.
    processor_customer_id text,
    processor_subscription_id text not null unique,
    tier text not null check (tier in ('pro', 'business')),
    -- LS subscription statuses we care about. "active" / "past_due" /
    -- "cancelled" / "expired" / "paused" mirror the LS status enum;
    -- `resolve_user_tier` decides which of these still grant tier
    -- access based on current_period_end.
    status text not null check (status in ('active', 'past_due', 'cancelled', 'expired', 'paused')),
    -- LS sends this as a Unix timestamp in the renewal-related
    -- webhooks. We store the parsed timestamptz so the tier resolver
    -- can do a `current_period_end > now()` comparison without
    -- re-parsing on every read.
    current_period_end timestamptz,
    -- LS "cancelled" status means "user clicked cancel but tier
    -- access continues until period end". Distinct from
    -- `status='cancelled'` -- LS sets cancel_at_period_end=true but
    -- keeps status='active' on the data payload. The webhook router
    -- in backend/webhooks/lemonsqueezy.py mirrors that.
    cancel_at_period_end boolean not null default false,
    -- The LS variant_id that produced this subscription. Lets us
    -- recover the tier from the upstream config (env var mapping)
    -- without a database round-trip; the resolver reads `tier`
    -- directly because the variant→tier mapping is settled at
    -- webhook-write time.
    variant_id text,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

create index if not exists subscriptions_processor_subscription_id_idx
on public.subscriptions (processor_subscription_id);

-- RLS: a user can read their own subscription row. The webhook
-- handler uses the service-role key which bypasses RLS, so no INSERT
-- / UPDATE policies are needed at the row level. Granting write
-- policies to authenticated would let a signed-in user forge their
-- own subscription -- explicitly avoided.
alter table public.subscriptions enable row level security;

drop policy if exists "users can read own subscription"
on public.subscriptions;
create policy "users can read own subscription"
on public.subscriptions
for select
to authenticated
using (auth.uid() = user_id);

-- Webhook idempotency log. The LS webhook router writes one row per
-- processed event_id; repeated deliveries (LS retries on 5xx + at-
-- least-once semantics) are detected by the PK uniqueness check and
-- skipped before any state change.
--
-- Kept in a separate table so the subscriptions row stays compact and
-- so retention sweeps can prune the log independently. The log row
-- has no FK to subscriptions -- some events (cancelled-then-resumed,
-- unknown-variant) don't always carry a user_id we trust at write
-- time.
create table if not exists public.subscription_webhook_log (
    event_id text primary key,
    event_name text not null,
    received_at timestamptz not null default timezone('utc', now())
);

create index if not exists subscription_webhook_log_received_at_idx
on public.subscription_webhook_log (received_at);

-- Webhook log writes are service-role only. Authenticated users have
-- no reason to read or write -- the log exists for backend
-- idempotency, not user-visible history.
alter table public.subscription_webhook_log enable row level security;

-- No SELECT policy created -> authenticated callers see zero rows.
-- service_role bypasses RLS so the webhook router can still read +
-- insert freely.
