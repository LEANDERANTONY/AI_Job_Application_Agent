"""Tier-1-style scorecard for the JD parser.

Runs each sample JD in `sample_jds/` through three modes:
  - deterministic: ``build_job_description_from_text``
  - llm_only:      LLM payload converted directly into a JobDescription
  - hybrid:        ``build_job_description_from_text_auto`` (production)

and scores each resulting `JobDescription` against the hand-authored
expected JSON in `expected_jds/`. Mirrors the resume parser_quality_runner.

Usage:
    python tests/quality/jd_parser_quality_runner.py                   # deterministic only (free)
    python tests/quality/jd_parser_quality_runner.py --include-llm     # all 3 modes (~$0.05)
    python tests/quality/jd_parser_quality_runner.py --json out.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from src.schemas import JobDescription
from src.services.job_service import (
    _build_job_description_from_llm_payload,
    build_job_description_from_text,
    build_job_description_from_text_auto,
)


FIXTURES_DIR = Path(__file__).parent / "sample_jds"
EXPECTED_DIR = Path(__file__).parent / "expected_jds"


# ---------------------------------------------------------------------------
# Fuzzy matchers
# ---------------------------------------------------------------------------


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _substring_match(needle: str, haystack: str) -> bool:
    if not needle:
        return True
    return _norm(needle) in _norm(haystack)


def _any_substring_match(needle: str, haystacks: list[str]) -> bool:
    return any(_substring_match(needle, h) for h in haystacks)


def _list_coverage(expected: list[str], actuals: list[str]) -> tuple[float, list[str]]:
    if not expected:
        return 1.0, []
    missing = [item for item in expected if not _any_substring_match(item, actuals)]
    found = len(expected) - len(missing)
    return (found / len(expected) if expected else 1.0), missing


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _score_title(actual: str, expected_substr: str) -> tuple[float, list[str]]:
    if not expected_substr:
        return 1.0, []
    if _substring_match(expected_substr, actual):
        return 1.0, []
    return 0.0, [f"missed: got {actual!r}, expected substring {expected_substr!r}"]


def _score_location(actual: str | None, expected_substr: str) -> tuple[float, list[str]]:
    if not expected_substr:
        return 1.0, []
    if actual and _substring_match(expected_substr, actual):
        return 1.0, []
    return 0.0, [f"missed: got {actual!r}, expected substring {expected_substr!r}"]


def _score_salary(actual: str | None, expected_substr: str) -> tuple[float, list[str]]:
    if not expected_substr:
        # No salary expected — phantom = mild penalty.
        if actual:
            return 0.5, [f"phantom salary: got {actual!r} (none expected)"]
        return 1.0, []
    if actual and _substring_match(expected_substr, actual):
        return 1.0, []
    return 0.0, [f"missed: got {actual!r}, expected substring {expected_substr!r}"]


def _score_experience(actual: str | None, expected_substr: str) -> tuple[float, list[str]]:
    if not expected_substr:
        return 1.0, []
    if actual and _substring_match(expected_substr, actual):
        return 1.0, []
    return 0.0, [f"missed: got {actual!r}, expected substring {expected_substr!r}"]


def _score_skills(actual: list[str], expected_must: list[str]) -> tuple[float, list[str]]:
    coverage, missing = _list_coverage(expected_must, list(actual or []))
    return coverage, [f"missing skill: {item!r}" for item in missing]


def _score_niche_skills(
    actual: list[str], niche_known_to_miss: list[str]
) -> tuple[float, list[str]]:
    """Score how many of the 'known niche' skills the parser DID pick up.
    These are skills we expect the deterministic parser to miss; the score
    measures how badly. 0.0 = all missed (worst); 1.0 = all caught."""
    if not niche_known_to_miss:
        return 1.0, []
    coverage, missing = _list_coverage(niche_known_to_miss, list(actual or []))
    notes: list[str] = []
    if missing:
        notes.append(
            "niche-skills missed: {}".format(", ".join(missing))
        )
    return coverage, notes


SECTION_WEIGHTS = {
    "title": 1.5,
    "location": 1.0,
    "salary": 0.5,
    "experience": 1.0,
    "skills": 1.5,
    "niche_skills": 0.0,  # diagnostic only — doesn't affect overall score
}


def score_jd(profile: JobDescription, expected: dict) -> dict:
    title_score, title_notes = _score_title(
        profile.title, expected.get("title_must_include", "")
    )
    location_score, location_notes = _score_location(
        profile.location, expected.get("location_must_include", "")
    )
    salary_score, salary_notes = _score_salary(
        profile.salary, expected.get("salary_must_include", "")
    )
    experience_score, experience_notes = _score_experience(
        profile.requirements.experience_requirement,
        expected.get("experience_requirement_must_include", ""),
    )
    skills_score, skills_notes = _score_skills(
        profile.requirements.hard_skills, expected.get("hard_skills_must_include", [])
    )
    niche_score, niche_notes = _score_niche_skills(
        profile.requirements.hard_skills,
        expected.get("niche_skills_known_to_miss", []),
    )

    sections = {
        "title": (title_score, title_notes),
        "location": (location_score, location_notes),
        "salary": (salary_score, salary_notes),
        "experience": (experience_score, experience_notes),
        "skills": (skills_score, skills_notes),
        "niche_skills": (niche_score, niche_notes),
    }

    weighted = 0.0
    weight_sum = 0.0
    for section, (score, _) in sections.items():
        w = SECTION_WEIGHTS.get(section, 1.0)
        weighted += w * score
        weight_sum += w
    overall = weighted / weight_sum if weight_sum else 0.0

    return {
        "overall": round(overall, 3),
        "sections": {
            section: {"score": round(score, 3), "notes": notes}
            for section, (score, notes) in sections.items()
        },
        "raw": {
            "title": profile.title,
            "location": profile.location,
            "salary": profile.salary,
            "experience_requirement": profile.requirements.experience_requirement,
            "hard_skill_count": len(profile.requirements.hard_skills),
            "hard_skills": list(profile.requirements.hard_skills),
            "soft_skill_count": len(profile.requirements.soft_skills),
            "must_haves_count": len(profile.requirements.must_haves),
            "nice_to_haves_count": len(profile.requirements.nice_to_haves),
        },
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _format_score(value: float) -> str:
    if value >= 0.95:
        return f"[ok ] {value:.2f}"
    if value >= 0.7:
        return f"[~  ] {value:.2f}"
    return f"[FAIL] {value:.2f}"


def _print_summary(per_fixture: list[dict]):
    print()
    print("=" * 90)
    print("SUMMARY")
    print("=" * 90)
    modes = list(per_fixture[0]["modes"].keys()) if per_fixture else []
    header = f"{'Fixture':<48}" + "".join(f"{m:<14}" for m in modes)
    print(header)
    print("-" * len(header))
    for entry in per_fixture:
        row = f"{entry['fixture']:<48}"
        for mode in modes:
            data = entry["modes"][mode]
            if data is None:
                row += f"{'(skipped)':<14}"
            else:
                row += f"{_format_score(data['overall']):<14}"
        print(row)
    print("-" * len(header))
    avg_row = f"{'AVERAGE':<48}"
    for mode in modes:
        scores = [
            entry["modes"][mode]["overall"]
            for entry in per_fixture
            if entry["modes"][mode] is not None
        ]
        if scores:
            avg_row += f"{_format_score(sum(scores) / len(scores)):<14}"
        else:
            avg_row += f"{'(skipped)':<14}"
    print(avg_row)


def _run_deterministic(text: str) -> JobDescription:
    return build_job_description_from_text(text)


def _fetch_llm_payload(text: str, parser_service) -> dict | None:
    """Single LLM call shared across llm_only and hybrid modes."""
    if parser_service is None or not parser_service.is_available():
        return None
    try:
        return parser_service.parse(text)
    except Exception as exc:
        print(f"  [llm] parse failed: {type(exc).__name__}: {str(exc)[:160]}")
        return None


def _run_llm_only(text: str, payload: dict | None) -> JobDescription | None:
    if payload is None:
        return None
    deterministic_profile = build_job_description_from_text(text)
    return _build_job_description_from_llm_payload(
        raw_text=text,
        deterministic_profile=deterministic_profile,
        payload=payload,
    )


def _run_hybrid(text: str, payload: dict | None) -> JobDescription:
    if payload is None:
        return build_job_description_from_text(text)
    deterministic_profile = build_job_description_from_text(text)
    return _build_job_description_from_llm_payload(
        raw_text=text,
        deterministic_profile=deterministic_profile,
        payload=payload,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--include-llm",
        action="store_true",
        help="Also run the LLM-only and hybrid modes (costs API tokens).",
    )
    parser.add_argument("--json", type=Path, default=None, help="Write full results to JSON.")
    args = parser.parse_args()

    llm_parser_service = None
    if args.include_llm:
        try:
            from src.openai_service import OpenAIService
            from src.services.jd_llm_parser_service import JobDescriptionLLMParserService

            llm_parser_service = JobDescriptionLLMParserService(OpenAIService())
            if not llm_parser_service.is_available():
                print("WARNING: --include-llm passed but OpenAI is not configured.")
                llm_parser_service = None
        except Exception as exc:
            print(f"WARNING: failed to initialise LLM parser: {exc}")
            llm_parser_service = None

    fixture_paths = sorted(FIXTURES_DIR.glob("*.txt"))
    per_fixture: list[dict] = []

    for fixture_path in fixture_paths:
        expected_path = EXPECTED_DIR / (fixture_path.stem + ".json")
        if not expected_path.exists():
            print(f"SKIP {fixture_path.name}: no expected JSON.")
            continue
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
        text = fixture_path.read_text(encoding="utf-8")
        try:
            deterministic_jd = _run_deterministic(text)
        except Exception as exc:
            print(f"PARSE-CRASH {fixture_path.name}: {type(exc).__name__}: {exc}")
            continue
        deterministic_score = score_jd(deterministic_jd, expected)

        llm_score = None
        hybrid_score = None
        if llm_parser_service is not None:
            payload = _fetch_llm_payload(text, llm_parser_service)
            llm_jd = _run_llm_only(text, payload)
            if llm_jd is not None:
                llm_score = score_jd(llm_jd, expected)
            hybrid_jd = _run_hybrid(text, payload)
            hybrid_score = score_jd(hybrid_jd, expected)

        modes = {
            "deterministic": deterministic_score,
            "llm_only": llm_score,
            "hybrid": hybrid_score,
        }
        per_fixture.append({"fixture": fixture_path.name, "modes": modes})

    _print_summary(per_fixture)

    if args.json:
        args.json.write_text(json.dumps(per_fixture, indent=2), encoding="utf-8")
        print(f"\nWrote full scorecard to {args.json}")


if __name__ == "__main__":
    main()
