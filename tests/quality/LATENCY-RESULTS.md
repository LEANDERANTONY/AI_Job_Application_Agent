# Latency baseline — first run

Initial baseline produced by [latency_runner.py](latency_runner.py) on the
`frontend-redesign` branch. Captures p50 / p95 / p99 of every backend
endpoint plus per-agent and full-orchestrator chain latency.

Run shape:

- Tier 1 (deterministic, no LLM): N=10 warm samples after a cold call.
- Tier 2 (LLM, single calls): N=3 warm samples (N=1 for `/analyze`
  assisted full chain).
- Tier 3 (per-agent isolated, full orchestrator): N=2 warm samples
  (N=1 for full chain). Higher N here would smooth p95 but at real
  OpenAI cost.

OpenAI cost for the full `--include-llm` run was rough order-of-magnitude
$1.

## Headline summary

| Run | Wall clock | PASS | WARN | FAIL | Total |
|---|---:|---:|---:|---:|---:|
| Tier 1 only (deterministic) | 31.7s | 17 | 0 | 1 | 18 |
| Full `--include-llm` (all tiers) | 819s (13.7 min) | 26 | 1 | 3 | 30 |

PASS = `actual_p95 <= budget_p95`; WARN = up to 1.5× budget; FAIL = over
1.5× budget. Runner exits non-zero on any FAIL.

## Tier 1 — deterministic

Forces `OpenAIService.is_available()` to False so the LLM-first parsers
(resume parser, JD parser, `/analyze` deterministic, resume-builder
commit/structuring) actually take their deterministic-fallback path.
Without that, "deterministic" Tier 1 scenarios were 6-28s p95 because
the failed LLM call dominated the fallback wall-clock.

| Scenario | cold | p50 | p95 | budget95 | status |
|---|---:|---:|---:|---:|:---:|
| GET /api/health | 8ms | 2ms | 3ms | 100ms | PASS |
| POST /api/jobs/search (cached, simple) | 8.79s | 707ms | 5.23s | 1.5s | **FAIL** |
| POST /api/jobs/search (cached, with filters) | 617ms | 396ms | 6.16s | 2.0s | **FAIL** |
| POST /api/workspace/resume/upload (TXT) | 36ms | 27ms | 31ms | 1.5s | PASS |
| POST /api/workspace/job-description/upload (TXT) | 48ms | 46ms | 47ms | 1.5s | PASS |
| POST /api/workspace/analyze (deterministic) | 58ms | 56ms | 56ms | 1.5s | PASS |
| POST /api/workspace/analyze-jobs (start) | 5ms | 3ms | 4ms | 200ms | PASS |
| GET /api/workspace/analyze-jobs/{id} (poll) | 3ms | 2ms | 3ms | 200ms | PASS |
| POST /api/workspace/resume-builder/start | 3ms | 3ms | 3ms | 500ms | PASS |
| POST /api/workspace/resume-builder/commit | — | 17ms | 17ms | 1.0s | PASS |
| POST /api/workspace/resume-builder/export (DOCX) | 39ms | 36ms | 50ms | 600ms | PASS |
| POST /api/workspace/resume-builder/export (PDF) | 760ms | 92ms | 195ms | 4.0s | PASS |
| POST /api/workspace/artifacts/export (DOCX) | 54ms | 55ms | 85ms | 600ms | PASS |
| POST /api/workspace/artifacts/export (PDF) | 119ms | 105ms | 110ms | 4.0s | PASS |
| POST /api/workspace/artifacts/preview (resume HTML) | 7ms | 6ms | 10ms | 500ms | PASS |
| POST /api/workspace/save (auth + persistence mocked) | 5ms | 4ms | 5ms | 1.5s | PASS |
| GET /api/workspace/saved (auth + load mocked) | 4ms | 3ms | 3ms | 2.0s | PASS |
| GET /api/workspace/saved-jobs (auth + list mocked) | 4ms | 3ms | 3ms | 1.5s | PASS |

`/jobs/search?live=true` is gated behind `--include-live` and was not
exercised here.

## Tier 2 — LLM (single calls)

| Scenario | cold | p50 | p95 | budget95 | status |
|---|---:|---:|---:|---:|:---:|
| POST /api/workspace/resume/upload (LLM hybrid) | 8.71s | 8.81s | 9.92s | 12.0s | PASS |
| POST /api/workspace/resume-builder/message (LLM) | 2.73s | 1.54s | 1.57s | 5.0s | PASS |
| POST /api/workspace/resume-builder/generate | 9.53s | 3ms | 4ms | 20.0s | PASS |
| POST /api/workspace/assistant/answer (LLM, sync) | 3.24s | 3.44s | 3.44s | 6.0s | PASS |
| POST /api/workspace/assistant/answer/stream (TTFT) | 3.17s | 2.96s | 3.19s | 2.5s | **WARN** |
| POST /api/workspace/assistant/answer/stream (total) | 3.17s | 3.31s | 5.50s | 10.0s | PASS |
| POST /api/workspace/analyze (assisted, full chain) | 93.01s | 106.01s | 106.01s | 120.0s | PASS |

Note on resume-builder/generate: warm samples (3-4ms) hit the
`structuring_signature` cache. Cold sample (9.53s) is the actual first
LLM-driven structuring + render. The cache means the warm budget is
structurally easy; the cold metric is the meaningful one.

## Tier 3 — per-agent isolation + full orchestrator

| Scenario | cold | p50 | p95 | budget95 | status |
|---|---:|---:|---:|---:|:---:|
| TailoringAgent (isolated, mid-trust mini) | 6.65s | 11.53s | 12.25s | 15.0s | PASS |
| ReviewAgent (isolated, high-trust) | 44.71s | 11.08s | 32.00s | 18.0s | **FAIL** |
| ResumeGenerationAgent (isolated, high-trust) | 61.80s | 13.95s | 17.09s | 20.0s | PASS |
| CoverLetterAgent (isolated, high-trust) | 33.33s | 12.64s | 15.94s | 18.0s | PASS |
| Full orchestrator chain (4 agents in sequence) | 74.13s | 60.97s | 60.97s | 70.0s | PASS |

## FAILs and the WARN — what's actually going on

### `/jobs/search` cached (simple + filtered) — both FAIL

p95 of 5.23s and 6.16s vs budgets of 1.5s and 2.0s. This is real Supabase
latency, not a runner artifact: the `cached_jobs` table is ~8.7K active
rows and the simple query (`engineer`) full-text-matches a large slice.
The "with filters" variant returned 6.16s because of run-time variance;
on the Tier-1-only run earlier it landed at 638ms (PASS) — the upper
percentile is bursty.

Three plausible directions:

1. Tighten the budget — accept that broad full-text queries on this
   cache size are a few seconds.
2. Tighten the query — paginate, or cap the response payload size.
3. Investigate the underlying postgres query plan — the `cached_jobs`
   FTS may benefit from a different index strategy.

Cold for the simple query was 8.79s — first Supabase HTTP-client init
plus first FTS query. This is one-shot per worker startup so not a hot
issue, but it's why the cold/warm split matters.

### `assistant/answer/stream` TTFT — WARN

p95 of 3.19s vs 2.5s budget. Within the FAIL threshold (1.5× = 3.75s)
but clearly slow. The `meta` event fires synchronously before the LLM
call, so TTFT here measures time-to-first-`delta`, which depends on the
model, not on SSE plumbing. The plan's caveat about TestClient SSE
being optimistic vs prod doesn't help when the LLM itself is slow on
the first chunk.

If reproduced consistently, either:

- Loosen the budget to 3.5s (matches what mini gives us in practice).
- Use a faster model for the streaming assistant path.

### `ReviewAgent` isolated — FAIL

p95 of 32.0s vs 18.0s budget, on N=2 warm samples. p50 of 11.08s is
fine. With N=2 the p95 is just `max(samples)`, so the 32s reflects a
single slow run. Cold was 44.71s.

ReviewAgent is high-trust gpt-5.4 with reasoning=high; high variance is
expected. Three options:

1. Bump Tier 3 N=5 to smooth p95 variance (costs another ~$1 per run).
2. Loosen budget to ~35s p95 to match the natural variance.
3. Accept the FAIL as signal that ReviewAgent's reasoning=high tail is
   genuinely long, and watch for regressions.

Worth noting that the full orchestrator chain (which includes
ReviewAgent) still came in at 60.97s p95 vs 70s budget, so the chain
absorbs Review's variance without breaking the end-to-end SLO.

## Caveats

- **Cold metrics are noisy** (single shot per scenario). Tier 3 cold
  values of 33-74s reflect first-request overhead — Python imports,
  OpenAI HTTP-client setup, FastAPI router lookup table — not steady-
  state behavior. Plan flags this; we accept it as a sanity check, not
  a budget gate.
- **TestClient is in-process.** No network round-trip between client
  and server. Real production adds 50-200ms of network on every call.
  Stream TTFT in particular will be slightly different in prod, where
  Caddy's `flush_interval -1` and `X-Accel-Buffering: no` matter.
- **Persistence is mocked.** `SavedWorkspaceStore`, `SavedJobsStore`,
  `ResumeBuilderStore`, and `CachedJobsStore.get_listing_status_map`
  are stubbed. The auth `resolve_authenticated_context` is faked. That
  means `/save`, `/saved`, `/saved-jobs` measure routing+serialization
  cost only — real Supabase round-trip would add 100-400ms each.
- **`cached_jobs` reads are NOT mocked.** Tier 1 `/jobs/search` is the
  one place we hit real Supabase; that's why the FAIL p95 of 5-6s
  showed up.
- **Rate limit overridden** at process start (`RATE_LIMIT_OVERRIDE=
  100000/minute`). Production rate limits will reject under burst.
- **`/analyze-jobs` thread worker is mocked** so the spawned background
  workflow doesn't burn LLM budget under Tier 1 measurement. Latency of
  the start endpoint is just thread spawn + dict insert.

## Suggested next moves

Before merging the runner into routine use:

1. Run `python tests/quality/latency_runner.py --include-llm` a second
   time to verify warm-warm consistency. Plan target is ±20% on
   non-LLM paths between runs.
2. Decide on the `/jobs/search` budget vs perf fix.
3. Decide on Tier 3 N (currently 2): loosen budgets at N=2 or burn
   another $1/run for N=5 stability.
4. After sign-off, consider a Day-41 DEVLOG entry capturing the
   baselines for future regression comparison.

The runner is otherwise ready: it's deterministic, mockable, follows
the existing `tests/quality/*_runner.py` conventions, and produces
machine-readable scorecards under
[_last_latency_run.json](_last_latency_run.json) (gitignored).
