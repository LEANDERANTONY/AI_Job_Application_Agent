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

create index if not exists saved_jobs_user_id_saved_at_idx
on public.saved_jobs (user_id, saved_at desc);

alter table public.saved_jobs enable row level security;

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
