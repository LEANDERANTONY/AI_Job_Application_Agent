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

create table if not exists public.saved_workspaces (
    user_id uuid primary key references auth.users (id) on delete cascade,
    job_title text not null default '',
    workflow_signature text not null default '',
    workflow_snapshot_json text not null default '',
    report_payload_json text not null default '',
    tailored_resume_payload_json text not null default '',
    expires_at timestamptz not null,
    updated_at timestamptz not null default timezone('utc', now())
);

alter table public.saved_workspaces add column if not exists job_title text not null default '';
alter table public.saved_workspaces add column if not exists workflow_signature text not null default '';
alter table public.saved_workspaces add column if not exists workflow_snapshot_json text not null default '';
alter table public.saved_workspaces add column if not exists report_payload_json text not null default '';
alter table public.saved_workspaces add column if not exists tailored_resume_payload_json text not null default '';
alter table public.saved_workspaces add column if not exists expires_at timestamptz not null default timezone('utc', now()) + interval '1 day';
alter table public.saved_workspaces add column if not exists updated_at timestamptz not null default timezone('utc', now());

create index if not exists saved_workspaces_expires_at_idx
on public.saved_workspaces (expires_at);

alter table public.saved_workspaces enable row level security;

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
