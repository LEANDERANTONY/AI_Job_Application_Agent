-- Resume builder sessions table. One row per user (PK = user_id).
-- The application upserts on every chat turn / draft-save; the row
-- is GC'd after RESUME_BUILDER_SESSION_TTL_DAYS (default 7) of
-- inactivity by the cron at the bottom of this file.

create table if not exists public.resume_builder_sessions (
    user_id uuid primary key references auth.users (id) on delete cascade,
    session_id text not null,
    status text not null default 'collecting',
    current_step text not null default 'basics',
    session_payload_json text not null default '',
    updated_at timestamptz not null default timezone('utc', now()),
    -- Refreshed by the application on every save_session upsert
    -- (timestamp + RESUME_BUILDER_SESSION_TTL_DAYS). Default is
    -- only used by the column itself for new rows in case the
    -- writer ever forgets to set it.
    expires_at timestamptz not null
        default timezone('utc', now()) + interval '7 days'
);

create index if not exists resume_builder_sessions_updated_at_idx
    on public.resume_builder_sessions (updated_at desc);

create index if not exists resume_builder_sessions_expires_at_idx
    on public.resume_builder_sessions (expires_at);

alter table public.resume_builder_sessions enable row level security;

-- SELECT also filters out expired rows so a draft past its TTL reads
-- as not-existing for the user even before the cron physically
-- removes it.
drop policy if exists "Users can view their own resume builder draft"
    on public.resume_builder_sessions;
create policy "Users can view their own resume builder draft"
    on public.resume_builder_sessions
    for select
    using (auth.uid() = user_id and expires_at > timezone('utc', now()));

drop policy if exists "Users can insert their own resume builder draft"
    on public.resume_builder_sessions;
create policy "Users can insert their own resume builder draft"
    on public.resume_builder_sessions
    for insert
    with check (auth.uid() = user_id);

drop policy if exists "Users can update their own resume builder draft"
    on public.resume_builder_sessions;
create policy "Users can update their own resume builder draft"
    on public.resume_builder_sessions
    for update
    using (auth.uid() = user_id)
    with check (auth.uid() = user_id);

drop policy if exists "Users can delete their own resume builder draft"
    on public.resume_builder_sessions;
create policy "Users can delete their own resume builder draft"
    on public.resume_builder_sessions
    for delete
    using (auth.uid() = user_id);

-- Physical cleanup. SECURITY DEFINER so the cron job (run as the
-- cron owner, not as a logged-in user) can DELETE rows even though
-- normal RLS would scope to auth.uid().
create or replace function public.cleanup_expired_resume_builder_sessions()
returns void
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
    delete from public.resume_builder_sessions
    where expires_at <= timezone('utc', now());
end;
$$;

-- Reset the cron schedule idempotently so re-running this file
-- doesn't queue duplicate jobs.
do $$
begin
    if exists (
        select 1 from cron.job
        where jobname = 'cleanup-expired-resume-builder-sessions'
    ) then
        perform cron.unschedule('cleanup-expired-resume-builder-sessions');
    end if;
end
$$;

select cron.schedule(
    'cleanup-expired-resume-builder-sessions',
    '*/5 * * * *',
    $$select public.cleanup_expired_resume_builder_sessions();$$
);
