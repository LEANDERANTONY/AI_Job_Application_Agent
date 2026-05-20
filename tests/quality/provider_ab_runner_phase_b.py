"""Phase B comprehensive multi-provider eval — parser + JD + analysis
across the 3-candidate Phase A shortlist, all routed through OpenRouter.

Phase A (resume-builder agentic eval, Slice 1G+1H) settled the
INTERACTIVE-CHAT question: gpt-5.4 stays default; Sonnet 4.5 is the
sole interactive failover candidate. Phase B answers the OTHER half:
can DeepSeek (the cost-efficient batch candidate) and Sonnet 4.5 carry
the parser / JD-parser / agentic-analysis tasks too, where latency
matters less and structured-output fidelity matters most?

Candidates (all via OpenRouter for transport-fair comparison —
proxy overhead measured at ~0s in Slice 1H so no fairness concern):

    openai-via-or  =  openai/gpt-5.4              (baseline)
    sonnet-4.5     =  anthropic/claude-sonnet-4.5
    deepseek       =  deepseek/deepseek-v4-pro

Suites (reuses scoring + fixtures from the existing quality runners):

    parser    — 10 resume-fixture gold profiles  (tests/quality/expected_profiles/)
    jd        — 10 JD-fixture gold parses        (tests/quality/expected_jds/)
    analysis  — 10 scenarios × full agentic chain
                (tailoring → review → resume_generation → cover_letter)

Per-task metrics captured (matches the Slice 1H pattern):

    - latency_seconds  : wall-clock per fixture
    - prompt_tokens    : input tokens consumed (KimiEvalService delta)
    - completion_tokens
    - total_tokens
    - cost_usd         : tokens × per-model pricing
    - fidelity         : valid_json / schema_ok / truncated /
                         content_failures (KimiEvalService tracks per task)

Defensive engineering (lessons baked in from Slice 1G/1H):

    - Incremental JSON checkpoint after EVERY (candidate, suite)
      completes — partial results survive any mid-run failure
    - `flush=True` heartbeat per fixture — `tail -f` watchable
    - OpenRouter timeout=60s, max_retries=0 — a hung provider doesn't
      lock the matrix (set on KimiEvalService construction below)
    - Structuring max_tokens bumped via env var to 6000 (Slice 1G
      finding — 4000 truncates the 11K-prompt structuring call)
    - Fence-tolerant JSON parser in KimiEvalService (Slice 1G+1I fix
      — Anthropic models wrap JSON in markdown without honoring
      response_format=json_object)

Cost budget for the full run (3 candidates × ~10 fixtures × 3 suites):

    openai/gpt-5.4         ~$3.00
    anthropic/sonnet-4.5   ~$4.00
    deepseek/v4-pro        ~$0.60
    ----------------------------
    total                  ~$7.60   (well under the $30 operator budget)

USAGE:
    python tests/quality/provider_ab_runner_phase_b.py
    python tests/quality/provider_ab_runner_phase_b.py --smoke
    python tests/quality/provider_ab_runner_phase_b.py --candidates openai-via-or,sonnet-4.5
    python tests/quality/provider_ab_runner_phase_b.py --suite parser --limit 3
    python tests/quality/provider_ab_runner_phase_b.py --json out.json
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Bump structuring output budget BEFORE importing src.config — see
# Slice 1G finding (the 11K-char structuring prompt truncates at the
# default 4000 token budget; 6000 gives the worst-case full output
# headroom).
os.environ.setdefault(
    "OPENAI_MAX_COMPLETION_TOKENS_RESUME_BUILDER_STRUCTURING", "6000"
)

# Reuse the suite implementations from the existing runner — they're
# good as-is; we wrap them with metrics capture below.
import tests.quality.jd_parser_quality_runner as JQ  # noqa: E402
import tests.quality.parser_quality_runner as PQ  # noqa: E402
import tests.quality.review_quality_runner as RQ  # noqa: E402
from tests.quality.kimi_eval_service import KimiEvalService  # noqa: E402
from tests.quality.provider_pricing import estimate_cost_usd  # noqa: E402
from src.schemas import ResumeDocument  # noqa: E402
from src.services.job_service import build_job_description_from_text_auto  # noqa: E402
from src.services.profile_service import build_candidate_profile_from_resume_auto  # noqa: E402
from src.services.resume_llm_parser_service import ResumeLLMParserService  # noqa: E402
from src.services.jd_llm_parser_service import JobDescriptionLLMParserService  # noqa: E402


# ---------------------------------------------------------------------------
# Phase B candidate slate. All three go through OpenRouter Chat
# Completions; this keeps the comparison apples-to-apples (no native-
# vs-proxy confound). The gpt-5.4 baseline-via-OpenRouter slug was
# verified working in Slice 1H. Slugs are kept in sync with
# report.md §4 + tests/quality/provider_pricing.py.
# ---------------------------------------------------------------------------

_PHASE_B_CANDIDATES: dict[str, str] = {
    "openai-via-or": "openai/gpt-5.4",
    "sonnet-4.5": "anthropic/claude-sonnet-4.5",
    "deepseek": "deepseek/deepseek-v4-pro",
}

_OPENROUTER_BASE = os.getenv(
    "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
).strip()


def _build_service(slug: str) -> KimiEvalService:
    """Build a KimiEvalService bound to a specific OpenRouter slug.

    The KimiEvalService name is historical — Slice 1I extended it to
    parse markdown-fenced JSON, so it now correctly handles Anthropic
    + Gemini + DeepSeek responses, not just Kimi.
    """
    return KimiEvalService(
        api_key=os.getenv("OPENROUTER_API_KEY", ""),
        base_url=_OPENROUTER_BASE,
        model=slug,
    )


def _usage_snapshot(svc: Any) -> dict[str, int]:
    """Return cumulative ``{prompt, completion, total}`` from the service."""
    try:
        snap = svc.get_usage_snapshot() or {}
    except Exception:
        snap = {}
    return {
        "prompt": int(snap.get("prompt_tokens", 0) or 0),
        "completion": int(snap.get("completion_tokens", 0) or 0),
        "total": int(snap.get("total_tokens", 0) or 0),
    }


def _overall(scored: dict | None) -> float | None:
    return scored.get("overall") if isinstance(scored, dict) else None


# ---------------------------------------------------------------------------
# Suite implementations — each iterates the suite's gold fixtures and
# returns a list of per-fixture result rows. Per-fixture metrics
# (latency, token delta, cost) are computed at the runner layer
# below, so the suite code only needs to return a fixture-level
# pass/fail signal.
# ---------------------------------------------------------------------------


def _run_parser_fixture(svc: Any, fixture_path: Path, expected: dict) -> dict:
    doc = ResumeDocument(
        text=fixture_path.read_text(encoding="utf-8"),
        filetype="TXT",
        source="ab",
    )
    profile = build_candidate_profile_from_resume_auto(
        doc, parser_service=ResumeLLMParserService(openai_service=svc)
    )
    scored = PQ.score_profile(profile, expected)
    return {"fixture": fixture_path.stem, "overall": _overall(scored)}


def _run_jd_fixture(svc: Any, fixture_path: Path, expected: dict) -> dict:
    jd = build_job_description_from_text_auto(
        fixture_path.read_text(encoding="utf-8"),
        parser_service=JobDescriptionLLMParserService(openai_service=svc),
    )
    scored = JQ.score_jd(jd, expected)
    return {"fixture": fixture_path.stem, "overall": _overall(scored)}


def _run_analysis_fixture(svc: Any, sc: dict, cache: dict) -> dict:
    """Run the full agentic chain (tailoring + review) for one scenario."""
    from src.agents.review_agent import ReviewAgent

    key = (sc["resume"], sc["jd"])
    if key not in cache:
        cache[key] = RQ._build_inputs(
            RQ.RESUMES_DIR / sc["resume"], RQ.JDS_DIR / sc["jd"]
        )
    cp, jd, fit, draft = cache[key]
    resume_text = (RQ.RESUMES_DIR / sc["resume"]).read_text(encoding="utf-8")
    it = sc["input_tailoring"]
    ro = ReviewAgent(openai_service=svc).run(cp, jd, fit, draft, it)
    scored = RQ.score_scenario(
        sc, ro, it, list(cp.skills), list(fit.missing_hard_skills), resume_text
    )
    return {
        "fixture": sc["label"],
        "mode": sc["mode"],
        "overall": scored["overall"],
        "sections": {k: v["score"] for k, v in scored["sections"].items()},
    }


def _iter_suite(suite_name: str, limit: int | None):
    """Yield (fixture_id, callable[svc] -> result_row) pairs for a suite.

    The callable is what does the actual LLM-driven work for one
    fixture; the runner wraps it with metrics capture.
    """
    if suite_name == "parser":
        paths = sorted(PQ.FIXTURES_DIR.glob("*.txt"))[: limit or None]
        for fp in paths:
            exp = PQ.EXPECTED_DIR / (fp.stem + ".json")
            if not exp.exists():
                continue
            expected = json.loads(exp.read_text(encoding="utf-8"))
            yield (fp.stem, lambda svc, _fp=fp, _exp=expected: _run_parser_fixture(svc, _fp, _exp))
    elif suite_name == "jd":
        paths = sorted(JQ.FIXTURES_DIR.glob("*.txt"))[: limit or None]
        for fp in paths:
            exp = JQ.EXPECTED_DIR / (fp.stem + ".json")
            if not exp.exists():
                continue
            expected = json.loads(exp.read_text(encoding="utf-8"))
            yield (fp.stem, lambda svc, _fp=fp, _exp=expected: _run_jd_fixture(svc, _fp, _exp))
    elif suite_name == "analysis":
        cache: dict = {}
        for sc in RQ.SCENARIOS[: limit or None]:
            yield (sc["label"], lambda svc, _sc=sc, _cache=cache: _run_analysis_fixture(svc, _sc, _cache))
    else:
        raise SystemExit(f"unknown suite: {suite_name!r}")


# ---------------------------------------------------------------------------
# main — orchestrate (candidate × suite × fixtures) with metrics +
# checkpoint after each (candidate, suite) pair.
# ---------------------------------------------------------------------------


def _run_candidate_suite(
    candidate: str,
    slug: str,
    svc: Any,
    suite: str,
    limit: int | None,
) -> dict:
    """Run one (candidate, suite) cell with per-fixture metrics.

    Returns ``{rows: [...], totals: {...}}``. ``totals`` aggregates
    avg_overall + total tokens / cost / latency.
    """
    print(
        f"\n--- {candidate} ({slug}) :: suite={suite} ---",
        flush=True,
    )
    rows: list[dict] = []
    suite_start = time.perf_counter()
    for fixture_id, run_fn in _iter_suite(suite, limit):
        snap_before = _usage_snapshot(svc)
        started_at = time.perf_counter()
        error: str | None = None
        result: dict[str, Any] = {"fixture": fixture_id, "overall": None}
        try:
            result = run_fn(svc)
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
            result = {"fixture": fixture_id, "overall": None, "error": error}
        elapsed = time.perf_counter() - started_at
        snap_after = _usage_snapshot(svc)
        delta_prompt = max(0, snap_after["prompt"] - snap_before["prompt"])
        delta_completion = max(0, snap_after["completion"] - snap_before["completion"])
        cost = estimate_cost_usd(slug, delta_prompt, delta_completion)
        result["metrics"] = {
            "elapsed_seconds": round(elapsed, 2),
            "prompt_tokens": delta_prompt,
            "completion_tokens": delta_completion,
            "total_tokens": delta_prompt + delta_completion,
            "cost_usd": round(cost, 4),
        }
        # Heartbeat — one line per fixture, tail-f-friendly.
        score_str = (
            f"{result.get('overall'):.3f}"
            if isinstance(result.get("overall"), (int, float))
            else "—"
        )
        print(
            f"  [{fixture_id}] score={score_str:<6} | "
            f"{elapsed:>6.2f}s | {delta_prompt + delta_completion:>6} tok | "
            f"${cost:>6.4f}"
            + (f"  ERROR: {error[:80]}" if error else ""),
            flush=True,
        )
        rows.append(result)

    overall_values = [r["overall"] for r in rows if isinstance(r.get("overall"), (int, float))]
    suite_elapsed = time.perf_counter() - suite_start
    totals = {
        "fixtures": len(rows),
        "scored": len(overall_values),
        "avg_overall": round(sum(overall_values) / len(overall_values), 3)
        if overall_values
        else None,
        "min_overall": round(min(overall_values), 3) if overall_values else None,
        "total_seconds": round(suite_elapsed, 2),
        "total_tokens": sum(r["metrics"]["total_tokens"] for r in rows),
        "total_cost_usd": round(
            sum(r["metrics"]["cost_usd"] for r in rows), 4
        ),
    }
    print(
        f"  ===> {candidate} :: {suite} done — "
        f"avg={totals['avg_overall']} ({len(overall_values)}/{len(rows)} scored), "
        f"{totals['total_seconds']}s, "
        f"{totals['total_tokens']} tok, "
        f"${totals['total_cost_usd']}",
        flush=True,
    )
    return {"rows": rows, "totals": totals}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        choices=["all", "parser", "jd", "analysis"],
        default="all",
        help="Which suite(s) to run. Default: all three.",
    )
    parser.add_argument(
        "--candidates",
        default="all",
        help=(
            "Comma list of candidate names from _PHASE_B_CANDIDATES "
            "(openai-via-or, sonnet-4.5, deepseek), or 'all'. Default: all."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Cap fixtures per suite (0 = all). Useful for smoke runs.",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Alias for --suite parser --limit 2 (cheap end-to-end sanity).",
    )
    parser.add_argument("--json", default="", help="Path to write the full JSON report.")
    args = parser.parse_args()

    if args.smoke:
        args.suite, args.limit = "parser", 2

    suites = ["parser", "jd", "analysis"] if args.suite == "all" else [args.suite]
    limit = args.limit or None

    if args.candidates == "all":
        candidates = list(_PHASE_B_CANDIDATES)
    else:
        candidates = [c.strip() for c in args.candidates.split(",") if c.strip()]
    unknown = [c for c in candidates if c not in _PHASE_B_CANDIDATES]
    if unknown:
        raise SystemExit(
            f"Unknown candidate(s): {unknown}. Known: {sorted(_PHASE_B_CANDIDATES)}"
        )

    if not os.getenv("OPENROUTER_API_KEY", "").strip():
        raise SystemExit(
            "OPENROUTER_API_KEY not set. Phase B routes every candidate "
            "through OpenRouter, so this is required."
        )

    print(
        f"== Phase B eval: {len(candidates)} candidate(s) × {len(suites)} suite(s)"
        f"{f' (limit={limit})' if limit else ''} ==",
        flush=True,
    )
    print(f"   candidates: {candidates}")
    print(f"   suites:     {suites}")

    started_at = time.perf_counter()
    report: dict[str, Any] = {
        "candidates": {c: _PHASE_B_CANDIDATES[c] for c in candidates},
        "suites": suites,
        "limit": limit,
        "results": {},
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    for candidate in candidates:
        slug = _PHASE_B_CANDIDATES[candidate]
        svc = _build_service(slug)
        if not svc.is_available():
            print(
                f"SKIP {candidate}: OPENROUTER_API_KEY missing or invalid.",
                flush=True,
            )
            continue
        report["results"][candidate] = {"slug": slug, "suites": {}}
        for suite in suites:
            cell = _run_candidate_suite(candidate, slug, svc, suite, limit)
            report["results"][candidate]["suites"][suite] = cell

            # Slice 1H pattern — incremental checkpoint after every
            # (candidate, suite) so a mid-run failure can't lose
            # everything. The file is overwritten so the most recent
            # state is always one read away.
            if args.json:
                ck = dict(report)
                ck["checkpoint_at"] = datetime.datetime.now(
                    datetime.timezone.utc
                ).isoformat()
                ck["checkpoint_after"] = f"{candidate}/{suite}"
                with open(args.json, "w", encoding="utf-8") as fh:
                    json.dump(ck, fh, indent=2)
                print(
                    f"  [checkpoint] wrote partial results to {args.json}",
                    flush=True,
                )

        # Per-candidate fidelity roll-up. The fidelity report is the
        # decisive provider metric for parser/JD/analysis — it tells
        # us how often the model returned valid+schema-OK JSON without
        # silently triggering the deterministic fallback.
        if hasattr(svc, "get_fidelity_report"):
            report["results"][candidate]["fidelity"] = svc.get_fidelity_report()

        if hasattr(svc, "get_usage_snapshot"):
            snap = svc.get_usage_snapshot() or {}
            report["results"][candidate]["usage_snapshot"] = {
                k: snap.get(k)
                for k in ("request_count", "prompt_tokens", "completion_tokens", "total_tokens")
            }

    report["elapsed_seconds"] = round(time.perf_counter() - started_at, 1)
    report["completed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # Final comparison table.
    print()
    print("=" * 90)
    print(" PHASE B SUMMARY — avg_overall by candidate × suite ".center(90, "="))
    print("=" * 90)
    name_w = 12
    col_w = 18
    header = "suite".ljust(name_w) + "".join(c.ljust(col_w) for c in candidates)
    print(header)
    print("-" * len(header))
    for suite in suites:
        row = suite.ljust(name_w)
        for cand in candidates:
            cell = (
                report["results"]
                .get(cand, {})
                .get("suites", {})
                .get(suite, {})
                .get("totals", {})
            )
            avg = cell.get("avg_overall")
            total_cost = cell.get("total_cost_usd")
            cell_str = (
                f"{avg if avg is not None else '—':<6}"
                f" ${total_cost or 0:.3f}"
            )
            row += cell_str.ljust(col_w)
        print(row)

    # Provider fidelity roll-up (the "did the model produce usable
    # structured output?" metric).
    print()
    print(" PROVIDER FIDELITY — worst-task usable_rate (gates ADR-028 D1) ".center(90, "="))
    for cand in candidates:
        fid = report["results"].get(cand, {}).get("fidelity") or {}
        if not fid:
            continue
        rates = [
            v.get("usable_rate")
            for v in fid.values()
            if v.get("usable_rate") is not None
        ]
        worst = min(rates) if rates else None
        per_task = "  ".join(
            f"{t}={v.get('usable_rate', '—')}" for t, v in fid.items()
        )
        print(f"  {cand:<14} worst={worst}   {per_task}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
        print(f"\nwrote JSON report -> {args.json}", flush=True)

    print(f"\nTotal wall time: {report['elapsed_seconds']}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
