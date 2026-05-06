"""Tier-3 TailoringAgent quality runner.

Runs the TailoringAgent against a curated set of (resume, JD) fixture
pairs covering strong fits, gap-heavy mismatches, wrong-industry
extreme mismatches, and minimal-info edge cases. Scores the output
on six dimensions tied to the agent's actual failure modes:

- grounding (1.5x): are highlighted_skills actually in the candidate
  profile? Detects skill fabrication.
- gap_avoidance (1.5x): does the agent NOT promote skills that are in
  fit_analysis.missing_hard_skills? Detects gap-claiming.
- jd_alignment (1.0x): does the agent surface matched_hard_skills?
  Detects failure to actually tailor.
- format_compliance (0.5x): bullets 3-5, skills 4-8, themes 2-4.
- non_empty (0.5x): all four fields populated.
- summary_sentence_count (0.5x): professional_summary is 2-5 sentences.

Two modes are compared:
- deterministic: TailoringAgent fallback (no LLM); reads tailored_draft.
- llm_only: gpt-5.4-mini via OpenAIService (the production path).

Usage:
    python tests/quality/tailoring_quality_runner.py
    python tests/quality/tailoring_quality_runner.py --include-llm
    python tests/quality/tailoring_quality_runner.py --include-llm --json out.json

Like the parser runner, this is intentionally a script not a pytest
module — running --include-llm costs API tokens.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from src.agents.tailoring_agent import TailoringAgent
from src.schemas import ResumeDocument, TailoringAgentOutput
from src.services.fit_service import build_fit_analysis
from src.services.job_service import build_job_description_from_text
from src.services.profile_service import build_candidate_profile_from_resume_auto
from src.services.tailoring_service import build_tailored_resume_draft
from src.taxonomy import canonicalize_skill


RESUMES_DIR = Path(__file__).parent / "sample_resumes"
JDS_DIR = Path(__file__).parent / "sample_jds"


# ---------------------------------------------------------------------------
# Fixture pairs — covers strong fit, gap-heavy, wrong-industry, minimal info
# ---------------------------------------------------------------------------

FIXTURE_PAIRS: list[tuple[str, str, str]] = [
    # (label, resume_filename, jd_filename)
    ("strong_fit_data_eng", "02-midcareer-tech.txt", "07-placer-big-data-engineer.txt"),
    ("gaps_junior_on_senior", "04-bootcamp-grad.txt", "04-moloco-data-scientist.txt"),
    ("gaps_career_switcher", "05-career-switcher.txt", "01-narvar-senior-ai-engineer.txt"),
    ("strong_fit_senior_ai", "11-senior-detailed.txt", "01-narvar-senior-ai-engineer.txt"),
    ("wrong_industry_rn_ds", "13-healthcare-rn.txt", "04-moloco-data-scientist.txt"),
    ("minimal_info", "06-minimal.txt", "08-synthetic-clean.txt"),
]


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _canon_set(items: list[str]) -> set[str]:
    return {canonicalize_skill(s) for s in items if s}


def _word_or_stem_in_text(word: str, text: str) -> bool:
    """True if the word, or a 5+ char prefix of it, appears in text.

    Tolerates verb-form variation ('precepting' vs 'precept'), plural
    vs singular ('protocols' vs 'protocol'), and -tion endings without
    falling back to a real stemmer.
    """
    word = word.lower()
    if len(word) < 4:
        return word in text
    if word in text:
        return True
    # Prefer the longest stem first to keep matches specific.
    for stem_len in range(len(word) - 1, 4, -1):
        if word[:stem_len] in text:
            return True
    return False


def _score_grounding(
    highlighted: list[str],
    profile_skills: list[str],
    resume_text: str,
) -> tuple[float, list[str]]:
    """% of highlighted_skills that can be defended from the resume.

    A skill is grounded if ANY of:
      - It is in candidate_profile.skills (canonical match), OR
      - The full skill phrase appears in resume_text, OR
      - At least HALF of its content words (or 5-char stems) appear
        in resume_text.

    The half-coverage rule lets us catch real fabrication ('Quantum
    cryptography' on a healthcare RN resume) without false-flagging
    abstract framings the LLM legitimately produces from bullets
    ('Process improvement' from 'evidence-based protocol improvement').
    """
    if not highlighted:
        return 1.0, ["no highlighted_skills produced"]
    profile_canon = _canon_set(profile_skills)
    resume_lower = (resume_text or "").lower()
    fabricated: list[str] = []
    for skill in highlighted:
        canonical = canonicalize_skill(skill)
        if canonical in profile_canon:
            continue
        if canonical and canonical in resume_lower:
            continue
        if skill.lower() in resume_lower:
            continue
        words = [w for w in re.split(r"\W+", canonical) if len(w) > 2]
        if not words:
            fabricated.append(skill)
            continue
        matched_words = sum(1 for w in words if _word_or_stem_in_text(w, resume_lower))
        if matched_words / len(words) >= 0.5:
            continue
        fabricated.append(skill)
    score = (len(highlighted) - len(fabricated)) / len(highlighted)
    notes = [f"fabricated: {s}" for s in fabricated]
    return score, notes


def _score_gap_avoidance(
    highlighted: list[str], missing_hard_skills: list[str]
) -> tuple[float, list[str]]:
    """Penalize highlighted skills that are in fit_analysis.missing_hard_skills.

    These are skills the JD requires but the profile lacks; promoting
    them is gap-claiming and the review agent will flag them later.
    """
    if not highlighted:
        return 1.0, []
    missing_canon = _canon_set(missing_hard_skills)
    if not missing_canon:
        return 1.0, []
    promoted_gaps: list[str] = []
    for skill in highlighted:
        if canonicalize_skill(skill) in missing_canon:
            promoted_gaps.append(skill)
    score = (len(highlighted) - len(promoted_gaps)) / len(highlighted)
    notes = [f"gap-claimed: {s}" for s in promoted_gaps]
    return score, notes


def _score_jd_alignment(
    highlighted: list[str], matched_hard_skills: list[str]
) -> tuple[float, list[str]]:
    """How many of the FitAnalysis matched_hard_skills appear in the
    agent's highlighted_skills.

    Measures whether the agent actually surfaces the JD-aligned skills
    rather than producing a generic skill list.
    """
    if not matched_hard_skills:
        # No JD-side hard skills detected; can't evaluate alignment.
        return 1.0, ["no matched_hard_skills to align against"]
    highlighted_canon = _canon_set(highlighted)
    matched_canon = _canon_set(matched_hard_skills)
    intersection = highlighted_canon & matched_canon
    # Cap denominator at 4 — we only have room for ~4-8 highlighted
    # skills, so requiring all matches to surface is unfair.
    target = min(len(matched_canon), 4)
    score = min(1.0, len(intersection) / max(target, 1))
    notes = []
    if score < 1.0:
        not_surfaced = [s for s in matched_hard_skills if canonicalize_skill(s) not in highlighted_canon]
        if not_surfaced:
            notes.append("matched but not surfaced: " + ", ".join(not_surfaced[:4]))
    return score, notes


def _count_in_range(value: int, low: int, high: int, soft_low: int, soft_high: int) -> float:
    if low <= value <= high:
        return 1.0
    if soft_low <= value <= soft_high:
        return 0.5
    return 0.0


def _score_format(output: TailoringAgentOutput) -> tuple[float, list[str]]:
    notes: list[str] = []
    bullets_n = len(output.rewritten_bullets)
    skills_n = len(output.highlighted_skills)
    themes_n = len(output.cover_letter_themes)

    bullets_score = _count_in_range(bullets_n, 3, 5, 2, 6)
    skills_score = _count_in_range(skills_n, 4, 8, 3, 9)
    themes_score = _count_in_range(themes_n, 2, 4, 1, 5)

    if bullets_score < 1.0:
        notes.append(f"bullets count {bullets_n} outside [3,5]")
    if skills_score < 1.0:
        notes.append(f"skills count {skills_n} outside [4,8]")
    if themes_score < 1.0:
        notes.append(f"themes count {themes_n} outside [2,4]")

    return (bullets_score + skills_score + themes_score) / 3.0, notes


def _score_non_empty(output: TailoringAgentOutput) -> tuple[float, list[str]]:
    notes: list[str] = []
    fields = {
        "professional_summary": bool((output.professional_summary or "").strip()),
        "rewritten_bullets": bool(output.rewritten_bullets),
        "highlighted_skills": bool(output.highlighted_skills),
        "cover_letter_themes": bool(output.cover_letter_themes),
    }
    populated = sum(1 for v in fields.values() if v)
    for name, ok in fields.items():
        if not ok:
            notes.append(f"empty: {name}")
    return populated / len(fields), notes


_SENTENCE_SPLIT_RE = re.compile(r"[.!?]+\s+")


def _score_summary_sentence_count(summary: str) -> tuple[float, list[str]]:
    text = (summary or "").strip()
    if not text:
        return 0.0, ["empty summary"]
    # Strip a trailing terminator before splitting so "X. Y. Z." reads
    # as 3 sentences not 4.
    if text[-1] in ".!?":
        text = text[:-1]
    parts = [p for p in _SENTENCE_SPLIT_RE.split(text) if p.strip()]
    n = len(parts) if parts else 1
    notes = []
    if 2 <= n <= 5:
        return 1.0, notes
    notes.append(f"sentence count {n} outside [2,5]")
    if 1 <= n <= 6:
        return 0.5, notes
    return 0.0, notes


# ---------------------------------------------------------------------------
# Per-pair scorecard
# ---------------------------------------------------------------------------


SECTION_WEIGHTS = {
    "grounding": 1.5,
    "gap_avoidance": 1.5,
    "jd_alignment": 1.0,
    "format_compliance": 0.5,
    "non_empty": 0.5,
    "summary_sentence_count": 0.5,
}


def score_output(
    output: TailoringAgentOutput,
    profile_skills: list[str],
    matched_hard_skills: list[str],
    missing_hard_skills: list[str],
    resume_text: str,
) -> dict:
    grounding_score, grounding_notes = _score_grounding(
        output.highlighted_skills, profile_skills, resume_text
    )
    gap_score, gap_notes = _score_gap_avoidance(
        output.highlighted_skills, missing_hard_skills
    )
    jd_score, jd_notes = _score_jd_alignment(
        output.highlighted_skills, matched_hard_skills
    )
    format_score, format_notes = _score_format(output)
    non_empty_score, non_empty_notes = _score_non_empty(output)
    summary_score, summary_notes = _score_summary_sentence_count(output.professional_summary)

    sections = {
        "grounding": (grounding_score, grounding_notes),
        "gap_avoidance": (gap_score, gap_notes),
        "jd_alignment": (jd_score, jd_notes),
        "format_compliance": (format_score, format_notes),
        "non_empty": (non_empty_score, non_empty_notes),
        "summary_sentence_count": (summary_score, summary_notes),
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
            "professional_summary": output.professional_summary,
            "rewritten_bullets": list(output.rewritten_bullets),
            "highlighted_skills": list(output.highlighted_skills),
            "cover_letter_themes": list(output.cover_letter_themes),
        },
    }


# ---------------------------------------------------------------------------
# Mode runners
# ---------------------------------------------------------------------------


def _build_inputs(resume_path: Path, jd_path: Path):
    resume_text = resume_path.read_text(encoding="utf-8")
    jd_text = jd_path.read_text(encoding="utf-8")
    document = ResumeDocument(text=resume_text, filetype="TXT", source=str(resume_path))
    candidate_profile = build_candidate_profile_from_resume_auto(document)
    job_description = build_job_description_from_text(jd_text)
    fit_analysis = build_fit_analysis(candidate_profile, job_description)
    tailored_draft = build_tailored_resume_draft(
        candidate_profile,
        job_description,
        fit_analysis,
    )
    return candidate_profile, job_description, fit_analysis, tailored_draft


def _run_deterministic(candidate_profile, job_description, fit_analysis, tailored_draft) -> TailoringAgentOutput:
    agent = TailoringAgent(openai_service=None)
    return agent.run(candidate_profile, job_description, fit_analysis, tailored_draft)


def _run_llm(openai_service, candidate_profile, job_description, fit_analysis, tailored_draft) -> TailoringAgentOutput | None:
    if openai_service is None or not openai_service.is_available():
        return None
    agent = TailoringAgent(openai_service=openai_service)
    try:
        return agent.run(candidate_profile, job_description, fit_analysis, tailored_draft)
    except Exception as exc:
        print(f"  WARNING: LLM run failed: {type(exc).__name__}: {exc}")
        return None


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _format_score(value: float) -> str:
    if value >= 0.95:
        return f"[ok ] {value:.2f}"
    if value >= 0.7:
        return f"[~  ] {value:.2f}"
    return f"[FAIL] {value:.2f}"


def _print_scorecard(label: str, mode_results: dict[str, dict | None]):
    print()
    print(f"=== {label} ===")
    sections = list(SECTION_WEIGHTS.keys())
    modes = list(mode_results.keys())
    header = f"{'Section':<25}" + "".join(f"{m:<18}" for m in modes)
    print(header)
    print("-" * len(header))
    for section in sections:
        row = f"{section:<25}"
        for mode in modes:
            data = mode_results[mode]
            if data is None:
                row += f"{'(skipped)':<18}"
                continue
            score = data["sections"][section]["score"]
            row += f"{_format_score(score):<18}"
        print(row)
    print("-" * len(header))
    overall_row = f"{'OVERALL':<25}"
    for mode in modes:
        data = mode_results[mode]
        if data is None:
            overall_row += f"{'(skipped)':<18}"
            continue
        overall_row += f"{_format_score(data['overall']):<18}"
    print(overall_row)

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


def _print_summary(per_pair: list[dict]):
    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    modes = list(per_pair[0]["modes"].keys()) if per_pair else []
    header = f"{'Pair':<32}" + "".join(f"{m:<18}" for m in modes)
    print(header)
    print("-" * len(header))
    for entry in per_pair:
        row = f"{entry['label']:<32}"
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
            for entry in per_pair
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
        help="Also run the LLM mode (costs API tokens).",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=None,
        help="Write the full result table to this JSON path.",
    )
    args = parser.parse_args()

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

    per_pair: list[dict] = []
    for label, resume_filename, jd_filename in FIXTURE_PAIRS:
        resume_path = RESUMES_DIR / resume_filename
        jd_path = JDS_DIR / jd_filename
        if not resume_path.exists():
            print(f"SKIP {label}: missing resume {resume_filename}")
            continue
        if not jd_path.exists():
            print(f"SKIP {label}: missing JD {jd_filename}")
            continue

        candidate_profile, job_description, fit_analysis, tailored_draft = _build_inputs(
            resume_path, jd_path
        )

        deterministic_output = _run_deterministic(
            candidate_profile, job_description, fit_analysis, tailored_draft
        )
        deterministic_score = score_output(
            deterministic_output,
            candidate_profile.skills,
            fit_analysis.matched_hard_skills,
            fit_analysis.missing_hard_skills,
            candidate_profile.resume_text,
        )

        llm_score = None
        if openai_service is not None:
            llm_output = _run_llm(
                openai_service,
                candidate_profile,
                job_description,
                fit_analysis,
                tailored_draft,
            )
            if llm_output is not None:
                llm_score = score_output(
                    llm_output,
                    candidate_profile.skills,
                    fit_analysis.matched_hard_skills,
                    fit_analysis.missing_hard_skills,
                    candidate_profile.resume_text,
                )

        modes = {
            "deterministic": deterministic_score,
            "llm_only": llm_score,
        }
        _print_scorecard(label, modes)
        per_pair.append(
            {
                "label": label,
                "resume": resume_filename,
                "jd": jd_filename,
                "fit_analysis": {
                    "overall_score": fit_analysis.overall_score,
                    "readiness_label": fit_analysis.readiness_label,
                    "matched_hard_skills": fit_analysis.matched_hard_skills,
                    "missing_hard_skills": fit_analysis.missing_hard_skills,
                },
                "modes": modes,
            }
        )

    _print_summary(per_pair)

    if args.json:
        args.json.write_text(json.dumps(per_pair, indent=2), encoding="utf-8")
        print(f"\nWrote full scorecard to {args.json}")


if __name__ == "__main__":
    main()
