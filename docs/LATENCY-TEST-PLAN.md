# Latency Test Plan — exhaustive baseline runner

This is a self-contained hand-off for a parallel chat session.

The user is running two streams in parallel:
- **THIS chat (latency):** build an exhaustive latency-baseline runner across
  every endpoint, including the agentic LLM chain.
- **Other chat (error handling):** static error-message audit + synthetic
  error-handling battle test + frontend `humanizeApiError` helper. **Don't
  touch error-handling code in this chat** — those edits are happening in
  parallel and will conflict if both sides poke the router.

Read this doc first, then build the runner. Ask the user before pushing.

---

## Project facts you need

- **Branch:** `frontend-redesign`
- **Worktree:** `.claude/worktrees/trusting-jones-afaa7e`
- **`.env`** lives at the repo root and auto-loads via `src/config.py`.
  `OPENAI_API_KEY` is configured.
- **Default model:** `gpt-5.4-mini`. High-trust agents use `gpt-5.4`.
- **Pytest run command (Windows):**
  ```
  "C:/Users/Leander Antony A/Documents/Projects/AI_Job_Application_Agent/.venv/Scripts/python.exe" -m pytest <path> -q
  ```
- **Quality runner pattern:** existing runners live in `tests/quality/`, all
  follow the same shape (deterministic + LLM modes, `--include-llm` flag,
  JSON scorecard at `tests/quality/_last_*.json`, console table). Mirror
  this pattern.
- **Single uvicorn worker** on the VPS — no race conditions in the
  in-memory `_SESSIONS` / `_JOBS` dicts.
- **Cached jobs cache** measured ~360ms warm, ~5.5s cold, vs ~25s for
  live fan-out (Day 40 in DEVLOG).

---

## What's in scope

Build `tests/quality/latency_runner.py` mirroring the existing quality
runner pattern. Per endpoint:

- N=10 warm runs after a single cold run.
- Capture cold latency separately (first hit after fresh app instance).
- Report p50 / p95 / p99 of warm runs.
- PASS / FAIL against per-endpoint budget (p95 budget; exit 1 if any
  endpoint exceeds its budget by >50%).
- JSON scorecard at `tests/quality/_last_latency_run.json`.
- Console table sorted by p95 descending.

LLM-using endpoints gated behind `--include-llm` (cost ~$0.50-1.00 per
run, mostly the full agentic chain). Default invocation runs only the
deterministic paths.

## What's out of scope (DON'T touch these — error-handling chat owns them)

- `frontend/src/lib/api.ts` `request()` helper
- `backend/routers/*.py` HTTPException sites
- `backend/services/*` AppError raise sites
- `tests/test_error_messages.py` (will be added by the error-handling chat)
- `tests/quality/error_handling_runner.py` (will be added by the
  error-handling chat)

## Endpoints to measure

### Tier 1 — deterministic / no LLM (cheap; always run)

| # | Endpoint | Method | Notes | p50 budget | p95 budget |
|---|---|---|---|---|---|
| 1 | `/health` | GET | sanity baseline | 50ms | 100ms |
| 2 | `/jobs/search` cached, simple query | POST | warm | 500ms | 1500ms |
| 3 | `/jobs/search` cached, with filters | POST | warm | 800ms | 2000ms |
| 4 | `/jobs/search` cached, FIRST hit | POST | cold | 6s | 8s |
| 5 | `/jobs/search?live=true` | POST | escape hatch, slow on purpose; skip default | 30s | 45s |
| 6 | `/workspace/resume/upload` TXT | POST | 5KB sample, deterministic regex | 500ms | 1500ms |
| 7 | `/workspace/job-description/upload` TXT | POST | deterministic | 500ms | 1500ms |
| 8 | `/workspace/analyze` deterministic | POST | run_assisted=False | 500ms | 1500ms |
| 9 | `/workspace/analyze-jobs` start | POST | spawns thread, returns handle | 100ms | 200ms |
| 10 | `/workspace/analyze-jobs/{id}` poll | GET | reads `_JOBS` dict | 100ms | 200ms |
| 11 | `/workspace/resume-builder/start` | POST | creates session | 200ms | 500ms |
| 12 | `/workspace/resume-builder/commit` | POST | structured profile build | 500ms | 1000ms |
| 13 | `/workspace/resume-builder/export` DOCX | POST | python-docx is fast | 300ms | 600ms |
| 14 | `/workspace/resume-builder/export` PDF | POST | WeasyPrint render | 1500ms | 4000ms |
| 15 | `/workspace/artifacts/export` DOCX | POST | from a workspace_snapshot | 300ms | 600ms |
| 16 | `/workspace/artifacts/export` PDF | POST | WeasyPrint render | 1500ms | 4000ms |
| 17 | `/workspace/artifacts/preview` resume | POST | HTML preview | 200ms | 500ms |
| 18 | `/workspace/save` | POST | Supabase write (mock the store) | 500ms | 1500ms |
| 19 | `/workspace/saved` | GET | Supabase read + re-render | 800ms | 2000ms |
| 20 | `/workspace/saved-jobs` list | GET | Supabase read | 500ms | 1500ms |

### Tier 2 — LLM-gated (only with `--include-llm`)

| # | Endpoint | Method | Notes | p50 budget | p95 budget |
|---|---|---|---|---|---|
| 21 | `/workspace/resume/upload` LLM hybrid | POST | mini extraction | 8s | 12s |
| 22 | `/workspace/resume-builder/message` LLM | POST | mini conversational turn | 3s | 5s |
| 23 | `/workspace/resume-builder/generate` | POST | structuring pass + render | 10s | 20s |
| 24 | `/workspace/assistant/answer` sync | POST | mini single-turn | 3s | 6s |
| 25 | `/workspace/assistant/answer/stream` TTFT | POST | time-to-first-`delta` event | 1500ms | 2500ms |
| 26 | `/workspace/assistant/answer/stream` total | POST | first-byte to `done` event | 5s | 10s |
| 27 | `/workspace/analyze` assisted (full chain) | POST | 4-agent orchestrator end-to-end | 60s | 120s |

### Tier 3 — per-agent isolation (only with `--include-llm`)

Bypass HTTP, call the agent class directly. Use the same fixture pair
the existing agent battle tests use
(`tests/quality/sample_resumes/02-midcareer-tech.txt`,
`tests/quality/sample_jds/07-placer-big-data-engineer.txt`).

| # | Agent | Notes | p50 budget | p95 budget |
|---|---|---|---|---|
| 28 | `TailoringAgent` | mid-trust mini | 8s | 15s |
| 29 | `ReviewAgent` | high-trust gpt-5.4 | 8s | 18s |
| 30 | `ResumeGenerationAgent` | high-trust gpt-5.4 | 10s | 20s |
| 31 | `CoverLetterAgent` | high-trust gpt-5.4 | 8s | 18s |
| 32 | Full orchestrator chain | 4 agents in sequence | 35s | 70s |

## Runner architecture

```
tests/quality/latency_runner.py
  ├─ _BUDGETS — dict[str, dict] mapping scenario name → p50/p95 budget + LLM flag
  ├─ _SCENARIOS — list of dicts: {name, scenario_fn, requires_llm}
  │     scenario_fn returns a callable that performs ONE measured operation
  ├─ _measure(callable, n=10) — runs N times, returns {cold, warm: [t1, ..., tN]}
  ├─ _percentiles(samples) — returns {p50, p95, p99}
  ├─ _make_app() — fresh FastAPI TestClient with all imports re-initialized
  │   (used so cold latency is honest — re-import the modules to drop
  │    module-level caches)
  ├─ _run_scenario(scenario, *, openai_service) — measures cold + warm
  ├─ _format_table(results) — pretty console output sorted by p95 desc
  └─ main() — argparse + run + JSON dump
```

### Scenario function shape

Each scenario function returns a closure that does ONE complete operation:

```python
def _scenario_jobs_search_cached_simple(client):
    def run():
        response = client.post("/api/jobs/search", json={"query": "engineer"})
        assert response.status_code == 200
    return run
```

The runner wraps each `run()` in `time.perf_counter()` and records
samples.

### Cold split

Cold latency is measured by the FIRST call against a freshly imported
app instance. The runner re-imports `backend.app` between cold and warm
batches:

```python
def _make_app(monkey=None):
    import importlib
    import backend.app as backend_app
    importlib.reload(backend_app)  # drops module-level caches
    return TestClient(backend_app.app)
```

For per-route cold splits, do this once per scenario. For "process
cold" splits (where `_SESSIONS` / `_JOBS` are dropped), this is the
right granularity; module-level lru_caches reset, but Python's import
cache for transitive deps stays warm. Document this in the scorecard.

### LLM scenarios

Tier 2 + Tier 3 scenarios use the real `OpenAIService()` (constructed
once and shared across runs to avoid re-establishing the OpenAI HTTP
client). Mirror the existing pattern from
`tests/quality/orchestrator_e2e_runner.py` lines ~280-310.

### Streaming TTFT

`/workspace/assistant/answer/stream` returns `text/event-stream`.
Capture TTFT by reading the response in chunks and timestamping the
first `event: delta` line:

```python
import time
start = time.perf_counter()
ttft = None
total = None
with client.stream("POST", "/api/workspace/assistant/answer/stream", json=payload) as resp:
    for line in resp.iter_lines():
        if ttft is None and line.startswith("event: delta"):
            ttft = time.perf_counter() - start
        if line.startswith("event: done"):
            total = time.perf_counter() - start
            break
return ttft, total
```

## CLI shape

```
python tests/quality/latency_runner.py
python tests/quality/latency_runner.py --include-llm
python tests/quality/latency_runner.py --include-llm --json out.json
python tests/quality/latency_runner.py --include-llm --skip-live  # skip Tier 1 #5
python tests/quality/latency_runner.py --tier 1                   # only tier 1
```

## Output

### Console

Sorted by p95 desc so the slowest path shows first:

```
================================================================================
Tier-3 latency scorecard
================================================================================

Endpoint                          cold      p50      p95      p99    budget95   status
--------------------------------------------------------------------------------
/workspace/analyze (assisted)     58.4s    52.1s    74.3s    82.0s    120.0s    PASS
/workspace/resume-builder/gen     11.8s     9.2s    16.4s    18.1s     20.0s    PASS
TailoringAgent (isolated)         12.3s    10.8s    14.7s    15.2s     15.0s    PASS
WeasyPrint PDF render              2.4s     2.1s     3.0s     3.4s      4.0s    PASS
/jobs/search cached (cold)         5.2s        -        -        -      6.0s    PASS  (cold-only)
/jobs/search cached (simple)         -    420ms    980ms    1.2s     1.5s    PASS
...
```

### JSON

```json
{
  "ran_with_llm": true,
  "ran_at": "2026-05-08T...",
  "scenarios": [
    {
      "name": "/jobs/search cached (simple)",
      "tier": 1,
      "cold_ms": 5200,
      "samples_warm_ms": [420, 410, 435, ...],
      "p50_ms": 420,
      "p95_ms": 980,
      "p99_ms": 1200,
      "budget_p95_ms": 1500,
      "status": "PASS"
    },
    ...
  ],
  "summary": {
    "total_scenarios": 32,
    "passed": 30,
    "failed": 2,
    "total_wall_clock_seconds": 412.5,
    "estimated_llm_cost_usd": 0.45
  }
}
```

## Threshold + exit policy

- **PASS** if `actual_p95 <= budget_p95`.
- **WARN** if `budget_p95 < actual_p95 <= 1.5 * budget_p95`.
- **FAIL** if `actual_p95 > 1.5 * budget_p95`.
- Exit 0 if no FAILs (warns are advisory).
- Exit 1 if any FAIL.

Budget tuning policy: budgets above are starting points. After the
first run, if a measurement is consistently 30-50% below budget,
tighten it. If consistently above, investigate (regression?) before
loosening.

## Cost estimate

Per `--include-llm` run, rough OpenAI spend:

- Tier 2: ~$0.10 (resume builder turn + generate + assistant + stream)
- Tier 3: ~$0.40 (4 agents × 1 fixture, full orchestrator)
- **Total: ~$0.50 per run.**

If you run with `--include-llm` 5 times during development (tuning
budgets), that's ~$2.50. Acceptable.

## Verification + ship steps

1. Build the runner. Use `TestClient` from `fastapi.testclient`.
2. Run `python tests/quality/latency_runner.py` (deterministic only)
   first. Verify all Tier 1 scenarios complete and produce sane numbers.
3. Adjust budgets if any are way off (e.g., if `/jobs/search` cached
   warm is consistently 200ms with budget 1500ms, tighten to 600ms).
4. Run `python tests/quality/latency_runner.py --include-llm` ONCE.
   Capture the JSON scorecard and verify Tier 2/3 numbers look sane
   (no unexpected timeouts or failures).
5. Run a SECOND time to check warm-warm consistency. p95 between the
   two runs should be within ~20% for non-LLM paths.
6. Commit:
   - `tests/quality/latency_runner.py`
   - `tests/quality/_last_latency_run.json` is gitignored — DO NOT
     commit it (matches the existing `_last_*.json` convention).
   - Add a brief note to DEVLOG (Day 41 or whatever the next day is)
     documenting the baselines.
7. Push when the user signs off.

## Known gotchas

- **WeasyPrint on Windows** — needs MSYS2 mingw64 on the PATH. The
  existing `_configure_weasyprint_windows_runtime()` in
  `src/exporters.py` handles this; don't re-instantiate.
- **OpenAI SDK has 120s timeout, max_retries=2** — a single LLM call
  can take up to ~6 minutes worst-case. Set the runner's per-scenario
  timeout to 6.5 minutes to avoid spurious failures.
- **`_JOBS` dict is process-local.** A scenario that starts an analyze
  job must poll on the SAME app instance. Don't reload between start
  and poll.
- **Supabase reads/writes:** mock `SavedWorkspaceStore`,
  `SavedJobsStore`, `ResumeBuilderStore` so the latency measures the
  code path, not the network. The error-handling chat will be doing
  similar mocking — make sure your stubs don't conflict if their
  changes land first (rebase + re-test).
- **Streaming TTFT:** the `flush_interval -1` Caddy setting only
  applies in production. In TestClient, SSE chunks come through
  immediately, so TTFT measurements will be slightly OPTIMISTIC vs
  real production. Document this in the scorecard.
- **Cold metrics are noisy.** Single-shot cold measurement has high
  variance. The plan accepts this — cold is a "first hit" sanity check,
  not a budgeted threshold.

## Hand-off back

When done, append a section to this file (or to DEVLOG) with:
- Actual measured baselines (p50/p95) per scenario.
- Any scenarios that needed budget adjustment, and why.
- Any FAIL scenarios that surfaced real performance issues — file as
  follow-up tasks rather than blocking the runner ship.

The error-handling chat is producing parallel changes to the routers
and frontend. Coordinate via the user before merging if both branches
of work end up touching adjacent files.
