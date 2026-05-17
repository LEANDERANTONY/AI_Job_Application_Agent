"""ADR-028 Decision 2 — premium reasoning A/B for the ReviewAgent.

Question: premium runs `review` on gpt-5.5 @ medium (2x gpt-5.4's
token price) but never invokes gpt-5.5's deep-reasoning. Is the
upgrade worth it, and would gpt-5.5 @ high (the differentiator we're
paying for but not using) be materially better?

Three arms, all over the SAME 6 scenarios + scoring as
``review_quality_runner`` (3 clean = over-correction / false-rejection
guard; 3 adversarial = planted-fabrication detection + correction —
the grounding-catch signal that decides this):

  - baseline   : gpt-5.4 @ medium   (standard / premium-off)
  - premium_now : gpt-5.5 @ medium   (what premium pays for today)
  - premium_high: gpt-5.5 @ high     (the slice we're NOT using)

Reuses the existing ReviewAgent + scoring untouched. Résumé-parse
inputs are cached per (resume, jd) pair so we don't re-parse 6x.

Usage:
    python -m tests.quality.review_model_ab_runner --json out.json
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import src.config as _cfg
from src.agents.review_agent import ReviewAgent
from src.openai_service import OpenAIService

from tests.quality.review_quality_runner import (
    JDS_DIR,
    RESUMES_DIR,
    SCENARIOS,
    _build_inputs,
    score_scenario,
)

_ARMS = [
    {"key": "baseline", "model": None, "reasoning": "medium"},      # gpt-5.4 @ med
    {"key": "premium_now", "model": "gpt-5.5", "reasoning": "medium"},
    {"key": "premium_high", "model": "gpt-5.5", "reasoning": "high"},
]


def _inputs_cache():
    cache: dict[tuple[str, str], tuple] = {}

    def get(resume: str, jd: str):
        k = (resume, jd)
        if k not in cache:
            cache[k] = _build_inputs(RESUMES_DIR / resume, JDS_DIR / jd)
        return cache[k]

    return get


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=str, default="")
    args = parser.parse_args()

    svc = OpenAIService()
    if not svc.is_available():
        raise SystemExit("OpenAI not configured — cannot run the A/B.")

    get_inputs = _inputs_cache()
    results: dict[str, list[dict]] = {a["key"]: [] for a in _ARMS}
    started = time.perf_counter()

    for scenario in SCENARIOS:
        cp, jd, fit, draft = get_inputs(scenario["resume"], scenario["jd"])
        resume_text = (RESUMES_DIR / scenario["resume"]).read_text(encoding="utf-8")
        input_tailoring = scenario["input_tailoring"]
        for arm in _ARMS:
            # Reasoning is read live from this dict per call, so
            # mutating it between arms is sufficient (no re-import).
            _cfg.OPENAI_REASONING_ROUTING["review"] = arm["reasoning"]
            agent = ReviewAgent(svc, model_override=arm["model"])
            try:
                ro = agent.run(cp, jd, fit, draft, input_tailoring)
                scored = score_scenario(
                    scenario, ro, input_tailoring,
                    list(cp.skills), list(fit.missing_hard_skills), resume_text,
                )
            except Exception as exc:  # noqa: BLE001 - record + continue
                scored = {"overall": None, "error": f"{type(exc).__name__}: {exc}"}
            results[arm["key"]].append(
                {"label": scenario["label"], "mode": scenario["mode"], **scored}
            )
            print(
                f"{scenario['label']:<24} {arm['key']:<13} "
                f"overall={scored.get('overall')}"
            )

    # Aggregate: adversarial detection+correction is the headline;
    # clean no_false_rejection guards over-correction.
    def _avg(arm_key: str, mode: str, section: str | None) -> float | None:
        vals = []
        for r in results[arm_key]:
            if r["mode"] != mode or r.get("overall") is None:
                continue
            vals.append(
                r["overall"] if section is None
                else r["sections"][section]["score"]
            )
        return round(sum(vals) / len(vals), 3) if vals else None

    snap = svc.get_usage_snapshot()
    summary = {
        "arms": {
            a["key"]: {
                "model": a["model"] or _cfg.OPENAI_MODEL_ROUTING.get("review"),
                "reasoning": a["reasoning"],
                "adversarial_detection": _avg(a["key"], "adversarial", "detection"),
                "adversarial_correction": _avg(a["key"], "adversarial", "correction"),
                "adversarial_overall": _avg(a["key"], "adversarial", None),
                "clean_no_false_rejection": _avg(
                    a["key"], "clean", "no_false_rejection"
                ),
                "clean_overall": _avg(a["key"], "clean", None),
            }
            for a in _ARMS
        },
        "usage": {
            "requests": snap.get("request_count"),
            "total_tokens": snap.get("total_tokens"),
        },
        "elapsed_s": round(time.perf_counter() - started, 1),
        "per_scenario": results,
    }
    print("\n=== SUMMARY ===")
    print(json.dumps(summary["arms"], indent=2))
    print("usage:", summary["usage"], "elapsed_s:", summary["elapsed_s"])
    if args.json:
        Path(args.json).write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print("wrote", args.json)


if __name__ == "__main__":
    main()
