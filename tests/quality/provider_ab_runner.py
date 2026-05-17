"""ADR-028 D1 validation — OpenAI vs Kimi across the 3 core suites.

Runs the PRODUCTION entrypoints (`build_candidate_profile_from_resume_auto`,
`build_job_description_from_text_auto`, `ReviewAgent`) with each
provider injected as the `openai_service`, so the comparison is
"what a user actually gets with provider X" — including the
auto-builders' own deterministic fallback when a provider's JSON is
unusable (which the Kimi adapter's fidelity counter records instead
of letting it silently mask a weaker provider).

Suites + scoring (reused verbatim, untouched):
  - resume parser : 15 fixtures vs GOLD `expected_profiles/`
                    (`parser_quality_runner.score_profile`)
  - jd parser     : 15 fixtures vs GOLD `expected_jds/`
                    (`jd_parser_quality_runner.score_jd`)
  - analysis      : `review_quality_runner` 6 scenarios + score_scenario
                    (N=3/mode — directional; the audit flagged it
                     underpowered; the fidelity rate adds the decisive
                     provider signal here)

Constraint (operator): Kimi must be ≤ gpt-5.4@medium cost AND
latency → KimiEvalService defaults to K2.6 non-thinking. Kimi-advanced
vs gpt-5.5@high is the explicit later follow-up.

Usage (needs KIMI_API_KEY for the kimi arm; OpenAI key for baseline):
    python -m tests.quality.provider_ab_runner --suite all --json out.json
    python -m tests.quality.provider_ab_runner --suite parser --limit 4   # cheap smoke
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from src.schemas import ResumeDocument
from src.services.profile_service import build_candidate_profile_from_resume_auto
from src.services.resume_llm_parser_service import ResumeLLMParserService
from src.services.job_service import build_job_description_from_text_auto
from src.services.jd_llm_parser_service import JobDescriptionLLMParserService
from src.openai_service import OpenAIService

from tests.quality.kimi_eval_service import KimiEvalService
from tests.quality import parser_quality_runner as PQ
from tests.quality import jd_parser_quality_runner as JQ
from tests.quality import review_quality_runner as RQ


def _make_arm(name: str):
    if name == "openai":
        return OpenAIService()
    if name == "kimi":
        return KimiEvalService()
    raise SystemExit(f"unknown arm {name!r}")


def _overall(scored: dict) -> float | None:
    return scored.get("overall") if isinstance(scored, dict) else None


def _run_parser_suite(arm_svc, limit: int | None) -> list[dict]:
    rows = []
    paths = sorted(PQ.FIXTURES_DIR.glob("*.txt"))[: limit or None]
    for fp in paths:
        exp = PQ.EXPECTED_DIR / (fp.stem + ".json")
        if not exp.exists():
            continue
        expected = json.loads(exp.read_text(encoding="utf-8"))
        doc = ResumeDocument(text=fp.read_text(encoding="utf-8"),
                             filetype="TXT", source="ab")
        try:
            profile = build_candidate_profile_from_resume_auto(
                doc, parser_service=ResumeLLMParserService(openai_service=arm_svc)
            )
            rows.append({"fixture": fp.stem,
                         "overall": _overall(PQ.score_profile(profile, expected))})
        except Exception as exc:  # noqa: BLE001
            rows.append({"fixture": fp.stem, "overall": None,
                         "error": f"{type(exc).__name__}: {exc}"})
    return rows


def _run_jd_suite(arm_svc, limit: int | None) -> list[dict]:
    rows = []
    paths = sorted(JQ.FIXTURES_DIR.glob("*.txt"))[: limit or None]
    for fp in paths:
        exp = JQ.EXPECTED_DIR / (fp.stem + ".json")
        if not exp.exists():
            continue
        expected = json.loads(exp.read_text(encoding="utf-8"))
        try:
            jd = build_job_description_from_text_auto(
                fp.read_text(encoding="utf-8"),
                parser_service=JobDescriptionLLMParserService(openai_service=arm_svc),
            )
            rows.append({"fixture": fp.stem,
                         "overall": _overall(JQ.score_jd(jd, expected))})
        except Exception as exc:  # noqa: BLE001
            rows.append({"fixture": fp.stem, "overall": None,
                         "error": f"{type(exc).__name__}: {exc}"})
    return rows


def _run_analysis_suite(arm_svc, limit: int | None) -> list[dict]:
    from src.agents.review_agent import ReviewAgent

    rows = []
    cache: dict[tuple, tuple] = {}
    scenarios = RQ.SCENARIOS[: limit or None]
    for sc in scenarios:
        key = (sc["resume"], sc["jd"])
        if key not in cache:
            cache[key] = RQ._build_inputs(
                RQ.RESUMES_DIR / sc["resume"], RQ.JDS_DIR / sc["jd"]
            )
        cp, jd, fit, draft = cache[key]
        resume_text = (RQ.RESUMES_DIR / sc["resume"]).read_text(encoding="utf-8")
        it = sc["input_tailoring"]
        try:
            ro = ReviewAgent(openai_service=arm_svc).run(cp, jd, fit, draft, it)
            scored = RQ.score_scenario(sc, ro, it, list(cp.skills),
                                       list(fit.missing_hard_skills), resume_text)
            rows.append({"fixture": sc["label"], "mode": sc["mode"],
                         "overall": scored["overall"],
                         "sections": {k: v["score"]
                                      for k, v in scored["sections"].items()}})
        except Exception as exc:  # noqa: BLE001
            rows.append({"fixture": sc["label"], "mode": sc["mode"],
                         "overall": None, "error": f"{type(exc).__name__}: {exc}"})
    return rows


_SUITES = {"parser": _run_parser_suite, "jd": _run_jd_suite,
           "analysis": _run_analysis_suite}


def _avg(rows: list[dict]) -> float | None:
    vals = [r["overall"] for r in rows if r.get("overall") is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--suite", choices=["all", *_SUITES], default="all")
    ap.add_argument("--arms", default="openai,kimi",
                    help="comma list; subset of openai,kimi")
    ap.add_argument("--limit", type=int, default=0, help="cap fixtures/suite (0=all)")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    suites = list(_SUITES) if args.suite == "all" else [args.suite]
    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    limit = args.limit or None
    started = time.perf_counter()

    result: dict[str, dict] = {}
    for arm in arms:
        svc = _make_arm(arm)
        if not svc.is_available():
            print(f"SKIP arm {arm}: service not configured "
                  f"({'KIMI_API_KEY' if arm == 'kimi' else 'OPENAI key'})")
            continue
        result[arm] = {"suites": {}}
        for s in suites:
            rows = _SUITES[s](svc, limit)
            result[arm]["suites"][s] = {"avg_overall": _avg(rows), "rows": rows}
            print(f"[{arm}] {s:<9} avg_overall={_avg(rows)} (n={len(rows)})")
        snap = svc.get_usage_snapshot()
        result[arm]["usage"] = {k: snap.get(k) for k in
                                ("request_count", "total_tokens")}
        if hasattr(svc, "get_fidelity_report"):
            result[arm]["fidelity"] = svc.get_fidelity_report()

    # Side-by-side summary + the decisive fidelity column for kimi.
    print("\n=== SUMMARY (avg_overall) ===")
    for s in suites:
        cells = " | ".join(
            f"{a}={result.get(a, {}).get('suites', {}).get(s, {}).get('avg_overall')}"
            for a in arms if a in result
        )
        print(f"  {s:<9} {cells}")
    if "kimi" in result and result["kimi"].get("fidelity"):
        print("\n=== KIMI provider fidelity (usable_rate = valid+schema, no fallback) ===")
        for task, f in result["kimi"]["fidelity"].items():
            print(f"  {task:<14} usable_rate={f['usable_rate']} "
                  f"(calls={f['calls']} content_failures={f['content_failures']} "
                  f"truncated={f['truncated']})")
    summary = {"result": result,
               "elapsed_s": round(time.perf_counter() - started, 1)}
    if args.json:
        Path(args.json).write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print("wrote", args.json)


if __name__ == "__main__":
    main()
