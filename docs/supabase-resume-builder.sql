create table if not exists public.resume_builder_sessions (
    user_id uuid primary key references auth.users (id) on delete cascade,
    session_id text not null,
    status text not null default 'collecting',
    current_step text not null default 'basics',
    session_payload_json text not null default '',
    updated_at timestamptz not null default timezone('utc', now())
);

create index if not exists resume_builder_sessions_updated_at_idx
    on public.resume_builder_sessions (updated_at desc);

alter table public.resume_builder_sessions enable row level security;

drop policy if exists "Users can view their own resume builder draft"
    on public.resume_builder_sessions;
create policy "Users can view their own resume builder draft"
    on public.resume_builder_sessions
    for select
    using (auth.uid() = user_id);

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
