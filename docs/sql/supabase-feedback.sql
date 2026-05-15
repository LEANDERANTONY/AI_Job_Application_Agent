-- AI Job Agent online feedback table.
--
-- Apply this in the Supabase SQL editor alongside the other migrations
-- under docs/sql/. Adds the online feedback loop — a tiny 👍 / 👎 control
-- on every tailored artifact, cover letter, JD summary, assistant turn,
-- and resume-builder session.
--
-- Schema decisions:
--   * feedback_id is a UUID so each row is referenced uniquely without
--     exposing the underlying auto-increment surface.
--   * trace_id is intentionally a nullable plain uuid column (NOT a FK
--     to aijobagent_run_traces). Reasons:
--       (a) Cleanup resilience — when an old run_traces row is pruned
--           by a retention sweep, we don't want a foreign-key cascade
--           to delete the feedback (the user's thumbs-down on a
--           tailored resume still teaches us something even after the
--           per-call trace is gone).
--       (b) Surface independence — some feedback surfaces won't have
--           a corresponding trace at all (e.g. a resume-builder session
--           is the join of many LLM calls; a single trace_id wouldn't
--           capture the full session). Keeping the FK off means we
--           can attach feedback to a logical surface even when there's
--           no single trace row to point at.
--   * surface is a CHECK constraint rather than an enum because
--     migrating enum values requires a CREATE TYPE + drop-recreate
--     dance; CHECK lets us add a new surface ('career_brief', etc.)
--     with a one-line ALTER instead.
--   * rating is a CHECK constraint on the two-value set; we don't use
--     a smallint (-1 / 0 / 1) because the canonical product UX is
--     two clear buttons, not a tri-state.
--   * comment defaults to '' so the JSON write path doesn't have to
--     send NULL — `record_feedback` always inserts a string.

create table if not exists public.aijobagent_feedback (
    feedback_id uuid primary key default gen_random_uuid(),
    user_id uuid not null references auth.users(id) on delete cascade,
    -- Nullable, no FK on purpose. See the cleanup-resilience note above.
    trace_id uuid,
    surface text not null check (surface in (
        'tailored_resume',
        'cover_letter',
        'jd_summary',
        'assistant_turn',
        'resume_builder_session'
    )),
    rating text not null check (rating in ('up', 'down')),
    -- Default '' so the application path can always insert a string;
    -- the column is truncated by the service layer at 4096 chars
    -- before insert.
    comment text not null default '',
    created_at timestamptz not null default timezone('utc', now())
);

-- Read hot paths: per-user feedback history (the user's profile page
-- might show "your 24 ratings so far") and per-surface aggregate
-- ("78% of users thumbed up the tailored resume this week"). Both
-- queries filter on (user_id, created_at) or (surface, created_at);
-- a pair of composite indexes covers both without a sequential scan.
create index if not exists aijobagent_feedback_user_id_created_at_idx
on public.aijobagent_feedback (user_id, created_at desc);

create index if not exists aijobagent_feedback_surface_created_at_idx
on public.aijobagent_feedback (surface, created_at desc);

-- ---------------------------------------------------------------------------
-- RLS
--
-- Reads: authenticated users see their own rows ONLY. Mirrors
-- aijobagent_quota_counters / aijobagent_run_traces — the per-user
-- aggregate (eventual product feature) loads from the user's own
-- rows, not a cross-user blob.
--
-- Inserts: authenticated users can insert their OWN rows. Unlike
-- aijobagent_run_traces (service-role-only writes), feedback is
-- intentionally driven by the user — the JS client posts to
-- /workspace/feedback which writes through the service-role key, but
-- a future direct-client write path stays possible. We restrict the
-- insert policy to rows whose user_id matches auth.uid() so a
-- compromised client key can't forge feedback for another user.
--
-- Updates / deletes: no policy granted; feedback is immutable from the
-- application's perspective. A user changing their mind should submit
-- a fresh row (timestamp tells us which one wins for aggregations).
-- ---------------------------------------------------------------------------

alter table public.aijobagent_feedback enable row level security;

drop policy if exists "users can read own aijobagent feedback"
on public.aijobagent_feedback;
create policy "users can read own aijobagent feedback"
on public.aijobagent_feedback
for select
to authenticated
using (auth.uid() = user_id);

drop policy if exists "users can write own aijobagent feedback"
on public.aijobagent_feedback;
create policy "users can write own aijobagent feedback"
on public.aijobagent_feedback
for insert
to authenticated
with check (auth.uid() = user_id);
