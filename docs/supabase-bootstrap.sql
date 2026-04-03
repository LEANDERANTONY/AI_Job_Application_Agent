create table if not exists public.app_users (
    id uuid primary key references auth.users (id) on delete cascade,
    email text not null default '',
    display_name text not null default '',
    avatar_url text not null default '',
    created_at timestamptz not null default timezone('utc', now()),
    last_seen_at timestamptz not null default timezone('utc', now()),
    plan_tier text not null default 'free',
    account_status text not null default 'active'
);

alter table public.app_users enable row level security;

drop policy if exists "users can read own app_user record" on public.app_users;
create policy "users can read own app_user record"
on public.app_users
for select
to authenticated
using (auth.uid() = id);

drop policy if exists "users can insert own app_user record" on public.app_users;
create policy "users can insert own app_user record"
on public.app_users
for insert
to authenticated
with check (auth.uid() = id);

drop policy if exists "users can update own app_user record" on public.app_users;
create policy "users can update own app_user record"
on public.app_users
for update
to authenticated
using (auth.uid() = id)
with check (auth.uid() = id);

create table if not exists public.usage_events (
    id bigint generated always as identity primary key,
    user_id uuid not null references auth.users (id) on delete cascade,
    task_name text not null default '',
    model_name text not null default '',
    request_count integer not null default 0,
    prompt_tokens integer not null default 0,
    completion_tokens integer not null default 0,
    total_tokens integer not null default 0,
    response_id text not null default '',
    status text not null default '',
    created_at timestamptz not null default timezone('utc', now())
);

create index if not exists usage_events_user_id_created_at_idx
on public.usage_events (user_id, created_at desc);

alter table public.usage_events enable row level security;

drop policy if exists "users can read own usage events" on public.usage_events;
create policy "users can read own usage events"
on public.usage_events
for select
to authenticated
using (auth.uid() = user_id);

drop policy if exists "users can insert own usage events" on public.usage_events;
create policy "users can insert own usage events"
on public.usage_events
for insert
to authenticated
with check (auth.uid() = user_id);

create or replace function public.get_daily_usage_totals(
    target_user_id uuid,
    target_window_start timestamptz default timezone('utc', now())::date,
    target_window_end timestamptz default (timezone('utc', now())::date + interval '1 day')
)
returns table (
    request_count bigint,
    prompt_tokens bigint,
    completion_tokens bigint,
    total_tokens bigint,
    window_start timestamptz,
    window_end timestamptz
)
language plpgsql
security invoker
set search_path = public
as $$
begin
    if auth.uid() is null or auth.uid() <> target_user_id then
        raise exception 'Daily usage totals can only be read for the authenticated user.';
    end if;

    return query
    select
        coalesce(sum(usage_events.request_count), 0) as request_count,
        coalesce(sum(usage_events.prompt_tokens), 0) as prompt_tokens,
        coalesce(sum(usage_events.completion_tokens), 0) as completion_tokens,
        coalesce(sum(usage_events.total_tokens), 0) as total_tokens,
                target_window_start as window_start,
                target_window_end as window_end
    from public.usage_events
    where usage_events.user_id = target_user_id
            and usage_events.created_at >= target_window_start
            and usage_events.created_at < target_window_end;
end;
$$;

revoke all on function public.get_daily_usage_totals(uuid, timestamptz, timestamptz) from public;
grant execute on function public.get_daily_usage_totals(uuid, timestamptz, timestamptz) to authenticated;

create table if not exists public.saved_workspaces (
    user_id uuid primary key references auth.users (id) on delete cascade,
    job_title text not null default '',
    workflow_signature text not null default '',
    workflow_snapshot_json text not null default '',
    report_payload_json text not null default '',
    cover_letter_payload_json text not null default '',
    tailored_resume_payload_json text not null default '',
    expires_at timestamptz not null,
    updated_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.saved_jobs (
    user_id uuid not null references auth.users (id) on delete cascade,
    job_id text not null,
    source text not null default '',
    title text not null default '',
    company text not null default '',
    location text not null default '',
    employment_type text not null default '',
    url text not null default '',
    summary text not null default '',
    description_text text not null default '',
    posted_at text not null default '',
    scraped_at text not null default '',
    metadata jsonb not null default '{}'::jsonb,
    saved_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now()),
    primary key (user_id, job_id)
);

alter table public.saved_workspaces add column if not exists job_title text not null default '';
alter table public.saved_workspaces add column if not exists workflow_signature text not null default '';
alter table public.saved_workspaces add column if not exists workflow_snapshot_json text not null default '';
alter table public.saved_workspaces add column if not exists report_payload_json text not null default '';
alter table public.saved_workspaces add column if not exists cover_letter_payload_json text not null default '';
alter table public.saved_workspaces add column if not exists tailored_resume_payload_json text not null default '';
alter table public.saved_workspaces add column if not exists expires_at timestamptz not null default timezone('utc', now()) + interval '1 day';
alter table public.saved_workspaces add column if not exists updated_at timestamptz not null default timezone('utc', now());
alter table public.saved_jobs add column if not exists source text not null default '';
alter table public.saved_jobs add column if not exists title text not null default '';
alter table public.saved_jobs add column if not exists company text not null default '';
alter table public.saved_jobs add column if not exists location text not null default '';
alter table public.saved_jobs add column if not exists employment_type text not null default '';
alter table public.saved_jobs add column if not exists url text not null default '';
alter table public.saved_jobs add column if not exists summary text not null default '';
alter table public.saved_jobs add column if not exists description_text text not null default '';
alter table public.saved_jobs add column if not exists posted_at text not null default '';
alter table public.saved_jobs add column if not exists scraped_at text not null default '';
alter table public.saved_jobs add column if not exists metadata jsonb not null default '{}'::jsonb;
alter table public.saved_jobs add column if not exists saved_at timestamptz not null default timezone('utc', now());
alter table public.saved_jobs add column if not exists updated_at timestamptz not null default timezone('utc', now());

create index if not exists saved_workspaces_expires_at_idx
on public.saved_workspaces (expires_at);

create index if not exists saved_jobs_user_id_saved_at_idx
on public.saved_jobs (user_id, saved_at desc);

alter table public.saved_workspaces enable row level security;
alter table public.saved_jobs enable row level security;

create extension if not exists pg_cron with schema extensions;

create or replace function public.cleanup_expired_saved_workspaces()
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
    deleted_count integer := 0;
begin
    delete from public.saved_workspaces
    where expires_at <= timezone('utc', now());

    get diagnostics deleted_count = row_count;
    return deleted_count;
end;
$$;

revoke all on function public.cleanup_expired_saved_workspaces() from public;
grant execute on function public.cleanup_expired_saved_workspaces() to service_role;

drop policy if exists "users can read own saved workspace" on public.saved_workspaces;
create policy "users can read own saved workspace"
on public.saved_workspaces
for select
to authenticated
using (
    auth.uid() = user_id
    and expires_at > timezone('utc', now())
);

drop policy if exists "users can insert own saved workspace" on public.saved_workspaces;
create policy "users can insert own saved workspace"
on public.saved_workspaces
for insert
to authenticated
with check (auth.uid() = user_id);

drop policy if exists "users can update own saved workspace" on public.saved_workspaces;
create policy "users can update own saved workspace"
on public.saved_workspaces
for update
to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "users can delete own saved workspace" on public.saved_workspaces;
create policy "users can delete own saved workspace"
on public.saved_workspaces
for delete
to authenticated
using (auth.uid() = user_id);

drop policy if exists "users can read own saved jobs" on public.saved_jobs;
create policy "users can read own saved jobs"
on public.saved_jobs
for select
to authenticated
using (auth.uid() = user_id);

drop policy if exists "users can insert own saved jobs" on public.saved_jobs;
create policy "users can insert own saved jobs"
on public.saved_jobs
for insert
to authenticated
with check (auth.uid() = user_id);

drop policy if exists "users can update own saved jobs" on public.saved_jobs;
create policy "users can update own saved jobs"
on public.saved_jobs
for update
to authenticated
using (auth.uid() = user_id)
with check (auth.uid() = user_id);

drop policy if exists "users can delete own saved jobs" on public.saved_jobs;
create policy "users can delete own saved jobs"
on public.saved_jobs
for delete
to authenticated
using (auth.uid() = user_id);

select public.cleanup_expired_saved_workspaces();

do $$
begin
    if exists (
        select 1
        from cron.job
        where jobname = 'cleanup-expired-saved-workspaces'
    ) then
        perform cron.unschedule('cleanup-expired-saved-workspaces');
    end if;
exception
    when undefined_table then
        null;
end;
$$;

select cron.schedule(
    'cleanup-expired-saved-workspaces',
    '*/5 * * * *',
    $$select public.cleanup_expired_saved_workspaces();$$
);
