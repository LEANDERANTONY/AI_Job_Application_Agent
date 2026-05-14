-- AI Job Agent per-LLM-call trace table for cost-per-query and tier-margin
-- validation.
--
-- Apply this in the Supabase SQL editor alongside the other migrations under
-- docs/sql/. Step 3 of the production-safety pack. Provides:
--   * aijobagent_run_traces table -- one row per LLM call recorded by
--     `src.openai_service`, with prompt + completion tokens and a USD cost
--     computed against the pricing map in the same module.
--   * RLS so authenticated users can read their own rows, while writes are
--     service-role-only (parity with `aijobagent_quota_counters`).
--
-- The point: the existing `usage_events` table records per-call token usage
-- but no cost; computing cost client-side at read time is brittle when
-- OpenAI moves pricing. Recording USD at write time lets the cron-side
-- nightly-eval (and any future tier-margin dashboard) compare actuals to
-- the modeled COGS without re-deriving prices.
--
-- Schema decisions:
--   * trace_id is a UUID so the cost row can be referenced from logs / a
--     future tier-margin dashboard without exposing the underlying auto-
--     increment surface.
--   * cost_usd uses numeric(10,6) to capture sub-cent costs without
--     floating-point drift; the pricing map in openai_service ranges from
--     $0.10/1M (gpt-5.4-nano) up through $30/1M (gpt-5.5 output), so a
--     5-bullet workflow run lands in the $0.001 - $0.05 band.
--   * task_name is text rather than an enum because new agents land
--     frequently; constraining to an enum would block migrations behind
--     a backfill every time we add one.

create table if not exists public.aijobagent_run_traces (
    trace_id uuid primary key default gen_random_uuid(),
    user_id uuid references auth.users(id) on delete cascade,
    task_name text not null,
    model_name text not null,
    prompt_tokens int not null default 0,
    completion_tokens int not null default 0,
    cost_usd numeric(10, 6) not null default 0,
    success boolean not null default true,
    created_at timestamptz not null default timezone('utc', now())
);

-- Hot reads: per-user cost summaries for the upcoming tier-margin endpoint;
-- per-day cost rollups for the nightly cost-of-goods report. Both filter on
-- (user_id, created_at) so a single composite index covers both queries.
create index if not exists aijobagent_run_traces_user_id_created_at_idx
on public.aijobagent_run_traces (user_id, created_at desc);

-- Per-task cost diagnostics: when a tailoring run looks expensive we want
-- to slice by task_name (tailoring vs review vs resume_generation) over
-- a rolling window. The single-column index on task_name is cheap and
-- makes the GROUP BY work without a sequential scan.
create index if not exists aijobagent_run_traces_task_name_idx
on public.aijobagent_run_traces (task_name);

-- ---------------------------------------------------------------------------
-- RLS
--
-- Reads: authenticated users see their own rows ONLY. This mirrors the
-- pattern from `aijobagent_quota_counters` -- the per-user table is queryable
-- from the UI for the user's own diagnostics, but the writer is service-role
-- because the application records the trace from inside OpenAIService where
-- the user identity is already known.
--
-- Writes: no policy granted for `authenticated`. The service role bypasses
-- RLS, which is how `record_trace` in `backend.run_traces` inserts rows.
-- Granting write to `authenticated` would let any signed-in user fake their
-- own cost rows -- not catastrophic, but a useless surface.
-- ---------------------------------------------------------------------------

alter table public.aijobagent_run_traces enable row level security;

drop policy if exists "users can read own aijobagent run traces"
on public.aijobagent_run_traces;
create policy "users can read own aijobagent run traces"
on public.aijobagent_run_traces
for select
to authenticated
using (auth.uid() = user_id);

-- No insert / update / delete policies for `authenticated`. The application
-- writes via the service-role client (`backend.run_traces.record_trace`),
-- which bypasses RLS. Direct table writes from the frontend / a signed-in
-- session must fail with a permission error.
