"""Tier-1-style scorecard for the skill canonicalization layer.

Builds candidate-vs-JD skill pairs that exercise common synonym variants
(Postgres / PostgreSQL, k8s / Kubernetes, JS / JavaScript, etc.) and
asserts that canonicalize_skill collapses them to the same key AND that
build_fit_analysis surfaces them as matched (not missing).

This is the layer that prevents TailoringAgent from being told "candidate
is missing PostgreSQL" when the candidate already has Postgres listed.

Usage:
    python tests/quality/skill_canonicalization_runner.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from src.schemas import (
    CandidateProfile,
    JobDescription,
    JobRequirements,
)
from src.services.fit_service import build_fit_analysis
from src.taxonomy import canonicalize_skill


# ---------------------------------------------------------------------------
# Canonicalization unit tests — pure function, no LLM, no fit calc
# ---------------------------------------------------------------------------


_CANON_CASES = [
    # (left, right, should-collapse-to-same-key)
    ("Postgres", "PostgreSQL", True),
    ("postgres", "POSTGRESQL", True),
    ("k8s", "Kubernetes", True),
    ("Kube", "kubernetes", True),
    ("JS", "JavaScript", True),
    ("ts", "TypeScript", True),
    ("Node", "Node.js", True),
    ("NodeJS", "node.js", True),
    ("React.js", "React", True),
    ("reactjs", "React", True),
    ("Vue.js", "Vue", True),
    ("Next.js", "Nextjs", True),
    ("Amazon Web Services", "AWS", True),
    ("GCP", "Google Cloud Platform", True),
    ("google cloud", "GCP", True),
    ("Golang", "Go", True),
    ("C Sharp", "C#", True),
    ("C++", "cpp", True),
    ("TF", "TensorFlow", True),
    ("scikit-learn", "Sklearn", True),
    ("HuggingFace", "Hugging Face", True),
    ("CICD", "CI/CD", True),
    ("REST APIs", "REST API", True),
    # Negative cases — these should NOT collapse
    ("Python", "Java", False),
    ("Postgres", "Snowflake", False),
    ("React", "Vue", False),
    ("AWS", "Azure", False),
]


def _run_canonicalization_tests() -> tuple[int, int, list[str]]:
    passes = 0
    failures: list[str] = []
    for left, right, expected_collapse in _CANON_CASES:
        canon_left = canonicalize_skill(left)
        canon_right = canonicalize_skill(right)
        actual_collapse = canon_left == canon_right
        if actual_collapse == expected_collapse:
            passes += 1
        else:
            failures.append(
                f"FAIL: {left!r} ({canon_left!r}) vs {right!r} ({canon_right!r}) — "
                f"expected collapse={expected_collapse}, got {actual_collapse}"
            )
    return passes, len(_CANON_CASES), failures


# ---------------------------------------------------------------------------
# Fit-match tests — does build_fit_analysis surface synonyms as matched?
# ---------------------------------------------------------------------------


def _make_profile(skills: list[str]) -> CandidateProfile:
    return CandidateProfile(
        full_name="Test Candidate",
        location="Anywhere",
        contact_lines=["test@example.com"],
        source="test",
        resume_text="Python and SQL background.",
        skills=skills,
    )


def _make_jd(hard_skills: list[str], soft_skills: list[str] | None = None) -> JobDescription:
    return JobDescription(
        title="Test Role",
        raw_text="",
        cleaned_text="",
        requirements=JobRequirements(
            hard_skills=hard_skills,
            soft_skills=soft_skills or [],
        ),
    )


_FIT_CASES = [
    {
        "name": "Postgres on resume, PostgreSQL in JD",
        "candidate_skills": ["Python", "Postgres"],
        "jd_hard_skills": ["Python", "PostgreSQL"],
        "expected_matched_substrings": ["Python", "PostgreSQL"],
        "expected_missing_to_be_empty": True,
    },
    {
        "name": "k8s on resume, Kubernetes in JD",
        "candidate_skills": ["Go", "k8s"],
        "jd_hard_skills": ["Go", "Kubernetes"],
        "expected_matched_substrings": ["Go", "Kubernetes"],
        "expected_missing_to_be_empty": True,
    },
    {
        "name": "JS on resume, JavaScript in JD",
        "candidate_skills": ["JS", "TypeScript"],
        "jd_hard_skills": ["JavaScript", "TypeScript"],
        "expected_matched_substrings": ["JavaScript", "TypeScript"],
        "expected_missing_to_be_empty": True,
    },
    {
        "name": "AWS on resume, Amazon Web Services in JD",
        "candidate_skills": ["Python", "AWS"],
        "jd_hard_skills": ["Python", "Amazon Web Services"],
        "expected_matched_substrings": ["Python", "Amazon Web Services"],
        "expected_missing_to_be_empty": True,
    },
    {
        "name": "Genuine missing skill stays in missing",
        "candidate_skills": ["Python"],
        "jd_hard_skills": ["Python", "Rust"],
        "expected_matched_substrings": ["Python"],
        "expected_missing_to_contain": ["Rust"],
    },
    {
        "name": "Mixed: 1 synonym matched + 1 genuinely missing",
        "candidate_skills": ["Python", "Postgres"],
        "jd_hard_skills": ["Python", "PostgreSQL", "Redis"],
        "expected_matched_substrings": ["Python", "PostgreSQL"],
        "expected_missing_to_contain": ["Redis"],
    },
    {
        "name": "Vue.js / Vue collapse",
        "candidate_skills": ["Vue.js", "TypeScript"],
        "jd_hard_skills": ["Vue", "TypeScript"],
        "expected_matched_substrings": ["Vue", "TypeScript"],
        "expected_missing_to_be_empty": True,
    },
    {
        "name": "TensorFlow / TF collapse",
        "candidate_skills": ["Python", "TF"],
        "jd_hard_skills": ["Python", "TensorFlow"],
        "expected_matched_substrings": ["Python", "TensorFlow"],
        "expected_missing_to_be_empty": True,
    },
]


def _check_fit_case(case: dict) -> tuple[bool, str]:
    profile = _make_profile(case["candidate_skills"])
    jd = _make_jd(case["jd_hard_skills"])
    fit = build_fit_analysis(profile, jd)

    matched = fit.matched_hard_skills
    missing = fit.missing_hard_skills

    issues: list[str] = []
    for needle in case.get("expected_matched_substrings", []):
        if not any(needle.lower() in m.lower() for m in matched):
            issues.append(f"expected matched to include '{needle}', got {matched}")
    for needle in case.get("expected_missing_to_contain", []):
        if not any(needle.lower() in m.lower() for m in missing):
            issues.append(f"expected missing to contain '{needle}', got {missing}")
    if case.get("expected_missing_to_be_empty"):
        if missing:
            issues.append(f"expected missing to be empty, got {missing}")

    if issues:
        return False, " | ".join(issues)
    return True, "ok"


def _run_fit_tests() -> tuple[int, int, list[str]]:
    passes = 0
    failures: list[str] = []
    for case in _FIT_CASES:
        ok, message = _check_fit_case(case)
        if ok:
            passes += 1
        else:
            failures.append(f"FAIL: {case['name']} — {message}")
    return passes, len(_FIT_CASES), failures


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print("=" * 70)
    print("Tier-1 skill canonicalization scorecard")
    print("=" * 70)

    canon_passes, canon_total, canon_failures = _run_canonicalization_tests()
    fit_passes, fit_total, fit_failures = _run_fit_tests()

    print(f"\nCanonicalization unit tests: {canon_passes} / {canon_total}")
    for failure in canon_failures:
        print(f"  {failure}")

    print(f"\nFit-match end-to-end tests : {fit_passes} / {fit_total}")
    for failure in fit_failures:
        print(f"  {failure}")

    overall_pass = (canon_passes == canon_total) and (fit_passes == fit_total)
    print()
    print("=" * 70)
    print(f"OVERALL: {'PASS' if overall_pass else 'FAIL'}")
    print("=" * 70)

    sys.exit(0 if overall_pass else 1)


if __name__ == "__main__":
    main()
