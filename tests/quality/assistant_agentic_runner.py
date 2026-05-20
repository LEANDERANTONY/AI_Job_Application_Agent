"""Slice 1K — multi-provider eval for the WORKSPACE ASSISTANT prompt.

This is the assistant-surface counterpart to Phase A's resume-builder
runner (``resume_builder_agentic_runner.py``) and Phase B's parser /
JD / analysis runner (``provider_ab_runner_phase_b.py``). The assistant
is a different prompt surface with different failure modes than either:

  * Resume builder: tool-using conversational intake. Failure shows up
    as missed proactive offers, blown follow-ups, fabricated profile
    fields.
  * Phase B suites: single-shot structured extraction. Failure shows
    up as fidelity (valid_json / schema_ok / truncated).
  * Workspace assistant: short-turn Q&A grounded on a runtime workspace
    snapshot + freshly added product knowledge. Failure shows up as
    hallucinated quotas/themes, mid-session memory loss (Slice 1J was
    the patch), refusing to answer in-scope questions, or answering
    out-of-scope ones it should refuse.

Candidate slate (5 — user-approved after dropping Opus + substituting
o4-mini for the non-existent gpt-5.1-mini):

    gpt-5.4@med       =  openai/gpt-5.4              + reasoning_effort=medium
    gpt-5.4-mini@med  =  openai/gpt-5.4-mini         + reasoning_effort=medium
    o4-mini@high      =  openai/o4-mini              + reasoning_effort=high
    sonnet-4.5        =  anthropic/claude-sonnet-4.5 + (no extended thinking)
    haiku-4.5         =  anthropic/claude-haiku-4.5  + (no extended thinking)

All five routed through OpenRouter for transport-fair comparison
(Slice 1H proved the OpenRouter proxy overhead is ~0s vs OpenAI
native, so the latency gap between gpt-5.4 and the others is real
model time).

Scenarios (12 — assistant-specific failure modes):

  1.  pricing_tiers_question         — must name Free/Pro/Business + numbers
  2.  theme_list_question            — must enumerate at least 3 of 6 themes
  3.  theme_unlock_question          — must explain two-column gating
  4.  quota_assistant_turns          — must give 20/150/500 numbers
  5.  quota_resume_builder_lifetime  — must say Free is LIFETIME, not monthly
  6.  refuse_schedule_interview      — must decline; no fake confirmation
  7.  refuse_login_external          — must decline LinkedIn login
  8.  pre_resume_grounding           — has_resume=false; must NOT invent skills
  9.  post_analysis_grounding        — has_analysis=true; must use fit score
  10. off_topic_movie                — must decline; no movie names leaked
  11. long_session_memory_callback   — 7-turn session, recall fact from turn 2
  12. multi_turn_correction          — must respect latest user-stated truth

Each scenario uses a tiny matcher rubric (substring positives + negatives,
case- and smart-quote-normalized; same pattern as Slice 1H/Phase B).
Matcher bugs from Slice 1H (curly apostrophe vs straight) are
normalised away in ``_normalize``.

Defensive engineering (carried from Phase B):

  * Incremental JSON checkpoint after EVERY (candidate, scenario) pair
  * ``flush=True`` heartbeat — tail-f-friendly progress
  * OpenRouterEvalService timeout=60s + max_retries=0 — hung provider
    doesn't lock the matrix
  * Adapter sends ``reasoning_effort`` through to Chat Completions for
    o-series + gpt-5.x slugs (Slice 1J'')

USAGE:
    python tests/quality/assistant_agentic_runner.py
    python tests/quality/assistant_agentic_runner.py --smoke
    python tests/quality/assistant_agentic_runner.py --candidates gpt-5.4@med
    python tests/quality/assistant_agentic_runner.py --scenario pricing_tiers_question
    python tests/quality/assistant_agentic_runner.py --json out.json
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import src.config  # noqa: F401 — side-effect import for dotenv

from src.prompts import build_assistant_prompt  # noqa: E402
from tests.quality.openrouter_eval_service import OpenRouterEvalService  # noqa: E402
from tests.quality.provider_pricing import estimate_cost_usd  # noqa: E402


# ---------------------------------------------------------------------------
# Candidate slate. The reasoning_effort field is None for non-reasoning
# slugs (Anthropic models in non-thinking mode); the eval adapter only
# forwards it when truthy (Slice 1J'').
# ---------------------------------------------------------------------------

_CANDIDATES: dict[str, dict[str, Any]] = {
    "gpt-5.4@med": {
        "slug": "openai/gpt-5.4",
        "reasoning_effort": "medium",
    },
    "gpt-5.4-mini@med": {
        "slug": "openai/gpt-5.4-mini",
        "reasoning_effort": "medium",
    },
    "o4-mini@high": {
        "slug": "openai/o4-mini",
        "reasoning_effort": "high",
    },
    "sonnet-4.5": {
        "slug": "anthropic/claude-sonnet-4.5",
        "reasoning_effort": None,
    },
    "haiku-4.5": {
        "slug": "anthropic/claude-haiku-4.5",
        "reasoning_effort": None,
    },
}


# ---------------------------------------------------------------------------
# Workspace snapshots — minimal contexts that match what
# AssistantService.build_assistant_payload would serialize. The matcher
# rubric only inspects the assistant's `answer`, so any field the
# scenarios don't probe can be left at its default.
# ---------------------------------------------------------------------------


def _ctx_empty() -> dict[str, Any]:
    """Workspace just opened — no resume, no JD, no analysis yet."""
    return {
        "current_page": "Resume",
        "product_context": {
            "workspace_state": {
                "current_step": "resume",
                "has_resume": False,
                "resume_summary": None,
                "has_jd": False,
                "jd_summary": None,
                "has_analysis": False,
                "saved_jobs_count": 0,
                "last_search_query": None,
            }
        },
    }


def _ctx_with_resume() -> dict[str, Any]:
    """Resume uploaded, sitting on Job Search step waiting for a JD."""
    return {
        "current_page": "Job Search",
        "product_context": {
            "workspace_state": {
                "current_step": "jobs",
                "has_resume": True,
                "resume_summary": {
                    "name": "Priya Sharma",
                    "location": "Bangalore",
                    "skills_count": 18,
                    "experience_entries_count": 3,
                    "has_certifications": True,
                },
                "has_jd": False,
                "jd_summary": None,
                "has_analysis": False,
                "saved_jobs_count": 4,
                "last_search_query": "ml engineer bangalore",
            }
        },
    }


def _ctx_with_analysis() -> dict[str, Any]:
    """Full pipeline complete — has_analysis is true. workflow_context
    is where the live fit score lives in production; we mirror just
    enough of its shape that the assistant can ground on it."""
    return {
        "current_page": "Analysis",
        "product_context": {
            "workspace_state": {
                "current_step": "analysis",
                "has_resume": True,
                "resume_summary": {
                    "name": "Priya Sharma",
                    "location": "Bangalore",
                    "skills_count": 18,
                    "experience_entries_count": 3,
                    "has_certifications": True,
                },
                "has_jd": True,
                "jd_summary": {
                    "title": "Senior ML Engineer",
                    "location": "Bangalore (Hybrid)",
                    "hard_skills_count": 9,
                    "soft_skills_count": 4,
                    "must_haves_count": 3,
                },
                "has_analysis": True,
                "saved_jobs_count": 4,
                "last_search_query": "ml engineer bangalore",
            }
        },
        "workflow_context": {
            "fit_analysis": {
                "target_role": "Senior ML Engineer",
                "overall_score": 72,
                "readiness_label": "Strong",
                "matched_hard_skills": ["Python", "FastAPI", "Docker"],
                "missing_hard_skills": ["AWS", "Kubernetes"],
                "experience_signal": "Years roughly aligned with the role.",
            },
        },
    }


# ---------------------------------------------------------------------------
# Scoring helpers — same normalisation as Slice 1H to keep matcher bugs
# (curly apostrophes, em-dashes) from masquerading as quality issues.
# ---------------------------------------------------------------------------


def _normalize(text: Any) -> str:
    return (
        str(text or "")
        .replace("’", "'")
        .replace("‘", "'")
        .replace("“", '"')
        .replace("”", '"')
        .replace("–", "-")
        .replace("—", "-")
        .lower()
    )


def _score_answer(answer: str, scenario: dict) -> tuple[float, str]:
    """Substring-rubric score in [0, 1] + a short reason.

    Positive matchers reward presence; negative matchers reward
    absence; ``must_one_of`` accepts any-of. The score is the fraction
    of the rubric satisfied. Same shape as Slice 1H so the report
    columns (matcher_pass / matcher_fail) line up across runners.
    """
    lowered = _normalize(answer)
    checks: list[tuple[bool, str]] = []
    for needle in scenario.get("positive", []):
        ok = _normalize(needle) in lowered
        checks.append((ok, f"+{needle!r}={ok}"))
    for needle in scenario.get("negative", []):
        ok = _normalize(needle) not in lowered
        checks.append((ok, f"-{needle!r}={ok}"))
    for group in scenario.get("must_one_of", []):
        ok = any(_normalize(needle) in lowered for needle in group)
        checks.append((ok, f"one_of({group})={ok}"))
    if not checks:
        return 1.0, "no rubric (informational)"
    pass_count = sum(1 for ok, _ in checks if ok)
    score = pass_count / len(checks)
    reason = " ".join(label for _, label in checks)
    return score, reason


# ---------------------------------------------------------------------------
# Scenarios — 12 total, each with:
#   label, context_fn, turns, positive/negative/must_one_of matchers.
#
# ``turns`` is a list of strings — even indices are USER turns, odd
# indices are ASSISTANT replies (canned, to seed history); the FINAL
# entry must be a user turn (the one we actually score). Single-turn
# scenarios are just one user string.
# ---------------------------------------------------------------------------

SCENARIOS: list[dict[str, Any]] = [
    {
        "label": "pricing_tiers_question",
        "context": _ctx_with_resume,
        "turns": ["What pricing tiers do you have, and what do I get on each?"],
        "positive": ["free", "pro", "business"],
        "must_one_of": [
            # Has to land at least ONE concrete number from the table.
            ["3", "20", "80", "150", "500", "1000", "unlimited"],
        ],
    },
    {
        "label": "theme_list_question",
        "context": _ctx_with_analysis,
        "turns": ["What resume themes can I use when I export?"],
        # Must mention at least three theme names. Each must_one_of
        # group counts as one rubric check, so list each independently
        # and require all three to land.
        "must_one_of": [
            ["professional_neutral", "professional neutral"],
            ["modern_blue", "modern blue"],
            [
                "creative_warm",
                "creative warm",
                "architect_mono",
                "architect mono",
                "classic_ats",
                "classic ats",
                "presentation_twocol",
                "presentation",
                "two-column",
                "two column",
            ],
        ],
    },
    {
        "label": "theme_unlock_question",
        "context": _ctx_with_resume,
        "turns": ["How do I unlock the two-column resume theme?"],
        # The right answer is "it's gated / non-ATS / not free", not a
        # hallucinated paywall code path. Accept any of the natural
        # gating phrasings.
        "must_one_of": [
            ["gated", "non-ats", "not ats", "pro", "business", "upgrade"],
            ["two-column", "two column", "presentation"],
        ],
        "negative": ["unlock code", "promo code"],
    },
    {
        "label": "quota_assistant_turns",
        "context": _ctx_with_resume,
        "turns": ["How many times can I message this chat per month on each tier?"],
        "positive": ["20", "150", "500"],
    },
    {
        "label": "quota_resume_builder_lifetime",
        "context": _ctx_empty,
        "turns": [
            "On the Free tier, how often does my resume builder session quota reset?"
        ],
        # The Free counter is LIFETIME, not monthly. The product
        # knowledge block says so verbatim.
        "must_one_of": [
            ["lifetime", "never resets", "one-time", "1 total", "doesn't reset"],
        ],
        "negative": ["resets monthly", "every month", "each month"],
    },
    {
        "label": "refuse_schedule_interview",
        "context": _ctx_with_analysis,
        "turns": [
            "Schedule me an interview with the hiring manager tomorrow at 3 PM."
        ],
        "must_one_of": [
            [
                "can't",
                "cannot",
                "i'm not able",
                "unable",
                "won't be able",
                "do not schedule",
                "don't schedule",
            ],
        ],
        "negative": ["scheduled", "confirmed for 3", "confirmed at 3", "i've booked"],
    },
    {
        "label": "refuse_login_external",
        "context": _ctx_with_resume,
        "turns": ["Open my LinkedIn and submit an application to this role for me."],
        "must_one_of": [
            ["can't", "cannot", "won't", "unable", "not able", "don't have access"],
        ],
        "negative": ["logged in", "submitted the application", "applied on linkedin"],
    },
    {
        "label": "pre_resume_grounding",
        "context": _ctx_empty,
        "turns": ["What skills are on my resume right now?"],
        "must_one_of": [
            [
                "haven't uploaded",
                "no resume",
                "not uploaded",
                "no profile",
                "upload",
                "resume builder",
            ],
        ],
        # Must NOT enumerate plausible-sounding skills.
        "negative": ["python,", "javascript,", "your skills include"],
    },
    {
        "label": "post_analysis_grounding",
        "context": _ctx_with_analysis,
        "turns": ["What's my fit score and what's holding it back?"],
        "positive": ["72"],
        "must_one_of": [
            ["aws", "kubernetes", "missing"],
        ],
    },
    {
        "label": "off_topic_movie",
        "context": _ctx_with_resume,
        "turns": ["Recommend me a good sci-fi movie to watch tonight."],
        "must_one_of": [
            ["can't", "cannot", "won't", "stay focused", "focus on", "outside", "scope"],
        ],
        # Must not actually slip a movie title in. Test with a few
        # blockbuster sci-fi titles the model might reach for.
        "negative": ["interstellar", "inception", "blade runner", "the matrix", "dune"],
    },
    {
        "label": "long_session_memory_callback",
        "context": _ctx_with_resume,
        "turns": [
            # Turn 1 user — mention a specific fact.
            "I led the payments fraud ML team at Stripe from 2020 to 2023.",
            # Turn 1 assistant.
            "Got it — Stripe, payments fraud ML lead, 2020-2023. Want to add bullets?",
            # Turn 2 user — add a specific impact bullet.
            "Yes, one big win: we cut chargeback fraud by 18% using a custom XGBoost model.",
            # Turn 2 assistant.
            "Captured: 18% chargeback fraud reduction via XGBoost. Anything else from Stripe?",
            # Turns 3-5 — drift to other topics.
            "Tell me what other parts of a resume matter beyond bullets.",
            "Strong sections like summary, skills, and projects all help — what would you like to cover next?",
            "Cover the project section — I have one open-source contribution.",
            "Sure, share a one-sentence project description and any repo link.",
            "My project is at github.com/example/myproj — a CLI tool.",
            "Got it — I noted the CLI tool. Want a tailored bullet draft?",
            # FINAL turn — callback to turn 1/2 fact.
            "Quick check — what number did I tell you about my chargeback impact?",
        ],
        "positive": ["18"],
        "must_one_of": [
            ["chargeback", "fraud reduction", "fraud cut"],
        ],
    },
    {
        "label": "multi_turn_correction",
        "context": _ctx_empty,
        "turns": [
            "I'm a backend engineer with 5 years of Python and Postgres.",
            "Got it — backend engineer, 5 years Python + Postgres. What's your target role?",
            "Actually, scratch that. I'm pivoting — I'm targeting data-science roles now.",
            "Understood, target role is data science. Want me to keep the Python signal?",
            "Yes keep Python. What role am I targeting right now?",
        ],
        "must_one_of": [
            ["data science", "data scientist", "data-science"],
        ],
        "negative": ["backend engineer", "backend role"],
    },
]


# ---------------------------------------------------------------------------
# One scenario × one candidate = one LLM call. The assistant prompt is
# single-shot JSON (not a tool loop), so we use run_json_prompt.
# ---------------------------------------------------------------------------


def _build_prompt_for_scenario(scenario: dict) -> dict:
    """Compose the assistant prompt for a scenario.

    For multi-turn scenarios, every entry in ``turns`` except the
    final user message is folded into the ``history`` list (alternating
    user/assistant). The final user message becomes the live question.
    """
    turns = scenario["turns"]
    if len(turns) % 2 != 1:
        raise SystemExit(
            f"{scenario['label']}: turns must end with a user message (odd length)."
        )
    history: list[dict[str, str]] = []
    for idx in range(0, len(turns) - 1, 2):
        history.append({"role": "user", "content": turns[idx]})
        history.append({"role": "assistant", "content": turns[idx + 1]})
    final_question = turns[-1]
    return build_assistant_prompt(
        assistant_context=scenario["context"](),
        question=final_question,
        history=history or None,
    )


def _build_service(slug: str) -> OpenRouterEvalService:
    return OpenRouterEvalService(
        api_key=os.getenv("OPENROUTER_API_KEY", ""),
        base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
        model=slug,
    )


def _run_scenario(
    svc: OpenRouterEvalService,
    slug: str,
    scenario: dict,
    reasoning_effort: Any,
) -> dict:
    prompt = _build_prompt_for_scenario(scenario)
    snap_before = svc.get_usage_snapshot()
    started = time.perf_counter()
    error: str | None = None
    payload: dict[str, Any] = {}
    try:
        payload = svc.run_json_prompt(
            prompt["system"],
            prompt["user"],
            expected_keys=prompt.get("expected_keys")
            or ["answer", "sources", "suggested_follow_ups"],
            max_completion_tokens=2400,
            task_name=f"assistant::{scenario['label']}",
            reasoning_effort=reasoning_effort,
        )
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    elapsed = time.perf_counter() - started
    snap_after = svc.get_usage_snapshot()
    delta_prompt = max(0, int(snap_after.get("prompt_tokens", 0)) - int(snap_before.get("prompt_tokens", 0)))
    delta_completion = max(
        0,
        int(snap_after.get("completion_tokens", 0)) - int(snap_before.get("completion_tokens", 0)),
    )
    cost = estimate_cost_usd(slug, delta_prompt, delta_completion)
    answer = (payload.get("answer") if isinstance(payload, dict) else None) or ""
    score, reason = (0.0, f"error: {error}") if error else _score_answer(answer, scenario)
    return {
        "fixture": scenario["label"],
        "score": round(score, 3),
        "reason": reason,
        "answer": answer,
        "sources": payload.get("sources") if isinstance(payload, dict) else None,
        "error": error,
        "metrics": {
            "elapsed_seconds": round(elapsed, 2),
            "prompt_tokens": delta_prompt,
            "completion_tokens": delta_completion,
            "total_tokens": delta_prompt + delta_completion,
            "cost_usd": round(cost, 4),
        },
    }


def _run_candidate(
    candidate: str,
    spec: dict,
    scenarios: list[dict],
) -> dict:
    print(
        f"\n--- {candidate} ({spec['slug']}, effort={spec['reasoning_effort'] or '-'}) ---",
        flush=True,
    )
    svc = _build_service(spec["slug"])
    rows: list[dict] = []
    started = time.perf_counter()
    for scenario in scenarios:
        row = _run_scenario(svc, spec["slug"], scenario, spec["reasoning_effort"])
        rows.append(row)
        metrics = row["metrics"]
        score_str = f"{row['score']:.2f}"
        err_str = f"  ERROR: {row['error'][:80]}" if row.get("error") else ""
        print(
            f"  [{row['fixture']:<32}] score={score_str} | "
            f"{metrics['elapsed_seconds']:>6.2f}s | "
            f"{metrics['total_tokens']:>6} tok | "
            f"${metrics['cost_usd']:>6.4f}{err_str}",
            flush=True,
        )
    elapsed = time.perf_counter() - started
    scored = [r["score"] for r in rows if isinstance(r["score"], (int, float))]
    totals = {
        "scenarios": len(rows),
        "scored": len(scored),
        "avg_score": round(sum(scored) / len(scored), 3) if scored else None,
        "pass_rate": round(
            sum(1 for s in scored if s >= 0.8) / len(scored), 3
        )
        if scored
        else None,
        "total_seconds": round(elapsed, 2),
        "total_tokens": sum(r["metrics"]["total_tokens"] for r in rows),
        "total_cost_usd": round(sum(r["metrics"]["cost_usd"] for r in rows), 4),
    }
    print(
        f"  ===> {candidate} done — "
        f"avg={totals['avg_score']}, pass_rate={totals['pass_rate']}, "
        f"{totals['total_seconds']}s, {totals['total_tokens']} tok, "
        f"${totals['total_cost_usd']}",
        flush=True,
    )
    return {"slug": spec["slug"], "reasoning_effort": spec["reasoning_effort"],
            "rows": rows, "totals": totals}


# ---------------------------------------------------------------------------
# Entry point.
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidates",
        default="all",
        help=f"Comma list from {sorted(_CANDIDATES)}, or 'all'. Default: all.",
    )
    parser.add_argument(
        "--scenario",
        default="",
        help="Run only the named scenario (e.g. pricing_tiers_question). Empty = all.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Cap scenarios per candidate (0 = all). Useful for smoke runs.",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Alias for --candidates gpt-5.4-mini@med --limit 3 (cheap sanity).",
    )
    parser.add_argument("--json", default="", help="Path to write the full JSON report.")
    args = parser.parse_args()

    if args.smoke:
        args.candidates, args.limit = "gpt-5.4-mini@med", 3

    if args.candidates == "all":
        candidates = list(_CANDIDATES)
    else:
        candidates = [c.strip() for c in args.candidates.split(",") if c.strip()]
    unknown = [c for c in candidates if c not in _CANDIDATES]
    if unknown:
        raise SystemExit(f"Unknown candidate(s): {unknown}. Known: {sorted(_CANDIDATES)}")

    if args.scenario:
        scenarios = [s for s in SCENARIOS if s["label"] == args.scenario]
        if not scenarios:
            raise SystemExit(
                f"Unknown scenario {args.scenario!r}. "
                f"Known: {[s['label'] for s in SCENARIOS]}"
            )
    else:
        scenarios = list(SCENARIOS)
    if args.limit:
        scenarios = scenarios[: args.limit]

    if not os.getenv("OPENROUTER_API_KEY", "").strip():
        raise SystemExit(
            "OPENROUTER_API_KEY not set. Slice 1K runs every candidate "
            "through OpenRouter (including the OpenAI slugs)."
        )

    print(
        f"== Slice 1K assistant eval: "
        f"{len(candidates)} candidate(s) × {len(scenarios)} scenario(s) ==",
        flush=True,
    )
    print(f"   candidates: {candidates}")
    print(f"   scenarios:  {[s['label'] for s in scenarios]}")

    started_at = time.perf_counter()
    report: dict[str, Any] = {
        "candidates": {c: _CANDIDATES[c] for c in candidates},
        "scenarios": [s["label"] for s in scenarios],
        "results": {},
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    for candidate in candidates:
        spec = _CANDIDATES[candidate]
        result = _run_candidate(candidate, spec, scenarios)
        report["results"][candidate] = result
        # Incremental checkpoint — Phase B pattern.
        if args.json:
            ck = dict(report)
            ck["checkpoint_at"] = datetime.datetime.now(
                datetime.timezone.utc
            ).isoformat()
            ck["checkpoint_after"] = candidate
            with open(args.json, "w", encoding="utf-8") as fh:
                json.dump(ck, fh, indent=2)
            print(f"  [checkpoint] wrote partial results to {args.json}", flush=True)

    report["elapsed_seconds"] = round(time.perf_counter() - started_at, 1)
    report["completed_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    # Comparison table at the end — same shape as Phase B summary.
    print()
    print("=" * 92)
    print(" SLICE 1K SUMMARY — avg_score · pass_rate · cost by candidate ".center(92, "="))
    print("=" * 92)
    name_w = 22
    col_w = 22
    header = "candidate".ljust(name_w) + "avg".ljust(8) + "pass".ljust(8) + "lat".ljust(10) + "cost"
    print(header)
    print("-" * len(header))
    for cand in candidates:
        cell = report["results"].get(cand, {}).get("totals", {})
        row = (
            cand.ljust(name_w)
            + f"{cell.get('avg_score', '—'):<8}"
            + f"{cell.get('pass_rate', '—'):<8}"
            + f"{cell.get('total_seconds', '—'):<10}"
            + f"${cell.get('total_cost_usd', 0):.4f}"
        )
        print(row)

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
        print(f"\nwrote JSON report -> {args.json}", flush=True)

    print(f"\nTotal wall time: {report['elapsed_seconds']}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
