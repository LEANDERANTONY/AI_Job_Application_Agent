alter table public.workflow_runs
add column if not exists workflow_signature text not null default '';

alter table public.workflow_runs
add column if not exists workflow_snapshot_json text not null default '';

alter table public.workflow_runs
add column if not exists report_payload_json text not null default '';

alter table public.workflow_runs
add column if not exists tailored_resume_payload_json text not null default '';