"""Tier-3 CoverLetterAgent quality runner.

CoverLetterAgent is the last agent in the workflow. It's gated in
production: orchestrator only runs it when review_output.approved
is True. The output ships verbatim into the cover_letter artifact
that the user downloads.

Different voice rules from the resume agents — cover letters are
prose in first person, not pronoun-free bullet lists. So this
runner tests:

- first_person_voice (2.0): the body uses 'I' / 'my' (positive
  signal), AND has no third-person pronouns ('he', 'his', 'she',
  'her'), no 'the candidate' / 'this candidate' label, no full-
  name self-reference in the body. Mirrors the agent's
  _contains_third_person_self_reference post-check.
- body_grounding (2.0): each body paragraph's content words appear
  via stem-match in (resume_text + JD_text). Cover letters
  legitimately mix profile claims with role framing.
- format_compliance (1.0): opening 2-4 sentences, body 1-3
  paragraphs, closing 1-2 sentences (matches the prompt contract).
- structure (0.5): non-empty greeting / signoff / signature_name.
- signature_name_correct (0.5): signature_name matches
  candidate_profile.full_name (case-insensitive). The body must
  not contain the name, but the signature must.
- no_bullet_bleed (0.5): paragraphs don't start with '-', '*', '•',
  or '1.' / numbered list markers. Cover letters are prose; bullet
  bleed reads like draft notes shipped to the recruiter.

Six fixture pairs (same as the other Tier-3 runners). Each mode is
tested with matching upstream — det runner gets det tailoring +
det review, LLM runner gets LLM tailoring + LLM review (the
production paths).

Usage:
    python -m tests.quality.cover_letter_quality_runner
    python -m tests.quality.cover_letter_quality_runner --include-llm
    python -m tests.quality.cover_letter_quality_runner --include-llm --json out.json

Costs API tokens with --include-llm.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from src.agents.cover_letter_agent import CoverLetterAgent
from src.agents.resume_generation_agent import ResumeGenerationAgent
from src.agents.review_agent import ReviewAgent
from src.agents.tailoring_agent import TailoringAgent
from src.schemas import (
    CandidateProfile,
    CoverLetterAgentOutput,
    ResumeDocument,
    ResumeGenerationAgentOutput,
    ReviewAgentOutput,
    TailoringAgentOutput,
)
from src.services.fit_service import build_fit_analysis
from src.services.job_service import build_job_description_from_text
from src.services.profile_service import build_candidate_profile_from_resume_auto
from src.services.tailoring_service import build_tailored_resume_draft

from tests.quality.tailoring_quality_runner import _word_or_stem_in_text


RESUMES_DIR = Path(__file__).parent / "sample_resumes"
JDS_DIR = Path(__file__).parent / "sample_jds"


FIXTURE_PAIRS: list[tuple[str, str, str]] = [
    ("strong_fit_data_eng", "02-midcareer-tech.txt", "07-placer-big-data-engineer.txt"),
    ("gaps_junior_on_senior", "04-bootcamp-grad.txt", "04-moloco-data-scientist.txt"),
    ("gaps_career_switcher", "05-career-switcher.txt", "01-narvar-senior-ai-engineer.txt"),
    ("strong_fit_senior_ai", "11-senior-detailed.txt", "01-narvar-senior-ai-engineer.txt"),
    ("wrong_industry_rn_ds", "13-healthcare-rn.txt", "04-moloco-data-scientist.txt"),
    ("minimal_info", "06-minimal.txt", "08-synthetic-clean.txt"),
]


# Mirrors src.agents.cover_letter_agent regexes so we score the same
# property the agent's post-check enforces.
_THIRD_PERSON_RE = re.compile(r"\b(he|his|him|she|her)\b", re.IGNORECASE)
_CANDIDATE_LABEL_RE = re.compile(r"\b(the candidate|this candidate)\b", re.IGNORECASE)
_FIRST_PERSON_RE = re.compile(r"\b(i|i'm|i've|i'd|i'll|my|me|mine)\b", re.IGNORECASE)
_BULLET_PREFIX_RE = re.compile(r"^\s*([-*•·▪]|\d+\.)\s+")
_SENTENCE_SPLIT_RE = re.compile(r"[.!?]+\s+")


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _content_words(text: str) -> list[str]:
    return [w for w in re.split(r"\W+", (text or "").lower()) if len(w) > 3]


def _body_text(output: CoverLetterAgentOutput) -> str:
    """Combine the body-relevant blocks (opening, body paragraphs,
    closing) into one searchable string. Excludes greeting and
    signature, since those legitimately contain the candidate name
    or generic salutation phrasing.
    """
    blocks = [
        output.opening_paragraph,
        *output.body_paragraphs,
        output.closing_paragraph,
    ]
    return " ".join(b for b in blocks if (b or "").strip())


def _score_first_person_voice(
    output: CoverLetterAgentOutput, candidate_profile: CandidateProfile
) -> tuple[float, list[str]]:
    body = _body_text(output)
    if not body:
        return 0.0, ["empty letter body"]

    notes = []
    score = 1.0

    has_first_person = bool(_FIRST_PERSON_RE.search(body))
    if not has_first_person:
        score -= 0.5
        notes.append("no first-person pronouns (I/my/me) in body — letter not in candidate's voice")

    third_person_match = _THIRD_PERSON_RE.search(body)
    if third_person_match:
        score -= 0.5
        notes.append(f"third-person pronoun in body: '{third_person_match.group(0)}'")

    if _CANDIDATE_LABEL_RE.search(body):
        score -= 0.5
        notes.append("'the candidate' / 'this candidate' label in body")

    candidate_name = (candidate_profile.full_name or "").strip()
    if candidate_name and candidate_name.lower() in body.lower():
        score -= 0.5
        notes.append(f"full-name self-reference in body: '{candidate_name}'")

    return max(0.0, score), notes


def _paragraph_is_grounded(paragraph: str, grounded_text: str) -> bool:
    words = _content_words(paragraph)
    if not words:
        return True
    matched = sum(1 for w in words if _word_or_stem_in_text(w, grounded_text))
    return matched / len(words) >= 0.5


def _score_body_grounding(
    output: CoverLetterAgentOutput, resume_text: str, jd_text: str
) -> tuple[float, list[str]]:
    paragraphs = [p for p in output.body_paragraphs if (p or "").strip()]
    if not paragraphs:
        return 0.0, ["no body paragraphs produced"]
    grounded_text = ((resume_text or "") + " " + (jd_text or "")).lower()
    weak = [p for p in paragraphs if not _paragraph_is_grounded(p, grounded_text)]
    score = (len(paragraphs) - len(weak)) / len(paragraphs)
    notes = [f"weak grounding: '{p[:80]}...'" for p in weak]
    return score, notes


def _count_sentences(text: str) -> int:
    text = (text or "").strip()
    if not text:
        return 0
    if text[-1] in ".!?":
        text = text[:-1]
    parts = [p for p in _SENTENCE_SPLIT_RE.split(text) if p.strip()]
    return len(parts) if parts else 1


def _count_in_range(value: int, low: int, high: int, soft_low: int, soft_high: int) -> float:
    if low <= value <= high:
        return 1.0
    if soft_low <= value <= soft_high:
        return 0.5
    return 0.0


def _score_format(output: CoverLetterAgentOutput) -> tuple[float, list[str]]:
    notes = []
    opening_n = _count_sentences(output.opening_paragraph)
    body_n = len([p for p in output.body_paragraphs if (p or "").strip()])
    closing_n = _count_sentences(output.closing_paragraph)

    opening_score = _count_in_range(opening_n, 2, 4, 1, 5)
    body_score = _count_in_range(body_n, 1, 3, 1, 4)
    closing_score = _count_in_range(closing_n, 1, 2, 1, 3)

    if opening_score < 1.0:
        notes.append(f"opening sentence count {opening_n} outside [2,4]")
    if body_score < 1.0:
        notes.append(f"body paragraph count {body_n} outside [1,3]")
    if closing_score < 1.0:
        notes.append(f"closing sentence count {closing_n} outside [1,2]")

    return (opening_score + body_score + closing_score) / 3.0, notes


def _score_structure(output: CoverLetterAgentOutput) -> tuple[float, list[str]]:
    notes = []
    if not (output.greeting or "").strip():
        notes.append("empty greeting")
    if not (output.signoff or "").strip():
        notes.append("empty signoff")
    if not (output.signature_name or "").strip():
        notes.append("empty signature_name")
    if notes:
        return 0.0, notes
    return 1.0, []


def _score_signature_name(
    output: CoverLetterAgentOutput, candidate_profile: CandidateProfile
) -> tuple[float, list[str]]:
    expected = (candidate_profile.full_name or "").strip().lower()
    actual = (output.signature_name or "").strip().lower()
    if not expected:
        return 1.0, ["candidate has no full_name to validate against"]
    if expected == actual:
        return 1.0, []
    if expected in actual or actual in expected:
        return 0.7, [f"signature name partial match: '{output.signature_name}' vs '{candidate_profile.full_name}'"]
    return 0.0, [f"signature name mismatch: '{output.signature_name}' vs expected '{candidate_profile.full_name}'"]


def _score_no_bullet_bleed(output: CoverLetterAgentOutput) -> tuple[float, list[str]]:
    paragraphs = [output.opening_paragraph, *output.body_paragraphs, output.closing_paragraph]
    bullet_starts = [p for p in paragraphs if (p or "").strip() and _BULLET_PREFIX_RE.match(p)]
    if not bullet_starts:
        return 1.0, []
    return 0.0, [f"bullet-style prefix in paragraph: '{p[:60]}...'" for p in bullet_starts]


SECTION_WEIGHTS = {
    "first_person_voice": 2.0,
    "body_grounding": 2.0,
    "format_compliance": 1.0,
    "structure": 0.5,
    "signature_name_correct": 0.5,
    "no_bullet_bleed": 0.5,
}


def score_output(
    output: CoverLetterAgentOutput,
    candidate_profile: CandidateProfile,
    resume_text: str,
    jd_text: str,
) -> dict:
    voice_score, voice_notes = _score_first_person_voice(output, candidate_profile)
    grounding_score, grounding_notes = _score_body_grounding(output, resume_text, jd_text)
    format_score, format_notes = _score_format(output)
    structure_score, structure_notes = _score_structure(output)
    sig_score, sig_notes = _score_signature_name(output, candidate_profile)
    bullet_score, bullet_notes = _score_no_bullet_bleed(output)

    sections = {
        "first_person_voice": (voice_score, voice_notes),
        "body_grounding": (grounding_score, grounding_notes),
        "format_compliance": (format_score, format_notes),
        "structure": (structure_score, structure_notes),
        "signature_name_correct": (sig_score, sig_notes),
        "no_bullet_bleed": (bullet_score, bullet_notes),
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
            "greeting": output.greeting,
            "opening_paragraph": output.opening_paragraph,
            "body_paragraphs": list(output.body_paragraphs),
            "closing_paragraph": output.closing_paragraph,
            "signoff": output.signoff,
            "signature_name": output.signature_name,
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
    return candidate_profile, job_description, fit_analysis, tailored_draft, jd_text


def _build_upstream(
    openai_service,
    candidate_profile,
    job_description,
    fit_analysis,
    tailored_draft,
) -> tuple[TailoringAgentOutput, ReviewAgentOutput, ResumeGenerationAgentOutput]:
    """Run the upstream chain (Tailoring -> Review -> ResumeGeneration)
    so the input to CoverLetterAgent matches the production shape.
    Uses the same openai_service throughout — in production the
    orchestrator never mixes modes."""
    tailoring = TailoringAgent(openai_service=openai_service).run(
        candidate_profile, job_description, fit_analysis, tailored_draft
    )
    review = ReviewAgent(openai_service=openai_service).run(
        candidate_profile, job_description, fit_analysis, tailored_draft, tailoring
    )
    final_tailoring = review.corrected_tailoring or tailoring
    resume_gen = ResumeGenerationAgent(openai_service=openai_service).run(
        candidate_profile,
        job_description,
        fit_analysis,
        tailored_draft,
        final_tailoring,
        review,
    )
    return final_tailoring, review, resume_gen


def _run_agent(
    openai_service,
    candidate_profile,
    job_description,
    fit_analysis,
    tailored_draft,
    final_tailoring,
    review,
    resume_gen,
) -> CoverLetterAgentOutput | None:
    agent = CoverLetterAgent(openai_service=openai_service)
    try:
        return agent.run(
            candidate_profile,
            job_description,
            fit_analysis,
            tailored_draft,
            final_tailoring,
            review,
            resume_gen,
        )
    except Exception as exc:
        print(f"  WARNING: agent run failed: {type(exc).__name__}: {exc}")
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

        candidate_profile, job_description, fit_analysis, tailored_draft, jd_text = (
            _build_inputs(resume_path, jd_path)
        )

        # Build matching upstream per mode (production paths never
        # mix det/LLM so we shouldn't either).
        det_tailoring, det_review, det_resume_gen = _build_upstream(
            None, candidate_profile, job_description, fit_analysis, tailored_draft
        )
        deterministic_output = _run_agent(
            None,
            candidate_profile,
            job_description,
            fit_analysis,
            tailored_draft,
            det_tailoring,
            det_review,
            det_resume_gen,
        )
        deterministic_score = (
            score_output(
                deterministic_output,
                candidate_profile,
                candidate_profile.resume_text,
                jd_text,
            )
            if deterministic_output
            else None
        )

        llm_score = None
        if openai_service is not None:
            llm_tailoring, llm_review, llm_resume_gen = _build_upstream(
                openai_service,
                candidate_profile,
                job_description,
                fit_analysis,
                tailored_draft,
            )
            llm_output = _run_agent(
                openai_service,
                candidate_profile,
                job_description,
                fit_analysis,
                tailored_draft,
                llm_tailoring,
                llm_review,
                llm_resume_gen,
            )
            if llm_output is not None:
                llm_score = score_output(
                    llm_output,
                    candidate_profile,
                    candidate_profile.resume_text,
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
                "review_approved_det": det_review.approved,
                "review_approved_llm": (
                    llm_review.approved if openai_service is not None else None
                ),
                "modes": modes,
            }
        )

    _print_summary(per_pair)

    if args.json:
        args.json.write_text(json.dumps(per_pair, indent=2), encoding="utf-8")
        print(f"\nWrote full scorecard to {args.json}")


if __name__ == "__main__":
    main()
