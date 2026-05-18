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


_OPENROUTER_BASE = "https://openrouter.ai/api/v1"

# Shortlisted from the May-2026 field (not Kimi-specific). Slugs are
# BEST-EFFORT — OpenRouter's catalog churns; VERIFY at
# https://openrouter.ai/models and override with --model-map or env
# CANDIDATE_MODEL_MAP (JSON) without touching code. `--preflight`
# makes one ~$0.001 call/candidate to catch a wrong slug BEFORE the
# expensive run. `openai` is the special baseline (real product
# OpenAIService, not via OpenRouter).
_CANDIDATES: dict[str, str] = {
    "gemini": "google/gemini-3.1-pro",       # ~57 AA index, $2/$12, US
    "kimi": "moonshotai/kimi-k2.6",          # ~54, $0.95, China
    "glm": "z-ai/glm-5.1",                   # #1 open-weight SWE-bench, China
    "deepseek": "deepseek/deepseek-v4",      # strong reasoning, very cheap, China
    "grok": "x-ai/grok-4.20",                # reasoning co-leader, US
    "qwen": "qwen/qwen-3.5",                 # cheap, China
}


def _resolve_model_map(cli_map: str) -> dict[str, str]:
    import os
    m = dict(_CANDIDATES)
    env = os.getenv("CANDIDATE_MODEL_MAP", "").strip()
    if env:
        m.update(json.loads(env))
    for pair in (cli_map or "").split(","):
        pair = pair.strip()
        if "=" in pair:
            k, v = pair.split("=", 1)
            m[k.strip()] = v.strip()
    return m


def _make_arm(name: str, model_map: dict[str, str]):
    import os
    if name == "openai":
        return OpenAIService()  # baseline = real product config
    if name not in model_map:
        raise SystemExit(f"unknown candidate {name!r} (known: {sorted(model_map)})")
    # Every non-baseline candidate goes through the OpenRouter
    # chat-completions adapter — one OPENROUTER_API_KEY, swap model id.
    return KimiEvalService(
        api_key=os.getenv("OPENROUTER_API_KEY", ""),
        base_url=_OPENROUTER_BASE,
        model=model_map[name],
    )


def _preflight(name: str, svc) -> tuple[bool, str]:
    """One tiny call to confirm the slug/key resolve before spending
    real eval budget. Returns (ok, detail)."""
    try:
        svc.run_json_prompt(
            'Reply with JSON {"ok": true} and nothing else.',
            "ping",
            expected_keys=["ok"],
            task_name="preflight",
            max_completion_tokens=20,
        )
        return True, "ok"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {str(exc)[:160]}"


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
    ap.add_argument(
        "--candidates", default="all",
        help="'all' (= openai baseline + the 6) or a comma list, "
        "e.g. openai,gemini,kimi,deepseek",
    )
    ap.add_argument("--model-map", default="",
                    help="override slugs: gemini=google/gemini-3.1-pro-preview,...")
    ap.add_argument("--limit", type=int, default=0, help="cap fixtures/suite (0=all)")
    ap.add_argument("--smoke", action="store_true",
                    help="alias: --suite parser --limit 3 (cheap sanity + fidelity)")
    ap.add_argument("--preflight", action="store_true",
                    help="1 tiny call/candidate to validate slug+key before the run")
    ap.add_argument("--preflight-only", action="store_true",
                    help="just validate every slug/key (~$0.001 total) and exit; "
                    "no suites — use when credits are tight")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    if args.smoke:
        args.suite, args.limit = "parser", 3
    suites = list(_SUITES) if args.suite == "all" else [args.suite]
    model_map = _resolve_model_map(args.model_map)
    if args.candidates == "all":
        arms = ["openai", *_CANDIDATES]
    else:
        arms = [a.strip() for a in args.candidates.split(",") if a.strip()]
    limit = args.limit or None
    started = time.perf_counter()

    # Build + (optionally) preflight every selected arm first, so a
    # bad slug / missing key is caught for pennies, not mid-eval.
    live: dict[str, object] = {}
    for arm in arms:
        svc = _make_arm(arm, model_map)
        if not svc.is_available():
            need = "OPENAI key" if arm == "openai" else "OPENROUTER_API_KEY"
            print(f"SKIP {arm}: not configured ({need})")
            continue
        if args.preflight and arm != "openai":
            ok, detail = _preflight(arm, svc)
            tag = model_map.get(arm, "?")
            print(f"[preflight] {arm:<9} {tag:<32} {'OK' if ok else 'FAIL: ' + detail}")
            if not ok:
                continue
        live[arm] = svc
    if not live:
        raise SystemExit("No usable arms (set OPENROUTER_API_KEY / OPENAI key).")

    result: dict[str, dict] = {}
    for arm, svc in live.items():
        result[arm] = {"model": ("(product)" if arm == "openai"
                                 else model_map.get(arm)), "suites": {}}
        for s in suites:
            rows = _SUITES[s](svc, limit)
            result[arm]["suites"][s] = {"avg_overall": _avg(rows), "rows": rows}
            print(f"[{arm}] {s:<9} avg_overall={_avg(rows)} (n={len(rows)})")
        snap = svc.get_usage_snapshot()
        result[arm]["usage"] = {k: snap.get(k) for k in
                                ("request_count", "total_tokens")}
        if hasattr(svc, "get_fidelity_report"):
            result[arm]["fidelity"] = svc.get_fidelity_report()

    order = [a for a in arms if a in result]
    print("\n=== SUMMARY: avg_overall (gold-standard score; higher=better) ===")
    head = "  " + "suite".ljust(10) + "".join(a.ljust(14) for a in order)
    print(head)
    for s in suites:
        line = "  " + s.ljust(10)
        for a in order:
            v = result[a]["suites"].get(s, {}).get("avg_overall")
            line += (str(v) if v is not None else "—").ljust(14)
        print(line)
    print("\n=== provider fidelity — usable_rate (valid+schema, NO deterministic "
          "fallback); the decisive provider metric ===")
    for a in order:
        if a == "openai" or not result[a].get("fidelity"):
            continue
        worst = min((f["usable_rate"] for f in result[a]["fidelity"].values()
                     if f.get("usable_rate") is not None), default=None)
        print(f"  {a:<9} worst_task_usable_rate={worst}  "
              + " ".join(f"{t}={f['usable_rate']}"
                         for t, f in result[a]["fidelity"].items()))
    summary = {"result": result, "model_map": model_map,
               "elapsed_s": round(time.perf_counter() - started, 1)}
    if args.json:
        Path(args.json).write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print("wrote", args.json)


if __name__ == "__main__":
    main()
