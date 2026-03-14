create table if not exists public.workflow_runs (
    id bigint generated always as identity primary key,
    user_id uuid not null references auth.users (id) on delete cascade,
    job_title text not null default '',
    fit_score integer not null default 0,
    review_approved boolean not null default false,
    model_policy text not null default '',
    workflow_signature text not null default '',
    workflow_snapshot_json text not null default '',
    report_payload_json text not null default '',
    tailored_resume_payload_json text not null default '',
    created_at timestamptz not null default timezone('utc', now())
);

alter table public.workflow_runs add column if not exists workflow_signature text not null default '';
alter table public.workflow_runs add column if not exists workflow_snapshot_json text not null default '';
alter table public.workflow_runs add column if not exists report_payload_json text not null default '';
alter table public.workflow_runs add column if not exists tailored_resume_payload_json text not null default '';

create index if not exists workflow_runs_user_id_created_at_idx
on public.workflow_runs (user_id, created_at desc);

alter table public.workflow_runs enable row level security;

drop policy if exists "users can read own workflow runs" on public.workflow_runs;
create policy "users can read own workflow runs"
on public.workflow_runs
for select
to authenticated
using (auth.uid() = user_id);

drop policy if exists "users can insert own workflow runs" on public.workflow_runs;
create policy "users can insert own workflow runs"
on public.workflow_runs
for insert
to authenticated
with check (auth.uid() = user_id);

create table if not exists public.artifacts (
    id bigint generated always as identity primary key,
    workflow_run_id bigint not null references public.workflow_runs (id) on delete cascade,
    artifact_type text not null default '',
    filename_stem text not null default '',
    storage_path text not null default '',
    created_at timestamptz not null default timezone('utc', now())
);

create index if not exists artifacts_workflow_run_created_at_idx
on public.artifacts (workflow_run_id, created_at desc);

alter table public.artifacts enable row level security;

drop policy if exists "users can read own artifacts" on public.artifacts;
create policy "users can read own artifacts"
on public.artifacts
for select
to authenticated
using (
    exists (
        select 1
        from public.workflow_runs
        where workflow_runs.id = artifacts.workflow_run_id
          and workflow_runs.user_id = auth.uid()
    )
);

drop policy if exists "users can insert own artifacts" on public.artifacts;
create policy "users can insert own artifacts"
on public.artifacts
for insert
to authenticated
with check (
    exists (
        select 1
        from public.workflow_runs
        where workflow_runs.id = artifacts.workflow_run_id
          and workflow_runs.user_id = auth.uid()
    )
);