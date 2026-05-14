# ADR-021: Atomic Quota with Refund-on-Failure

- Status: Accepted
- Date: 2026-05-15

## Context

The pre-Day-42 quota path was inherited from the Streamlit era: `src/quota_service.py` aggregated `usage_events` rows for the current UTC day and pre-checked the count against an env-driven daily limit before each assisted call. This pattern had two structural problems for the new tier-enforcement matrix:

1. **It's racy.** Two concurrent `/workspace/analyze` calls from the same user both see `count = N` in the SELECT, both decide they're under the cap, both execute their workflow, and both INSERT their own `usage_events` row. The user gets `N + 2` requests on a cap of `N + 1`. The window is small (one round-trip) but the cap is per-month and concurrent runs from one user are realistic — two browser tabs, retried CTAs, etc.
2. **It can't distinguish "request happened" from "request succeeded".** Pre-check + post-increment makes the increment a single-direction commitment; once the workflow runs and fails, the count is consumed. A network blip during the Forge agent shouldn't burn the user's monthly `tailored_applications` credit, but the legacy pattern offered no rollback.

The HelpmateAI quota path (which we draw a lot of structure from) keeps the pre-check + post-increment shape. AI Job Agent runs more concurrent agents per user (the supervised pipeline is four sequential agents per `/workspace/analyze`, plus parsers and search), so the racy window is more exposed AND the consequences of an irreversible increment are worse.

## Decision

A single SQL function does the cap check and the increment in one transaction; failures refund.

### Atomic increment in SQL

`public.increment_aijobagent_counter(p_user_id uuid, p_period_key text, p_counter_name text, p_cap integer, p_delta integer)` lives in `docs/sql/supabase-quota-counters.sql`. The function's body:

1. For positive deltas: `SELECT count ... FOR UPDATE` on the existing row (or 0 if absent), then check `existing_count + p_delta > p_cap`. If so, `RAISE EXCEPTION 'aijobagent_quota_exceeded' USING ERRCODE = 'P0001', DETAIL = format('counter=%s cap=%s current=%s', ...)`.
2. `INSERT ... ON CONFLICT (user_id, period_key, counter_name) DO UPDATE SET count = greatest(count + p_delta, 0), updated_at = now() RETURNING count`.

The `FOR UPDATE` + same-transaction INSERT-ON-CONFLICT serializes concurrent calls on the same row. Two workspace runs producing counts `N + 1` and `N + 2` respectively — never both `N + 1`. The SQL function is `SECURITY DEFINER` so the cap check can't be bypassed by a client; EXECUTE is granted *only* to `service_role` because the function takes `p_user_id` as a parameter and would otherwise let any signed-in user burn another user's quota by passing their UUID.

### Python wrapper translates the P0001

`backend/quota.py::check_and_increment(counter_name, user_id, tier, *, lifetime=False)` resolves the cap from `TIER_CAPS[tier][counter_name]`, short-circuits when the cap equals `UNLIMITED` (no row is written; the table stays compact), and otherwise calls the RPC. The supabase-py wrapper surfaces the P0001 as an `APIError` whose message contains the SQL DETAIL string; we pattern-match `"aijobagent_quota_exceeded"` and re-raise as `src.errors.QuotaExceededError(counter, current, cap, reset_period, tier)`.

### Single global 429 handler

`backend/app.py` registers exactly one exception handler for `QuotaExceededError`. The handler returns a 429 with a fixed body shape (`detail`, `code: "tier_limit_exceeded"`, `counter`, `current`, `cap`, `reset_period`, `tier`). Every gate raises through this path; the frontend renders one upgrade-nudge component regardless of which counter fired.

### Refund-on-failure

`backend/quota.py::refund(counter_name, user_id, tier, *, lifetime=False)` calls the same RPC with `p_delta = -1`. The SQL function floors at zero on negative deltas (`greatest(count + p_delta, 0)`) and never invokes the cap check on a negative delta (the second `if p_delta > 0:` branch). The orchestrator's outermost try/except catches `AgentExecutionError` and similar pipeline failures, calls `refund("tailored_applications", ...)` (and `refund("premium_applications", ...)` if premium was opted in), then re-raises. Refunds are best-effort: a Supabase outage during refund logs and swallows so the caller can re-raise the original workflow exception — the user's account has already absorbed the increment, and a refund failure shouldn't mask the real error.

### Period keys

Period partitioning is on the application side: a `period_key` column lets the call site write to either the current month (`current_period_key()` returns `"YYYY-MM"`) or a literal `"lifetime"`. The Free-tier `resume_builder_sessions` cap (1 session ever) uses `lifetime=True`; the same counter on Pro / Business (3 / 15 per month) uses the default monthly partition. No scheduled reset job — the next month's first increment writes a fresh row with `count = 1`.

### In-memory fallback for tests

When Supabase isn't configured (local dev, CI without secrets), `backend/quota.py` falls back to a process-local `_InMemoryQuotaBackend` that mirrors the SQL semantics: same atomicity guarantees within a single process via a `threading.Lock`, same `_QuotaExceededAtBackend` exception type that's translated identically. Production must run with Supabase — the in-memory backend is not safe under concurrent workers (each worker has its own dict).

## Alternatives Considered

### 1. Keep the pre-check + post-increment pattern, add a retry on conflict
Rejected. Detecting the race requires a unique constraint *and* a way to roll back the workflow if the second insert fails — which means the workflow has to be idempotent enough to re-run, or we leak side effects (LLM tokens spent, partial agent outputs). Atomic-at-SQL is strictly simpler than "make the whole workflow restartable".

### 2. Optimistic locking with `UPDATE ... WHERE count = expected`
Rejected. Two-call shape (read, then conditional update) widens the racy window between calls and doesn't compose well with the FastAPI request lifecycle. The single `FOR UPDATE` + INSERT-ON-CONFLICT in the SQL function is the canonical PostgreSQL atomic-counter idiom.

### 3. Sequence-backed counter instead of `count` column
Rejected. Sequences don't gap-fill, so a refund (decrement) wouldn't free the credit. Sequences also can't enforce a cap directly; the application would still need a pre-check.

### 4. Charge after success only (no pre-increment at all)
Considered. Wait until the workflow returns successfully, then increment. Removes the refund machinery entirely but introduces a new race: ten concurrent workflows can all run "for free" before any of them increments, and the cap doesn't fire until the 11th request arrives — which by then has already been *accepted* on the server side. Atomic-increment before work + refund-on-failure is the right side of that trade.

### 5. Persistent row-count counters in the `aijobagent_quota_counters` table
Rejected for `saved_jobs` and `saved_workspaces`. These caps are persistent (current row count vs cap, not period-keyed), and the row count *already lives* in the dedicated store table. Mirroring it into the quota table means two sources of truth and a sync problem. Instead, the gate calls `SavedJobsStore.count(user_id)` directly and compares against `TIER_CAPS[tier]["saved_jobs"]` before the insert. The `/workspace/quota` snapshot reads the row count from the same store for the UI indicator. The `aijobagent_quota_counters` table only holds the period-keyed counters.

## Consequences

### Positive

- Concurrent runs from the same user can't breach the cap. The SQL function serializes them.
- Workflow failures don't burn the user's quota credit. A transient OpenAI outage that takes down `tailored_applications` for a single run gets refunded the next instant; the user retries and the second attempt re-increments.
- One global 429 handler means every gate's frontend treatment is identical. No per-counter response-shape skew.
- The same Python function and same SQL function support both monthly and lifetime periods via a kwarg — no parallel `lifetime_quota_counters` table.
- `UNLIMITED` short-circuits at the Python layer so the SQL function never sees the unlimited case; the table stays compact even for high-volume Pro / Business counters like `job_searches`.

### Negative

- Every gated request makes a Supabase round-trip. Latency adds ~30-80 ms per gate. The orchestrator's `/workspace/analyze` path passes through 2 gates max (`tailored_applications` + optionally `premium_applications`), so 2× 80 ms = 160 ms in the worst case — well inside acceptable for a pipeline that already takes 20-40 s of LLM time.
- Refunds add a second round-trip on failures. Best-effort by design: if the refund itself fails, the user has lost a credit. Mitigated by logging the failure with full context so we can manually refund from the dashboard if support gets a ticket.
- The in-memory fallback diverges from production behaviour under multi-worker test runs. We mitigate by running our test suite single-process; nobody is running pytest with `--numprocesses` against the in-memory backend.

## Follow-Up

- Add a Supabase metric on the `aijobagent_quota_counters` insert rate to catch unusual burn patterns (e.g. a script abusing the assistant turn cap).
- Periodic background reconciliation: walk `usage_events` totals against `aijobagent_quota_counters.count` for the current month — if they ever diverge by more than a small noise threshold, something is bypassing the gate.
- When Day 43 (Lemon Squeezy) lands and refunds become user-visible (a cancelled Pro user's mid-month rows need to behave correctly under the resolver swap), revisit whether monthly counters carry over period start metadata. Currently the user's first action after a tier change writes to a fresh row tagged with the new tier's caps — this is correct, but documenting the behaviour is worth a runbook entry.

## Related

- [ADR-020](ADR-020-tier-resolution-via-single-shim-function.md): the resolver that supplies the `tier` argument to every `check_and_increment` call.
- [ADR-018](ADR-018-three-layer-llm-retry-and-per-agent-fallback-isolation.md): the orchestrator-level retry layers that decide which failures get the refund treatment (per-agent fallback fires before refund; refund only fires when the whole workflow exits with an error).
