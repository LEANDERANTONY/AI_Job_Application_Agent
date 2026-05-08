"""Tier-3 ResumeGenerationAgent quality runner.

ResumeGenerationAgent is the last LLM stage in the resume pipeline:
it takes the (review-corrected) TailoringAgentOutput and produces the
final resume content fields (professional_summary, highlighted_skills,
experience_bullets, section_order). Its output flows directly into
the rendered resume markdown + PDF, so any failure here ships
verbatim to the user.

Six (resume, JD) fixture pairs covering the same regions as the
tailoring runner — strong fit, gap-heavy, wrong-industry, minimal
info. We run TailoringAgent + ReviewAgent first to produce a clean,
review-corrected input, then run ResumeGenerationAgent against that.

Six scoring dimensions weighted by failure-mode severity:

- bullet_grounding (2.0): each experience_bullet is defensible from
  candidate.resume_text (>=50% content-word stem match). Catches
  bullet fabrication — the highest-blast-radius failure since these
  bullets ship verbatim.
- voice_compliance (2.0): no first/third-person pronouns, no full-name
  self-reference. Mirrors the agent's own _contains_self_reference
  post-check. The agent should already fall back to deterministic
  when violated; this verifies the fallback fires.
- format_compliance (1.0): bullets [3,6], skills [4,8], summary
  sentences [2,5].
- section_order_quality is NOT scored here. The agent's section_order
  field is ignored by resume_builder._resolve_section_order — the
  deterministic compute_section_order(profile) is authoritative
  because the decision is purely structural and the LLM's emitted
  order doesn't track candidate level reliably. End-to-end ordering
  behavior is covered in test_resume_builder.
- skill_consistency (0.5): highlighted_skills overlap with the input
  tailoring_output.highlighted_skills at >= 40%. Catches skills
  drifting from the review-approved set.
- summary_groundedness (0.5): professional_summary content words
  appear in resume_text (stem match, >= 50%).

Two modes are compared:
- deterministic: ResumeGenerationAgent fallback (echoes tailoring
  + tailored_draft + fit_analysis). Structurally safe baseline.
- llm_only: gpt-5.4 (high-trust model from OPENAI_MODEL_ROUTING).

Usage:
    python -m tests.quality.resume_generation_quality_runner
    python -m tests.quality.resume_generation_quality_runner --include-llm
    python -m tests.quality.resume_generation_quality_runner --include-llm --json out.json

Costs API tokens with --include-llm.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from src.agents.resume_generation_agent import ResumeGenerationAgent
from src.agents.review_agent import ReviewAgent
from src.agents.tailoring_agent import TailoringAgent
from src.schemas import (
    CandidateProfile,
    ResumeDocument,
    ResumeGenerationAgentOutput,
    TailoringAgentOutput,
)
from src.services.fit_service import build_fit_analysis
from src.services.job_service import build_job_description_from_text
from src.services.profile_service import build_candidate_profile_from_resume_auto
from src.services.tailoring_service import build_tailored_resume_draft

from tests.quality.tailoring_quality_runner import _word_or_stem_in_text


RESUMES_DIR = Path(__file__).parent / "sample_resumes"
JDS_DIR = Path(__file__).parent / "sample_jds"


# Same shape as tailoring_quality_runner so the two scorecards are
# directly comparable.
FIXTURE_PAIRS: list[tuple[str, str, str]] = [
    ("strong_fit_data_eng", "02-midcareer-tech.txt", "07-placer-big-data-engineer.txt"),
    ("gaps_junior_on_senior", "04-bootcamp-grad.txt", "04-moloco-data-scientist.txt"),
    ("gaps_career_switcher", "05-career-switcher.txt", "01-narvar-senior-ai-engineer.txt"),
    ("strong_fit_senior_ai", "11-senior-detailed.txt", "01-narvar-senior-ai-engineer.txt"),
    ("wrong_industry_rn_ds", "13-healthcare-rn.txt", "04-moloco-data-scientist.txt"),
    ("minimal_info", "06-minimal.txt", "08-synthetic-clean.txt"),
]


# Mirrors src.agents.resume_generation_agent._RESUME_SELF_REFERENCE_RE
# so we score the same property the agent's own post-check enforces.
_RESUME_SELF_REFERENCE_RE = re.compile(
    r"\b(i|me|my|mine|myself|he|his|him|himself|she|her|hers|herself|the candidate|this candidate)\b",
    re.IGNORECASE,
)


_SENTENCE_SPLIT_RE = re.compile(r"[.!?]+\s+")


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _content_words(text: str) -> list[str]:
    return [w for w in re.split(r"\W+", (text or "").lower()) if len(w) > 3]


def _bullet_is_grounded(bullet: str, resume_text_lower: str) -> bool:
    """A bullet is grounded if >=50% of its content words (4+ chars)
    appear in resume_text via stem-match."""
    words = _content_words(bullet)
    if not words:
        return True  # empty bullet — let format_compliance catch it
    matched = sum(1 for w in words if _word_or_stem_in_text(w, resume_text_lower))
    return matched / len(words) >= 0.5


def _score_bullet_grounding(
    bullets: list[str], resume_text: str
) -> tuple[float, list[str]]:
    if not bullets:
        return 0.0, ["no experience_bullets produced"]
    resume_lower = (resume_text or "").lower()
    fabricated = [b for b in bullets if not _bullet_is_grounded(b, resume_lower)]
    score = (len(bullets) - len(fabricated)) / len(bullets)
    notes = [f"low-evidence bullet: '{b[:80]}...'" for b in fabricated]
    return score, notes


def _score_voice_compliance(
    output: ResumeGenerationAgentOutput, candidate_profile: CandidateProfile
) -> tuple[float, list[str]]:
    text_blocks = [output.professional_summary, *output.experience_bullets]
    combined = " ".join(b for b in text_blocks if (b or "").strip())
    if not combined:
        return 1.0, []
    notes = []
    candidate_name = (candidate_profile.full_name or "").strip()
    if candidate_name and candidate_name.lower() in combined.lower():
        notes.append(f"full-name self-reference: '{candidate_name}'")
    pronoun_match = _RESUME_SELF_REFERENCE_RE.search(combined)
    if pronoun_match:
        notes.append(f"pronoun/self-ref violation: '{pronoun_match.group(0)}'")
    if not notes:
        return 1.0, []
    return 0.0, notes


def _count_in_range(value: int, low: int, high: int, soft_low: int, soft_high: int) -> float:
    if low <= value <= high:
        return 1.0
    if soft_low <= value <= soft_high:
        return 0.5
    return 0.0


def _score_format(output: ResumeGenerationAgentOutput) -> tuple[float, list[str]]:
    notes = []
    bullets_n = len(output.experience_bullets)
    skills_n = len(output.highlighted_skills)
    summary = (output.professional_summary or "").strip()
    if summary and summary[-1] in ".!?":
        summary = summary[:-1]
    sentences_n = len([p for p in _SENTENCE_SPLIT_RE.split(summary) if p.strip()]) if summary else 0

    bullets_score = _count_in_range(bullets_n, 3, 6, 2, 7)
    skills_score = _count_in_range(skills_n, 4, 8, 3, 9)
    summary_score = _count_in_range(sentences_n, 2, 5, 1, 6)

    if bullets_score < 1.0:
        notes.append(f"bullets count {bullets_n} outside [3,6]")
    if skills_score < 1.0:
        notes.append(f"skills count {skills_n} outside [4,8]")
    if summary_score < 1.0:
        notes.append(f"summary sentence count {sentences_n} outside [2,5]")

    return (bullets_score + skills_score + summary_score) / 3.0, notes


def _canon_skill_set(items: list[str]) -> set[str]:
    return {(s or "").strip().lower() for s in items if (s or "").strip()}


def _score_skill_consistency(
    output: ResumeGenerationAgentOutput,
    tailoring_output: TailoringAgentOutput,
) -> tuple[float, list[str]]:
    expected = _canon_skill_set(tailoring_output.highlighted_skills)
    if not expected:
        return 1.0, ["no upstream skills to compare against"]
    agent_skills = _canon_skill_set(output.highlighted_skills)
    if not agent_skills:
        return 0.0, ["agent emitted no highlighted_skills"]
    overlap = expected & agent_skills
    coverage = len(overlap) / len(expected)
    if coverage >= 0.4:
        return 1.0, []
    notes = [
        f"skill drift from tailoring: only {len(overlap)}/{len(expected)} overlap "
        f"({coverage:.0%})"
    ]
    return coverage, notes


def _score_summary_groundedness(
    output: ResumeGenerationAgentOutput,
    resume_text: str,
    jd_text: str,
) -> tuple[float, list[str]]:
    """Tailored summaries legitimately mix profile claims (skills,
    employers) with JD framing (target role, JD-side keywords). A
    word is 'grounded' if it appears in EITHER the resume or the
    job description text.
    """
    summary = (output.professional_summary or "").strip()
    if not summary:
        return 0.0, ["empty summary"]
    words = _content_words(summary)
    if not words:
        return 0.5, ["summary has no scoreable content words"]
    grounded_text = ((resume_text or "") + " " + (jd_text or "")).lower()
    matched = sum(1 for w in words if _word_or_stem_in_text(w, grounded_text))
    coverage = matched / len(words)
    if coverage >= 0.5:
        return 1.0, []
    return coverage, [
        f"summary content-word coverage {coverage:.0%} below 50% "
        f"(across resume + JD vocabulary)"
    ]


SECTION_WEIGHTS = {
    "bullet_grounding": 2.0,
    "voice_compliance": 2.0,
    "format_compliance": 1.0,
    "skill_consistency": 0.5,
    "summary_groundedness": 0.5,
}


def score_output(
    output: ResumeGenerationAgentOutput,
    candidate_profile: CandidateProfile,
    tailoring_output: TailoringAgentOutput,
    jd_text: str = "",
) -> dict:
    bullet_grounding, bg_notes = _score_bullet_grounding(
        output.experience_bullets, candidate_profile.resume_text
    )
    voice_compliance, vc_notes = _score_voice_compliance(output, candidate_profile)
    format_compliance, fc_notes = _score_format(output)
    skill_consistency, sk_notes = _score_skill_consistency(output, tailoring_output)
    summary_groundedness, sg_notes = _score_summary_groundedness(
        output, candidate_profile.resume_text, jd_text
    )

    sections = {
        "bullet_grounding": (bullet_grounding, bg_notes),
        "voice_compliance": (voice_compliance, vc_notes),
        "format_compliance": (format_compliance, fc_notes),
        "skill_consistency": (skill_consistency, sk_notes),
        "summary_groundedness": (summary_groundedness, sg_notes),
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
            "highlighted_skills": list(output.highlighted_skills),
            "experience_bullets": list(output.experience_bullets),
            "section_order": list(output.section_order),
            "template_hint": output.template_hint,
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
        candidate_profile, job_description, fit_analysis
    )
    return candidate_profile, job_description, fit_analysis, tailored_draft


def _build_tailoring_input(
    openai_service, candidate_profile, job_description, fit_analysis, tailored_draft
) -> TailoringAgentOutput:
    """Run TailoringAgent + ReviewAgent so the input to
    ResumeGenerationAgent matches the production shape (review-
    corrected tailoring). When LLM is unavailable, falls back to the
    deterministic chain."""
    tailoring = TailoringAgent(openai_service=openai_service).run(
        candidate_profile, job_description, fit_analysis, tailored_draft
    )
    review = ReviewAgent(openai_service=openai_service).run(
        candidate_profile, job_description, fit_analysis, tailored_draft, tailoring
    )
    return review.corrected_tailoring or tailoring


def _run_deterministic(
    candidate_profile,
    job_description,
    fit_analysis,
    tailored_draft,
    tailoring_output,
) -> ResumeGenerationAgentOutput:
    agent = ResumeGenerationAgent(openai_service=None)
    return agent.run(
        candidate_profile,
        job_description,
        fit_analysis,
        tailored_draft,
        tailoring_output,
    )


def _run_llm(
    openai_service,
    candidate_profile,
    job_description,
    fit_analysis,
    tailored_draft,
    tailoring_output,
) -> ResumeGenerationAgentOutput | None:
    if openai_service is None or not openai_service.is_available():
        return None
    agent = ResumeGenerationAgent(openai_service=openai_service)
    try:
        return agent.run(
            candidate_profile,
            job_description,
            fit_analysis,
            tailored_draft,
            tailoring_output,
        )
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
        if not resume_path.exists() or not jd_path.exists():
            print(f"SKIP {label}: missing fixture")
            continue

        candidate_profile, job_description, fit_analysis, tailored_draft = _build_inputs(
            resume_path, jd_path
        )
        jd_text = jd_path.read_text(encoding="utf-8")

        # Build upstream tailoring with MATCHING mode for each test:
        # in production the orchestrator runs all agents with the same
        # openai_service, so the deterministic ResumeGenerationAgent
        # never sees LLM tailoring output and vice versa. Mixing them
        # exposes spurious failures (LLM-tailored bullets containing
        # the candidate's name flow into deterministic resume-gen,
        # which has no name filter — but this never happens in prod).
        det_tailoring_input = _build_tailoring_input(
            None,
            candidate_profile,
            job_description,
            fit_analysis,
            tailored_draft,
        )
        deterministic_output = _run_deterministic(
            candidate_profile,
            job_description,
            fit_analysis,
            tailored_draft,
            det_tailoring_input,
        )
        deterministic_score = score_output(
            deterministic_output,
            candidate_profile,
            det_tailoring_input,
            jd_text,
        )

        llm_score = None
        llm_tailoring_input = None
        if openai_service is not None:
            llm_tailoring_input = _build_tailoring_input(
                openai_service,
                candidate_profile,
                job_description,
                fit_analysis,
                tailored_draft,
            )
            llm_output = _run_llm(
                openai_service,
                candidate_profile,
                job_description,
                fit_analysis,
                tailored_draft,
                llm_tailoring_input,
            )
            if llm_output is not None:
                llm_score = score_output(
                    llm_output,
                    candidate_profile,
                    llm_tailoring_input,
                    jd_text,
                )

        modes = {"deterministic": deterministic_score, "llm_only": llm_score}
        _print_scorecard(label, modes)
        per_pair.append(
            {
                "label": label,
                "resume": resume_filename,
                "jd": jd_filename,
                "fit_score": fit_analysis.overall_score,
                "modes": modes,
                "tailoring_input_deterministic": {
                    "professional_summary": det_tailoring_input.professional_summary,
                    "highlighted_skills": list(det_tailoring_input.highlighted_skills),
                },
                "tailoring_input_llm": (
                    {
                        "professional_summary": llm_tailoring_input.professional_summary,
                        "highlighted_skills": list(llm_tailoring_input.highlighted_skills),
                    }
                    if llm_tailoring_input
                    else None
                ),
            }
        )

    _print_summary(per_pair)

    if args.json:
        args.json.write_text(json.dumps(per_pair, indent=2), encoding="utf-8")
        print(f"\nWrote full scorecard to {args.json}")


if __name__ == "__main__":
    main()
