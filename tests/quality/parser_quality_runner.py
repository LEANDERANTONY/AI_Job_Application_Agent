"""Tier-1 parser-quality test runner.

Runs each sample resume in `sample_resumes/` through three parsers
(deterministic, LLM-only, hybrid auto) and scores the resulting
CandidateProfile against a hand-authored ground-truth in
`expected_profiles/`. Outputs a per-fixture scorecard + summary table.

This is intentionally a runner script, not a pytest module — running
it costs LLM dollars when --include-llm is passed, so we keep it
explicit and ad-hoc rather than wired into CI.

Usage:
    python tests/quality/parser_quality_runner.py
    python tests/quality/parser_quality_runner.py --include-llm
    python tests/quality/parser_quality_runner.py --include-llm --json out.json

Field-by-field fuzzy matching keeps the test honest: a parser is
correct if it surfaces the substantive content even if formatting
differs (e.g. 'Acme' vs 'Acme Corp'). Scores are 0.0–1.0 per section.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from src.schemas import CandidateProfile, ResumeDocument
from src.services.profile_service import (
    _build_candidate_profile_from_llm_payload,
    build_candidate_profile_from_resume,
    build_candidate_profile_from_resume_auto,
)


FIXTURES_DIR = Path(__file__).parent / "sample_resumes"
EXPECTED_DIR = Path(__file__).parent / "expected_profiles"


# ---------------------------------------------------------------------------
# Fuzzy matchers
# ---------------------------------------------------------------------------


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _substring_match(needle: str, haystack: str) -> bool:
    """Case-insensitive substring match. Used everywhere because
    parsers legitimately disagree on punctuation (e.g. 'IIT Madras' vs
    'Indian Institute of Technology Madras')."""
    if not needle:
        return True
    return _norm(needle) in _norm(haystack)


def _any_substring_match(needle: str, haystacks: list[str]) -> bool:
    return any(_substring_match(needle, h) for h in haystacks)


def _list_coverage(expected: list[str], actuals: list[str]) -> tuple[float, list[str]]:
    """Returns (coverage_ratio, missing_items)."""
    if not expected:
        return 1.0, []
    missing: list[str] = []
    for item in expected:
        if not _any_substring_match(item, actuals):
            missing.append(item)
    found = len(expected) - len(missing)
    return (found / len(expected) if expected else 1.0), missing


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _score_full_name(actual: str, expected: str) -> tuple[float, str]:
    if not expected:
        return 1.0, ""
    if _norm(actual) == _norm(expected):
        return 1.0, ""
    if _substring_match(actual, expected) or _substring_match(expected, actual):
        return 0.7, f"partial: got '{actual}', expected '{expected}'"
    return 0.0, f"missed: got '{actual}', expected '{expected}'"


def _score_location(actual: str, expected: str) -> tuple[float, str]:
    if not expected:
        # Source has no location; parser inventing one is a hallucination.
        if not actual:
            return 1.0, ""
        return 0.5, f"hallucinated: '{actual}' (source had no location)"
    if _substring_match(expected, actual) or _substring_match(actual, expected):
        return 1.0, ""
    return 0.0, f"missed: got '{actual}', expected '{expected}'"


def _score_contact_lines(
    actual: list[str], expected: list[str]
) -> tuple[float, list[str]]:
    coverage, missing = _list_coverage(expected, list(actual or []))
    return coverage, missing


def _score_skills(actual: list[str], expected_must: list[str]) -> tuple[float, list[str]]:
    return _list_coverage(expected_must, list(actual or []))


def _score_experience(
    actual: list[Any],
    expected_count: int,
    expected_titles: list[str],
    expected_orgs: list[str],
) -> tuple[float, list[str]]:
    notes: list[str] = []
    if not expected_count and not expected_titles and not expected_orgs:
        if actual:
            notes.append(
                "phantom: parser produced {n} entries when source had 0".format(n=len(actual))
            )
            return 0.5, notes
        return 1.0, notes

    count_score = 1.0
    if expected_count:
        if len(actual) < expected_count:
            count_score = len(actual) / expected_count
            notes.append(
                "missed entries: got {got}, expected {exp}".format(
                    got=len(actual), exp=expected_count
                )
            )
        elif len(actual) > expected_count:
            count_score = max(0.0, 1.0 - 0.15 * (len(actual) - expected_count))
            notes.append(
                "extra entries: got {got}, expected {exp}".format(
                    got=len(actual), exp=expected_count
                )
            )

    titles_actual = [getattr(e, "title", "") for e in actual]
    title_coverage, missing_titles = _list_coverage(expected_titles, titles_actual)
    if missing_titles:
        notes.append("missing titles: " + ", ".join(missing_titles))

    orgs_actual = [getattr(e, "organization", "") for e in actual]
    org_coverage, missing_orgs = _list_coverage(expected_orgs, orgs_actual)
    if missing_orgs:
        notes.append("missing orgs: " + ", ".join(missing_orgs))

    return ((count_score + title_coverage + org_coverage) / 3.0), notes


def _score_education(
    actual: list[Any], expected: list[dict]
) -> tuple[float, list[str]]:
    notes: list[str] = []
    if not expected:
        if actual:
            notes.append("phantom education: {n} entries".format(n=len(actual)))
            return 0.5, notes
        return 1.0, notes

    matched = 0
    for entry in expected:
        institution_substr = entry.get("institution_must_include", "")
        degree_substr = entry.get("degree_must_include", "")
        for actual_entry in actual:
            inst_ok = _substring_match(
                institution_substr, getattr(actual_entry, "institution", "")
            )
            degree_ok = _substring_match(
                degree_substr, getattr(actual_entry, "degree", "")
            )
            if inst_ok and degree_ok:
                matched += 1
                break
        else:
            notes.append(
                "missing education: '{inst}' / '{deg}'".format(
                    inst=institution_substr, deg=degree_substr
                )
            )
    coverage = matched / len(expected) if expected else 1.0
    return coverage, notes


def _score_projects(
    actual: list[Any], expected_count_min: int, expected_names: list[str]
) -> tuple[float, list[str]]:
    notes: list[str] = []
    if not expected_count_min and not expected_names:
        if actual:
            notes.append("phantom projects: {n}".format(n=len(actual)))
            return 0.5, notes
        return 1.0, notes

    count_score = 1.0
    if len(actual) < expected_count_min:
        count_score = len(actual) / max(expected_count_min, 1)
        notes.append(
            "fewer projects than expected: got {got}, expected at least {exp}".format(
                got=len(actual), exp=expected_count_min
            )
        )

    names_actual = [getattr(p, "name", "") for p in actual]
    name_coverage, missing_names = _list_coverage(expected_names, names_actual)
    if missing_names:
        notes.append("missing project names: " + ", ".join(missing_names))

    return ((count_score + name_coverage) / 2.0), notes


def _score_publications(
    actual: list[str], expected_count_min: int, expected_substrings: list[str]
) -> tuple[float, list[str]]:
    notes: list[str] = []
    if not expected_count_min and not expected_substrings:
        if actual:
            notes.append("phantom publications: {n}".format(n=len(actual)))
            return 0.5, notes
        return 1.0, notes

    count_score = 1.0
    if len(actual) < expected_count_min:
        count_score = len(actual) / max(expected_count_min, 1)
        notes.append(
            "fewer publications than expected: got {got}, expected at least {exp}".format(
                got=len(actual), exp=expected_count_min
            )
        )

    sub_coverage, missing = _list_coverage(expected_substrings, list(actual or []))
    if missing:
        notes.append("missing publications: " + ", ".join(missing))
    return ((count_score + sub_coverage) / 2.0), notes


def _score_certifications(
    actual: list[str], expected_substrings: list[str]
) -> tuple[float, list[str]]:
    coverage, missing = _list_coverage(expected_substrings, list(actual or []))
    notes: list[str] = []
    if missing:
        notes.append("missing certifications: " + ", ".join(missing))
    return coverage, notes


# ---------------------------------------------------------------------------
# Per-profile scorecard
# ---------------------------------------------------------------------------


SECTION_WEIGHTS = {
    "full_name": 1.0,
    "location": 0.5,
    "contact_lines": 1.0,
    "skills": 1.5,
    "experience": 2.0,
    "education": 1.5,
    "certifications": 0.5,
    "projects": 1.5,
    "publications": 1.0,
}


def score_profile(profile: CandidateProfile, expected: dict) -> dict:
    full_name_score, full_name_note = _score_full_name(
        profile.full_name, expected.get("full_name", "")
    )
    location_score, location_note = _score_location(
        profile.location, expected.get("location", "")
    )
    contact_score, contact_missing = _score_contact_lines(
        profile.contact_lines, expected.get("contact_lines", [])
    )
    skills_score, skills_missing = _score_skills(
        profile.skills, expected.get("skills_must_include", [])
    )
    experience_score, experience_notes = _score_experience(
        profile.experience,
        expected.get("experience_count", 0),
        expected.get("experience_titles", []),
        expected.get("experience_organizations_must_include", []),
    )
    education_score, education_notes = _score_education(
        profile.education, expected.get("education", [])
    )
    cert_score, cert_notes = _score_certifications(
        profile.certifications, expected.get("certifications_must_include", [])
    )
    projects_score, project_notes = _score_projects(
        profile.projects,
        expected.get("projects_count_min", 0),
        expected.get("projects_names_must_include", []),
    )
    pub_score, pub_notes = _score_publications(
        profile.publications,
        expected.get("publications_count_min", 0),
        expected.get("publications_must_include_substrings", []),
    )

    sections = {
        "full_name": (full_name_score, [full_name_note] if full_name_note else []),
        "location": (location_score, [location_note] if location_note else []),
        "contact_lines": (
            contact_score,
            [f"missing: {x}" for x in contact_missing] if contact_missing else [],
        ),
        "skills": (
            skills_score,
            [f"missing: {x}" for x in skills_missing] if skills_missing else [],
        ),
        "experience": (experience_score, experience_notes),
        "education": (education_score, education_notes),
        "certifications": (cert_score, cert_notes),
        "projects": (projects_score, project_notes),
        "publications": (pub_score, pub_notes),
    }

    weighted_total = 0.0
    weight_sum = 0.0
    for section, (score, _) in sections.items():
        w = SECTION_WEIGHTS.get(section, 1.0)
        weighted_total += w * score
        weight_sum += w
    overall = weighted_total / weight_sum if weight_sum else 0.0

    return {
        "overall": round(overall, 3),
        "sections": {
            section: {"score": round(score, 3), "notes": notes}
            for section, (score, notes) in sections.items()
        },
        "raw": {
            "full_name": profile.full_name,
            "location": profile.location,
            "contact_count": len(profile.contact_lines),
            "skill_count": len(profile.skills),
            "experience_count": len(profile.experience),
            "education_count": len(profile.education),
            "certification_count": len(profile.certifications),
            "project_count": len(profile.projects),
            "publication_count": len(profile.publications),
        },
    }


# ---------------------------------------------------------------------------
# Mode runners
# ---------------------------------------------------------------------------


def _run_deterministic(document: ResumeDocument) -> CandidateProfile:
    return build_candidate_profile_from_resume(document)


def _fetch_llm_payload(document: ResumeDocument, parser_service) -> dict | None:
    """Single LLM call shared across llm_only and hybrid modes — keeps
    the two scorecards directly comparable. If we called the LLM twice
    we'd be measuring two stochastic outputs against the same expected
    profile, which would surface as a fake 'merge regression'."""
    if parser_service is None or not parser_service.is_available():
        return None
    try:
        return parser_service.parse(document)
    except Exception:
        return None


def _run_hybrid_auto(
    document: ResumeDocument, payload: dict | None
) -> CandidateProfile:
    deterministic_profile = build_candidate_profile_from_resume(document)
    if payload is None:
        return deterministic_profile
    return _build_candidate_profile_from_llm_payload(
        resume_document=document,
        deterministic_profile=deterministic_profile,
        payload=payload,
    )


def _run_llm_only(payload: dict | None) -> CandidateProfile | None:
    """Pure LLM payload converted to CandidateProfile, no merge with
    the deterministic profile. Useful for diagnosing whether a missed
    field is the LLM's fault or the merge's fault."""
    if payload is None:
        return None
    empty = CandidateProfile()
    return _build_candidate_profile_from_llm_payload(
        resume_document=ResumeDocument(text="", filetype="TXT"),
        deterministic_profile=empty,
        payload=payload,
    )


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _format_score(value: float) -> str:
    # ASCII-only markers so the runner works in cmd / PowerShell on
    # Windows where stdout is cp1252 by default.
    if value >= 0.95:
        return f"[ok ] {value:.2f}"
    if value >= 0.7:
        return f"[~  ] {value:.2f}"
    return f"[FAIL] {value:.2f}"


def _print_scorecard(fixture_name: str, mode_results: dict[str, dict]):
    print()
    print(f"=== {fixture_name} ===")
    sections = list(SECTION_WEIGHTS.keys())
    modes = list(mode_results.keys())
    header = f"{'Section':<18}" + "".join(f"{m:<18}" for m in modes)
    print(header)
    print("-" * len(header))
    for section in sections:
        row = f"{section:<18}"
        for mode in modes:
            data = mode_results[mode]
            if data is None:
                row += f"{'(skipped)':<18}"
                continue
            score = data["sections"][section]["score"]
            row += f"{_format_score(score):<18}"
        print(row)
    print("-" * len(header))
    overall_row = f"{'OVERALL':<18}"
    for mode in modes:
        data = mode_results[mode]
        if data is None:
            overall_row += f"{'(skipped)':<18}"
            continue
        overall_row += f"{_format_score(data['overall']):<18}"
    print(overall_row)

    # Per-mode notes
    for mode, data in mode_results.items():
        if data is None:
            continue
        notes = []
        for section, payload in data["sections"].items():
            for note in payload["notes"]:
                notes.append(f"  - [{section}] {note}")
        if notes:
            print()
            print(f"  [{mode}] notes:")
            for note in notes:
                print(note)


def _print_summary(per_fixture: list[dict]):
    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    modes = list(per_fixture[0]["modes"].keys()) if per_fixture else []
    header = f"{'Fixture':<32}" + "".join(f"{m:<18}" for m in modes)
    print(header)
    print("-" * len(header))
    for entry in per_fixture:
        row = f"{entry['fixture']:<32}"
        for mode in modes:
            data = entry["modes"][mode]
            if data is None:
                row += f"{'(skipped)':<18}"
            else:
                row += f"{_format_score(data['overall']):<18}"
        print(row)
    print("-" * len(header))
    avg_row = f"{'AVERAGE':<32}"
    for mode in modes:
        scores = [
            entry["modes"][mode]["overall"]
            for entry in per_fixture
            if entry["modes"][mode] is not None
        ]
        if scores:
            avg_row += f"{_format_score(sum(scores) / len(scores)):<18}"
        else:
            avg_row += f"{'(skipped)':<18}"
    print(avg_row)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--include-llm",
        action="store_true",
        help="Also run the LLM-only and hybrid-auto modes (costs API tokens).",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Write the full result table to this JSON path.",
    )
    args = parser.parse_args()

    llm_parser_service = None
    if args.include_llm:
        try:
            from src.openai_service import OpenAIService
            from src.services.resume_llm_parser_service import ResumeLLMParserService

            llm_parser_service = ResumeLLMParserService(OpenAIService())
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
        document = ResumeDocument(text=text, filetype="TXT", source="test")

        deterministic_profile = _run_deterministic(document)
        deterministic_score = score_profile(deterministic_profile, expected)

        llm_score = None
        hybrid_score = None
        if llm_parser_service is not None:
            payload = _fetch_llm_payload(document, llm_parser_service)
            llm_profile = _run_llm_only(payload)
            if llm_profile is not None:
                llm_score = score_profile(llm_profile, expected)
            hybrid_profile = _run_hybrid_auto(document, payload)
            hybrid_score = score_profile(hybrid_profile, expected)

        modes = {
            "deterministic": deterministic_score,
            "llm_only": llm_score,
            "hybrid": hybrid_score,
        }
        _print_scorecard(fixture_path.name, modes)
        per_fixture.append({"fixture": fixture_path.name, "modes": modes})

    _print_summary(per_fixture)

    if args.json:
        args.json.write_text(json.dumps(per_fixture, indent=2), encoding="utf-8")
        print(f"\nWrote full scorecard to {args.json}")


if __name__ == "__main__":
    main()
