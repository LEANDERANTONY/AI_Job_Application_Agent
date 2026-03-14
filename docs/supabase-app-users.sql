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