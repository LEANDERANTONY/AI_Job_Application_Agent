"""Tier-3 scorecard for the resume-builder structuring pass.

The structuring pass is what runs at /generate and /export time
(`_structure_via_llm`): takes the user's verbatim free-form
`experience_notes` / `education_notes` and turns them into structured
WorkExperience + EducationEntry lists. Two modes scored side by side:

- deterministic: the regex parsers (_build_experience_entries /
  _build_education_entries from the notes string). Free, fast, the
  fallback when the LLM is unavailable.
- llm_only: gpt-5.4-mini via the real OpenAIService through
  _structure_via_llm. The production path when the user is signed in.

Coverage targets the realistic shapes a user types:
- Multi-role single line ('X at A 2020-Present, prior at B 2017-2020').
- Rich prose with embedded bullets (the Stripe / Cloudflare scenario).
- Newline-separated multi-line entries.
- Sparse one-liner with no bullets.
- Multi-degree single line with bare institution names (Stanford,
  IIT Madras).
- Education with 'from' connector.
- Hallucination guard: prose with no specific numbers must NOT yield
  bullets with invented metrics.

Score dimensions:
- entry_count: did we split into the right number of WorkExperience
  / EducationEntry items?
- title / organization / institution: are the labels correct?
- dates: did we extract start / end into their own fields?
- bullets: rich-input scenarios should have polished bullet text.
- fact_preservation: company names + specific numbers from the prose
  must appear verbatim in the rendered bullets (and no invented ones).

Usage:
    python tests/quality/resume_builder_structuring_quality_runner.py
    python tests/quality/resume_builder_structuring_quality_runner.py --include-llm
    python tests/quality/resume_builder_structuring_quality_runner.py --include-llm --json out.json

Cost: --include-llm runs ~8 scenarios x 1 structuring call each,
gpt-5.4-mini, prompt ~1.5KB / response ~1KB → roughly $0.02.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

from backend.services.resume_builder_service import (
    ResumeBuilderDraft,
    ResumeBuilderSession,
    _build_education_entries,
    _build_experience_entries,
    _structure_via_llm,
)


# ---------------------------------------------------------------------------
# Helpers (mirrored from resume_builder_quality_runner)
# ---------------------------------------------------------------------------


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _substring_in(needle: str, haystacks: list[str]) -> bool:
    if not needle:
        return True
    needle_norm = _norm(needle)
    return any(needle_norm in _norm(h) for h in haystacks)


# ---------------------------------------------------------------------------
# Scenarios — each describes a draft and the expected structured shape.
# ---------------------------------------------------------------------------


_SCENARIOS: list[dict[str, Any]] = [
    {
        "name": "multi_role_single_line_with_transition",
        "draft": {
            "experience_notes": (
                "Senior Backend Engineer at TechCorp from 2020-Present, "
                "prior at FinStart 2017-2020"
            ),
            "education_notes": "",
        },
        "expected": {
            "experience_count": 2,
            "experience_entries": [
                {
                    "organization": "TechCorp",
                    "title_substring": "Senior Backend Engineer",
                    "start": "2020",
                    "end": "Present",
                },
                {
                    "organization": "FinStart",
                    "start": "2017",
                    "end": "2020",
                },
            ],
            "education_count": 0,
        },
    },
    {
        "name": "rich_two_role_prose_with_bullets",
        "draft": {
            "experience_notes": (
                "Senior Backend Engineer at Stripe (Jul 2022 - Present) - "
                "led the rate-limiter rewrite cutting p99 from 240ms to "
                "45ms; shipped Vitess migrations for 3.2B legacy charges. "
                "Software Engineer at Cloudflare (Aug 2019 - Jun 2022) - "
                "owned cache invalidation pipeline; reduced global read "
                "p99 by 38%."
            ),
            "education_notes": "",
        },
        "expected": {
            "experience_count": 2,
            "experience_entries": [
                {
                    "organization": "Stripe",
                    "title_substring": "Senior Backend Engineer",
                    "start_substring": "2022",
                    "end": "Present",
                    "bullet_substrings": ["240ms", "45ms"],
                },
                {
                    "organization": "Cloudflare",
                    "title_substring": "Engineer",
                    "start_substring": "2019",
                    "end_substring": "2022",
                    "bullet_substrings": ["38%", "cache"],
                },
            ],
            "education_count": 0,
        },
    },
    {
        "name": "multiline_entries_with_explicit_bullets",
        "draft": {
            "experience_notes": (
                "AI Engineer at Example Labs (Jan 2023 - Present)\n"
                "- Built FastAPI services that ship LLM evaluation reports.\n"
                "- Drove 30% latency drop in the inference pipeline."
            ),
            "education_notes": "",
        },
        "expected": {
            "experience_count": 1,
            "experience_entries": [
                {
                    "organization": "Example Labs",
                    "title_substring": "AI Engineer",
                    "bullet_substrings": ["FastAPI", "30%"],
                },
            ],
            "education_count": 0,
        },
    },
    {
        "name": "sparse_role_no_bullets",
        # User typed only the headline. Must produce one entry with the
        # right title/org and NOT fabricate impact bullets.
        "draft": {
            "experience_notes": "ML Engineer at Acme",
            "education_notes": "",
        },
        "expected": {
            "experience_count": 1,
            "experience_entries": [
                {"organization": "Acme", "title_substring": "ML Engineer"},
            ],
            "education_count": 0,
            # Hallucination guard: no specific numbers were mentioned by
            # the user, so the bullets MUST NOT contain "%", "ms", "x",
            # or other invented metrics.
            "no_invented_numbers_in_bullets": True,
        },
    },
    {
        "name": "multi_degree_single_line",
        "draft": {
            "experience_notes": "",
            "education_notes": "MS Computer Science Stanford 2017, BTech CS IIT Madras 2015",
        },
        "expected": {
            "experience_count": 0,
            "education_count": 2,
            "education_entries": [
                {
                    "institution_substring": "Stanford",
                    "degree_substring": "MS",
                    "field_substring": "Computer Science",
                },
                {
                    "institution_substring": "IIT Madras",
                    "degree_substring": "BTech",
                },
            ],
        },
    },
    {
        "name": "education_with_from_connector",
        "draft": {
            "experience_notes": "",
            "education_notes": "MSc in Artificial Intelligence from Liverpool John Moores University (2025-2026)",
        },
        "expected": {
            "experience_count": 0,
            "education_count": 1,
            "education_entries": [
                {
                    "institution_substring": "Liverpool John Moores",
                    "degree_substring": "MSc",
                },
            ],
        },
    },
    {
        "name": "rich_complete_input",
        # Realistic complete input: 2 roles + 2 degrees together. Pins
        # the integration of both halves of the structuring contract.
        "draft": {
            "experience_notes": (
                "Independent AI/ML Developer (2022-Present) - built RAG Q&A "
                "system, agentic job application assistant, and multimodal "
                "cancer detection framework. Software Engineer at Acme "
                "(2019-2022) - owned billing pipeline migration."
            ),
            "education_notes": (
                "MSc Artificial Intelligence Liverpool John Moores University 2025-2026, "
                "B.Tech Mechanical Engineering Manipal Institute of Technology 2015-2019"
            ),
        },
        "expected": {
            "experience_count": 2,
            "experience_entries": [
                {
                    "title_substring": "Independent",
                    "start_substring": "2022",
                    "end": "Present",
                    "bullet_substrings": ["RAG"],
                },
                {
                    "organization": "Acme",
                    "start_substring": "2019",
                    "end_substring": "2022",
                    "bullet_substrings": ["billing"],
                },
            ],
            "education_count": 2,
            "education_entries": [
                {"institution_substring": "Liverpool John Moores"},
                {"institution_substring": "Manipal"},
            ],
        },
    },
    {
        "name": "hallucination_guard_vague_prose",
        # User said "did good work" with no specifics. Bullets must NOT
        # contain any specific numbers / metrics / company names beyond
        # what's in the prose.
        "draft": {
            "experience_notes": (
                "Senior Engineer at Acme 2020-Present - did some interesting "
                "work on the platform team."
            ),
            "education_notes": "",
        },
        "expected": {
            "experience_count": 1,
            "experience_entries": [
                {"organization": "Acme", "title_substring": "Senior Engineer"},
            ],
            "education_count": 0,
            "no_invented_numbers_in_bullets": True,
            "no_invented_companies_in_bullets": ["TechCorp", "FinStart", "Stripe", "Cloudflare", "Google"],
        },
    },
]


# ---------------------------------------------------------------------------
# Dimension scorers
# ---------------------------------------------------------------------------


def _score_experience_count(experience: list, expected: dict) -> tuple[float, str]:
    expected_count = expected.get("experience_count")
    if expected_count is None:
        return 1.0, "no expectation"
    actual = len(experience)
    if actual == expected_count:
        return 1.0, f"got {actual} entries"
    return 0.0, f"expected {expected_count}, got {actual}"


def _score_education_count(education: list, expected: dict) -> tuple[float, str]:
    expected_count = expected.get("education_count")
    if expected_count is None:
        return 1.0, "no expectation"
    actual = len(education)
    if actual == expected_count:
        return 1.0, f"got {actual} entries"
    return 0.0, f"expected {expected_count}, got {actual}"


def _score_experience_fields(experience: list, expected: dict) -> tuple[float, str]:
    expected_entries = expected.get("experience_entries") or []
    if not expected_entries:
        return 1.0, "no expectation"
    if not experience:
        return 0.0, "no experience entries to score"
    hits = 0
    total = 0
    notes: list[str] = []
    for i, exp in enumerate(expected_entries):
        if i >= len(experience):
            notes.append(f"missing entry {i}")
            total += len(exp)
            continue
        actual = experience[i]
        actual_dict = asdict(actual) if hasattr(actual, "__dataclass_fields__") else actual
        for key, expected_value in exp.items():
            total += 1
            if key == "title_substring":
                if _substring_in(expected_value, [actual_dict.get("title", "")]):
                    hits += 1
                else:
                    notes.append(f"entry {i} title missing '{expected_value}'")
            elif key == "organization":
                if _norm(actual_dict.get("organization")) == _norm(expected_value):
                    hits += 1
                else:
                    notes.append(
                        f"entry {i} org '{actual_dict.get('organization')}' "
                        f"!= '{expected_value}'"
                    )
            elif key == "start":
                if _norm(actual_dict.get("start") or "") == _norm(expected_value):
                    hits += 1
                else:
                    notes.append(
                        f"entry {i} start '{actual_dict.get('start')}' != '{expected_value}'"
                    )
            elif key == "start_substring":
                if _substring_in(expected_value, [str(actual_dict.get("start") or "")]):
                    hits += 1
                else:
                    notes.append(f"entry {i} start missing '{expected_value}'")
            elif key == "end":
                if _norm(actual_dict.get("end") or "") == _norm(expected_value):
                    hits += 1
                else:
                    notes.append(
                        f"entry {i} end '{actual_dict.get('end')}' != '{expected_value}'"
                    )
            elif key == "end_substring":
                if _substring_in(expected_value, [str(actual_dict.get("end") or "")]):
                    hits += 1
                else:
                    notes.append(f"entry {i} end missing '{expected_value}'")
            elif key == "bullet_substrings":
                description = actual_dict.get("description") or ""
                missing = [s for s in expected_value if s.lower() not in description.lower()]
                if not missing:
                    hits += 1
                else:
                    notes.append(f"entry {i} bullets missing {missing}")
    score = hits / total if total else 0.0
    note = "; ".join(notes) if notes else f"{hits}/{total} field matches"
    return score, note


def _score_education_fields(education: list, expected: dict) -> tuple[float, str]:
    expected_entries = expected.get("education_entries") or []
    if not expected_entries:
        return 1.0, "no expectation"
    if not education:
        return 0.0, "no education entries to score"
    # Education entries from LLM may not be in the same order as expected;
    # match each expected entry to the best candidate by institution.
    actual_dicts = [
        asdict(e) if hasattr(e, "__dataclass_fields__") else e
        for e in education
    ]
    hits = 0
    total = 0
    notes: list[str] = []
    used = set()
    for i, exp in enumerate(expected_entries):
        institution_target = (exp.get("institution_substring") or "").lower()
        match_idx = None
        for j, ad in enumerate(actual_dicts):
            if j in used:
                continue
            if institution_target and institution_target in (ad.get("institution") or "").lower():
                match_idx = j
                break
        if match_idx is None:
            total += len(exp)
            notes.append(f"no education entry matched '{exp.get('institution_substring')}'")
            continue
        used.add(match_idx)
        actual = actual_dicts[match_idx]
        for key, expected_value in exp.items():
            total += 1
            if key == "institution_substring":
                if _substring_in(expected_value, [actual.get("institution", "")]):
                    hits += 1
                else:
                    notes.append(f"institution '{actual.get('institution')}' missing '{expected_value}'")
            elif key == "degree_substring":
                if _substring_in(expected_value, [actual.get("degree", "")]):
                    hits += 1
                else:
                    notes.append(f"degree '{actual.get('degree')}' missing '{expected_value}'")
            elif key == "field_substring":
                # field could land in degree (LLM) or institution (regex)
                merged = (actual.get("degree", "") + " " + actual.get("field_of_study", "")).strip()
                if _substring_in(expected_value, [merged]):
                    hits += 1
                else:
                    notes.append(f"field-of-study missing '{expected_value}'")
    score = hits / total if total else 0.0
    note = "; ".join(notes) if notes else f"{hits}/{total} field matches"
    return score, note


def _score_hallucination_guard(experience: list, expected: dict) -> tuple[float, str]:
    """Bullets must not contain invented numbers or company names when
    the user's prose was vague."""
    notes: list[str] = []
    score = 1.0
    no_invented_numbers = expected.get("no_invented_numbers_in_bullets")
    if no_invented_numbers:
        for i, entry in enumerate(experience):
            description = (
                asdict(entry).get("description")
                if hasattr(entry, "__dataclass_fields__")
                else (entry.get("description") if isinstance(entry, dict) else "")
            ) or ""
            # Look for percent / ms / x-multiplier / dollar / unit numbers.
            import re as _re
            invented = _re.findall(
                r"\b\d+(?:\.\d+)?\s*(?:%|ms|x|million|billion|m|b|users|reqs)\b",
                description,
                _re.IGNORECASE,
            )
            if invented:
                score = 0.0
                notes.append(f"entry {i} invented metrics: {invented}")
    invented_companies = expected.get("no_invented_companies_in_bullets") or []
    if invented_companies:
        for i, entry in enumerate(experience):
            description = (
                asdict(entry).get("description")
                if hasattr(entry, "__dataclass_fields__")
                else (entry.get("description") if isinstance(entry, dict) else "")
            ) or ""
            invented = [c for c in invented_companies if c.lower() in description.lower()]
            if invented:
                score = 0.0
                notes.append(f"entry {i} invented companies: {invented}")
    if not no_invented_numbers and not invented_companies:
        return 1.0, "no expectation"
    return score, "; ".join(notes) if notes else "clean"


_DIMENSION_WEIGHTS = {
    "experience_count": 1.0,
    "education_count": 1.0,
    "experience_fields": 2.0,
    "education_fields": 2.0,
    "hallucination_guard": 1.5,
}

_SCORERS = {
    "experience_count": lambda exp, edu, expected: _score_experience_count(exp, expected),
    "education_count": lambda exp, edu, expected: _score_education_count(edu, expected),
    "experience_fields": lambda exp, edu, expected: _score_experience_fields(exp, expected),
    "education_fields": lambda exp, edu, expected: _score_education_fields(edu, expected),
    "hallucination_guard": lambda exp, edu, expected: _score_hallucination_guard(exp, expected),
}


# ---------------------------------------------------------------------------
# Scenario runner
# ---------------------------------------------------------------------------


def _run_scenario(scenario: dict, *, mode: str, openai_service=None) -> dict:
    """Run one structuring scenario in deterministic or llm mode.

    deterministic: call _build_experience_entries / _build_education_entries
    directly on the prose.

    llm: assemble a ResumeBuilderSession with the draft, call
    _structure_via_llm with the real OpenAIService.
    """
    draft_payload = scenario["draft"]
    experience_notes = draft_payload.get("experience_notes", "")
    education_notes = draft_payload.get("education_notes", "")

    error: str | None = None
    if mode == "deterministic":
        try:
            experience = _build_experience_entries(experience_notes)
            education = _build_education_entries(education_notes)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            experience, education = [], []
    elif mode == "llm":
        if openai_service is None:
            return {
                "name": scenario["name"],
                "mode": mode,
                "overall": 0.0,
                "error": "no openai_service",
                "dimensions": {},
            }
        session = ResumeBuilderSession(
            session_id="quality-runner",
            draft=ResumeBuilderDraft(
                full_name=draft_payload.get("full_name", "Test Candidate"),
                target_role=draft_payload.get("target_role", ""),
                professional_summary=draft_payload.get("professional_summary", ""),
                experience_notes=experience_notes,
                education_notes=education_notes,
                skills=draft_payload.get("skills", []),
            ),
        )
        try:
            result = _structure_via_llm(session, openai_service=openai_service)
            if result is None:
                error = "structuring returned None (LLM unavailable or failed)"
                experience, education = [], []
            else:
                experience, education = result
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            experience, education = [], []
    else:
        raise ValueError(f"unknown mode: {mode}")

    expected = scenario["expected"]
    dimension_scores: dict[str, dict[str, Any]] = {}
    for dim, scorer in _SCORERS.items():
        score, note = scorer(experience, education, expected)
        dimension_scores[dim] = {
            "score": round(score, 3),
            "weight": _DIMENSION_WEIGHTS[dim],
            "note": note,
        }
    weighted_total = sum(d["score"] * d["weight"] for d in dimension_scores.values())
    weighted_max = sum(_DIMENSION_WEIGHTS.values())
    overall = weighted_total / weighted_max if weighted_max else 0.0

    return {
        "name": scenario["name"],
        "mode": mode,
        "overall": round(overall, 3),
        "dimensions": dimension_scores,
        "error": error,
        "experience": [
            asdict(e) if hasattr(e, "__dataclass_fields__") else e
            for e in experience
        ],
        "education": [
            asdict(e) if hasattr(e, "__dataclass_fields__") else e
            for e in education
        ],
    }


# ---------------------------------------------------------------------------
# CLI / report
# ---------------------------------------------------------------------------


def _format_dimension_row(name: str, payload: dict) -> str:
    score = payload["score"]
    weight = payload["weight"]
    note = payload["note"]
    bar = "#" * int(round(score * 10))
    return f"    {name:<20} {score:.2f}  [w={weight:.1f}]  {bar:<10}  {note}"


def _format_score(value: float | None) -> str:
    if value is None:
        return "(skipped)"
    return f"{value:.3f}"


def _print_scenario_summary(name: str, deterministic_result: dict | None, llm_result: dict | None):
    det_overall = deterministic_result["overall"] if deterministic_result else None
    llm_overall = llm_result["overall"] if llm_result else None
    print(
        f"\n[{name}]  deterministic={_format_score(det_overall)}    "
        f"llm={_format_score(llm_overall)}"
    )
    for label, result in (("deterministic", deterministic_result), ("llm", llm_result)):
        if result is None:
            continue
        if result.get("error"):
            print(f"  [{label}] ERROR: {result['error']}")
        for dim, payload in result.get("dimensions", {}).items():
            if payload["score"] < 1.0:
                print(_format_dimension_row(dim, payload))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--include-llm",
        action="store_true",
        help="Also run the LLM path (costs gpt-5.4-mini API tokens, ~$0.02 total).",
    )
    parser.add_argument("--json", type=str, help="Path to dump the full scorecard as JSON.")
    args = parser.parse_args()

    print("=" * 78)
    print("Tier-3 resume-builder STRUCTURING scorecard (deterministic + llm)")
    print("=" * 78)

    openai_service = None
    if args.include_llm:
        try:
            from src.openai_service import OpenAIService

            openai_service = OpenAIService()
            if not openai_service.is_available():
                print("WARNING: --include-llm passed but OpenAI is not configured.")
                openai_service = None
        except Exception as exc:
            print(f"WARNING: failed to initialise OpenAIService: {exc}")
            openai_service = None

    if not args.include_llm:
        print("Running deterministic mode only. Pass --include-llm to also score the LLM path.")

    per_scenario: list[dict] = []
    for scenario in _SCENARIOS:
        det = _run_scenario(scenario, mode="deterministic")
        llm = (
            _run_scenario(scenario, mode="llm", openai_service=openai_service)
            if openai_service is not None
            else None
        )
        _print_scenario_summary(scenario["name"], det, llm)
        per_scenario.append({
            "name": scenario["name"],
            "modes": {"deterministic": det, "llm": llm},
        })

    print("\n" + "=" * 78)
    print("Aggregate")
    print("=" * 78)
    det_avg = (
        sum(p["modes"]["deterministic"]["overall"] for p in per_scenario)
        / len(per_scenario)
        if per_scenario
        else 0.0
    )
    print(f"  deterministic average: {det_avg:.3f}")
    if openai_service is not None:
        llm_results = [
            p["modes"]["llm"]["overall"]
            for p in per_scenario
            if p["modes"].get("llm")
        ]
        llm_avg = sum(llm_results) / len(llm_results) if llm_results else 0.0
        print(f"  llm average:           {llm_avg:.3f}")

    output_dir = Path(__file__).parent
    output_path = output_dir / "_last_resume_builder_structuring_run.json"
    output_path.write_text(
        json.dumps({"scenarios": per_scenario, "aggregate_deterministic": det_avg}, indent=2),
        encoding="utf-8",
    )
    print(f"\nFull scorecard written to {output_path}")
    if args.json:
        Path(args.json).write_text(
            json.dumps({"scenarios": per_scenario, "aggregate_deterministic": det_avg}, indent=2),
            encoding="utf-8",
        )
        print(f"Also written to {args.json}")


if __name__ == "__main__":
    main()
