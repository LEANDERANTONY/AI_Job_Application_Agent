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