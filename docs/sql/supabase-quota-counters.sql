-- AI Job Agent per-(user, period, counter) quota counters table + atomic
-- increment RPC.
--
-- Apply this in the Supabase SQL editor alongside docs/sql/supabase-bootstrap.sql.
-- Step 2 of the tier-enforcement series. Provides:
--   * aijobagent_quota_counters table -- one row per (user, period, counter)
--   * increment_aijobagent_counter RPC that atomically UPSERTs and returns the
--     new value
--   * RLS policy so users can only read their own counters
--
-- HelpmateAI's helpmate_quota_counters table uses a fixed two-column schema
-- (questions, premium) because that backend has exactly two counters. AI Job
-- Agent has eight different counters with mixed period semantics (some
-- monthly, some lifetime, some persistent), so the schema here generalizes:
-- counter_name is part of the composite PK and the period_key is a string
-- the application supplies (YYYY-MM for monthly, "lifetime" for lifetime
-- counters, "persistent" reserved for persistent caps not yet wired).

create table if not exists public.aijobagent_quota_counters (
    user_id uuid not null references auth.users (id) on delete cascade,
    period_key text not null,
    counter_name text not null,
    count integer not null default 0,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now()),
    primary key (user_id, period_key, counter_name)
);

create index if not exists aijobagent_quota_counters_user_id_idx
on public.aijobagent_quota_counters (user_id);

-- RLS: a user can read their own counter rows. INSERT/UPDATE flow through
-- the RPC below (security definer) so they don't need direct write policies.
-- The service role still bypasses RLS for ops.
alter table public.aijobagent_quota_counters enable row level security;

drop policy if exists "users can read own aijobagent quota counters"
on public.aijobagent_quota_counters;
create policy "users can read own aijobagent quota counters"
on public.aijobagent_quota_counters
for select
to authenticated
using (auth.uid() = user_id);

-- ---------------------------------------------------------------------------
-- Atomic increment RPC.
--
-- Pattern: INSERT ... ON CONFLICT ... DO UPDATE ... RETURNING. PostgreSQL
-- guarantees the upsert is atomic, so two concurrent workspace runs from the
-- same user produce two distinct return values (N+1 and N+2) without race.
-- The optional p_delta argument lets the refund path decrement by 1 by
-- passing -1 -- a separate "decrement" RPC would duplicate the same body.
--
-- The cap check intentionally happens in the SQL function so we never write
-- a row that would exceed the user's tier limit. On rejection the function
-- raises a SQLSTATE 'P0001' error with a stable detail string; the Python
-- wrapper catches that and translates it to a QuotaExceededError, which the
-- FastAPI exception handler converts to a structured 429 response.
-- ---------------------------------------------------------------------------

create or replace function public.increment_aijobagent_counter(
    p_user_id uuid,
    p_period_key text,
    p_counter_name text,
    p_cap integer,
    p_delta integer default 1
)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
    new_count integer;
    existing_count integer;
begin
    if p_delta = 0 then
        select count into new_count
        from public.aijobagent_quota_counters
        where user_id = p_user_id
          and period_key = p_period_key
          and counter_name = p_counter_name;
        return coalesce(new_count, 0);
    end if;

    -- Cap=-1 means "unlimited"; never write a row, just acknowledge. The
    -- Python helper short-circuits this same case before calling the RPC,
    -- but defending here makes the SQL function safe to call directly from
    -- an admin context too.
    if p_cap < 0 then
        insert into public.aijobagent_quota_counters
            (user_id, period_key, counter_name, count)
        values (p_user_id, p_period_key, p_counter_name, greatest(p_delta, 0))
        on conflict (user_id, period_key, counter_name)
        do update set
            count = greatest(aijobagent_quota_counters.count + p_delta, 0),
            updated_at = timezone('utc', now())
        returning count into new_count;
        return new_count;
    end if;

    -- Cap enforcement only fires on positive delta. Refunds (negative delta)
    -- always succeed -- they only run after a successful increment, so the
    -- counter is guaranteed to be >= 1 and we floor at zero defensively.
    if p_delta > 0 then
        select count into existing_count
        from public.aijobagent_quota_counters
        where user_id = p_user_id
          and period_key = p_period_key
          and counter_name = p_counter_name
        for update;

        existing_count := coalesce(existing_count, 0);
        if existing_count + p_delta > p_cap then
            raise exception 'aijobagent_quota_exceeded'
                using errcode = 'P0001',
                      detail = format(
                          'counter=%s cap=%s current=%s',
                          p_counter_name, p_cap, existing_count
                      );
        end if;
    end if;

    insert into public.aijobagent_quota_counters
        (user_id, period_key, counter_name, count)
    values (p_user_id, p_period_key, p_counter_name, greatest(p_delta, 0))
    on conflict (user_id, period_key, counter_name)
    do update set
        count = greatest(aijobagent_quota_counters.count + p_delta, 0),
        updated_at = timezone('utc', now())
    returning count into new_count;

    return new_count;
end;
$$;

-- Lock down execution. The RPC takes user_id as a parameter rather than
-- consulting auth.uid(), so granting EXECUTE to authenticated would let any
-- signed-in user burn another user's quota by passing their UUID. The
-- backend uses the service-role key for this RPC so it can call the
-- function while client-side calls cannot.
revoke all on function
    public.increment_aijobagent_counter(uuid, text, text, integer, integer)
from public;
revoke all on function
    public.increment_aijobagent_counter(uuid, text, text, integer, integer)
from authenticated;
grant execute on function
    public.increment_aijobagent_counter(uuid, text, text, integer, integer)
to service_role;
