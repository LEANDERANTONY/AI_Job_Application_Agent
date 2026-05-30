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

-- Atomic cap-enforced save (review M2). The Python save_saved_job path
-- counts existing rows then upserts in two steps, so two concurrent saves
-- of DISTINCT jobs at count = cap-1 both pass the check and both insert,
-- overshooting the cap. This SECURITY DEFINER RPC does the count + insert
-- in ONE transaction under a per-user transaction-scoped advisory lock, so
-- concurrent saves for the same user serialize and the cap holds. cap < 0
-- means unlimited; re-saving an already-saved job_id is always allowed (it
-- is an UPDATE, not a new row). The cap is passed by the backend, which
-- resolves the authoritative per-tier value (the DB row can't see the tier).
create or replace function public.save_saved_job_atomic(
    p_user_id uuid,
    p_job_id text,
    p_cap integer,
    p_payload jsonb
)
returns public.saved_jobs
language plpgsql
security definer
set search_path = public
as $$
declare
    existing_count integer;
    already_saved boolean;
    result_row public.saved_jobs;
begin
    -- Serialize concurrent saves for THIS user so the count below can't
    -- race the insert. Transaction-scoped: released at commit/rollback.
    perform pg_advisory_xact_lock(hashtext(p_user_id::text));

    select count(*), bool_or(job_id = p_job_id)
      into existing_count, already_saved
    from public.saved_jobs
    where user_id = p_user_id;

    existing_count := coalesce(existing_count, 0);
    already_saved := coalesce(already_saved, false);

    if p_cap >= 0 and not already_saved and existing_count >= p_cap then
        raise exception 'aijobagent_quota_exceeded'
            using errcode = 'P0001',
                  detail = format(
                      'counter=saved_jobs cap=%s current=%s',
                      p_cap, existing_count
                  );
    end if;

    insert into public.saved_jobs (
        user_id, job_id, source, title, company, location, employment_type,
        url, summary, description_text, posted_at, scraped_at, metadata,
        saved_at, updated_at
    )
    values (
        p_user_id,
        p_job_id,
        coalesce(p_payload->>'source', ''),
        coalesce(p_payload->>'title', ''),
        coalesce(p_payload->>'company', ''),
        coalesce(p_payload->>'location', ''),
        coalesce(p_payload->>'employment_type', ''),
        coalesce(p_payload->>'url', ''),
        coalesce(p_payload->>'summary', ''),
        coalesce(p_payload->>'description_text', ''),
        coalesce(p_payload->>'posted_at', ''),
        coalesce(p_payload->>'scraped_at', ''),
        coalesce(p_payload->'metadata', '{}'::jsonb),
        timezone('utc', now()),
        timezone('utc', now())
    )
    on conflict (user_id, job_id) do update set
        source = excluded.source,
        title = excluded.title,
        company = excluded.company,
        location = excluded.location,
        employment_type = excluded.employment_type,
        url = excluded.url,
        summary = excluded.summary,
        description_text = excluded.description_text,
        posted_at = excluded.posted_at,
        scraped_at = excluded.scraped_at,
        metadata = excluded.metadata,
        updated_at = timezone('utc', now())
    returning * into result_row;

    return result_row;
end;
$$;

grant execute on function public.save_saved_job_atomic(uuid, text, integer, jsonb) to authenticated;
