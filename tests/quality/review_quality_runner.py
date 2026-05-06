"""Tier-3 ReviewAgent quality runner.

The ReviewAgent is the gatekeeper between TailoringAgent and the
downstream resume/cover-letter generators. Orchestrator promotes
``review_output.corrected_tailoring or tailoring_output`` as the
final tailoring output, so a wrongly-approved bad output ships
directly into the user's resume.

This runner tests two distinct properties:

1. **No false rejection on clean input.** When the input
   TailoringOutput is already grounded (e.g. the actual output from
   tailoring_quality_runner), ReviewAgent should approve and not
   make destructive changes.

2. **Detection + correction on adversarial input.** When we inject
   known fabrications (skills the candidate doesn't have, embellished
   seniority claims, wrong-industry skill claims), ReviewAgent should
   either flag them in grounding_issues OR remove them via
   corrected_tailoring. After taking the final output (corrected
   if present, original otherwise), the grounding score should rise
   back to clean levels.

Six scenarios:
- 3 clean:       feed real TailoringAgent output, expect approve + minimal change
- 3 adversarial: feed crafted bad output, expect detection + correction
  - skill fabrication (Spark/Hadoop on a candidate without them)
  - embellishment (claim '5+ years senior ML' on a career switcher)
  - wrong-industry (claim Python/ML/SQL on a healthcare RN)

Usage:
    python -m tests.quality.review_quality_runner
    python -m tests.quality.review_quality_runner --include-llm
    python -m tests.quality.review_quality_runner --include-llm --json out.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.agents.review_agent import ReviewAgent
from src.schemas import (
    ResumeDocument,
    ReviewAgentOutput,
    TailoredResumeDraft,
    TailoringAgentOutput,
)
from src.services.fit_service import build_fit_analysis
from src.services.job_service import build_job_description_from_text
from src.services.profile_service import build_candidate_profile_from_resume_auto
from src.services.tailoring_service import build_tailored_resume_draft

from tests.quality.tailoring_quality_runner import (
    _score_grounding,
    _score_gap_avoidance,
)


RESUMES_DIR = Path(__file__).parent / "sample_resumes"
JDS_DIR = Path(__file__).parent / "sample_jds"


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


# Each scenario carries:
# - label: short id
# - resume / jd: fixture filenames
# - input_tailoring: the TailoringAgentOutput we feed to ReviewAgent
# - mode: "clean" or "adversarial"
# - flagged_terms (adversarial only): substrings/keywords that should
#   appear in grounding_issues OR revision_requests OR be REMOVED from
#   the corrected output
# - removable_skills (adversarial only): skills that should be absent
#   from the final highlighted_skills (after corrections)


SCENARIOS = [
    {
        "label": "clean_strong_fit",
        "resume": "02-midcareer-tech.txt",
        "jd": "07-placer-big-data-engineer.txt",
        "mode": "clean",
        "input_tailoring": TailoringAgentOutput(
            professional_summary=(
                "Senior software engineer with 8+ years building high-throughput "
                "distributed systems at companies like Stripe and Cloudflare. "
                "Strong fit for big-data engineering work that requires Python, "
                "AWS, and GCP fluency plus production-scale platform thinking."
            ),
            rewritten_bullets=[
                "Re-architected Stripe's payment routing across 14 regions; cut p99 from 240ms to 45ms while doubling throughput.",
                "Owned the Cloudflare cache invalidation pipeline; eliminated a class of stale-data bugs reported by enterprise customers.",
                "Built the Atlassian Jira webhook delivery service handling 50M+ events/day.",
                "Led the migration that moved 3.2B legacy charges off MySQL onto Vitess.",
            ],
            highlighted_skills=["Python", "Go", "AWS", "GCP", "Kubernetes", "Distributed Systems"],
            cover_letter_themes=[
                "Anchor on production-scale distributed systems experience with measurable impact.",
                "Lead with platform-team leadership at Stripe and the Vitess migration story.",
                "Show willingness to learn the data-engineering specifics (Spark, Airflow) on top of strong systems fundamentals.",
            ],
        ),
    },
    {
        "label": "clean_career_switcher",
        "resume": "05-career-switcher.txt",
        "jd": "01-narvar-senior-ai-engineer.txt",
        "mode": "clean",
        "input_tailoring": TailoringAgentOutput(
            professional_summary=(
                "Mechanical engineer transitioning into ML engineering after a "
                "Master's in AI/ML and 4 years building automation tooling in "
                "automotive R&D. Capstone work on multi-modal deep learning "
                "and a production-style RAG system show grounded ML implementation."
            ),
            rewritten_bullets=[
                "Built a Python tool that auto-extracted intrusion metrics from LS-DYNA crash-simulation output, saving 15 hours/week.",
                "Designed a multi-modal AI pipeline integrating CECT imaging and serum biomarkers; trained ResNet-50 + tabular fusion model with AUROC 0.89.",
                "Designed a retrieval-augmented generation system using LangChain and ChromaDB; reduced policy-question-answering latency from 12s to 2.3s.",
            ],
            highlighted_skills=["Python", "PyTorch", "RAG", "LangChain", "Docker", "FastAPI"],
            cover_letter_themes=[
                "Lead with grounded ML capstone evidence and the production RAG system to show implementation depth.",
                "Frame the mechanical-engineering background as transferable rigor, not as direct ML production experience.",
            ],
        ),
    },
    {
        "label": "clean_rn",
        "resume": "13-healthcare-rn.txt",
        "jd": "04-moloco-data-scientist.txt",
        "mode": "clean",
        "input_tailoring": TailoringAgentOutput(
            professional_summary=(
                "Critical-care nurse with 9 years of bedside experience in "
                "surgical ICUs and a master's in nursing leadership. Strong "
                "operational and protocol-improvement track record but no "
                "current data-science or programming experience."
            ),
            rewritten_bullets=[
                "Directed a 40-bed surgical ICU during 16 of 28 weekly shifts at 92% census.",
                "Led the rollout of an early-mobility protocol associated with a 14% drop in ventilator days across 6 quarters.",
                "Co-authored the unit's revised SBAR hand-off template adopted hospital-wide in 2019.",
            ],
            highlighted_skills=["Critical-care nursing", "Nursing leadership", "Protocol improvement", "SBAR hand-off communication"],
            cover_letter_themes=[
                "Be transparent that this is a hard pivot; lead with operational rigor and rapid-learning evidence rather than claiming data-science skills.",
                "Highlight protocol-improvement work as transferable systems-thinking.",
            ],
        ),
    },
    {
        "label": "adv_skill_fabrication",
        "resume": "02-midcareer-tech.txt",
        "jd": "07-placer-big-data-engineer.txt",
        "mode": "adversarial",
        "input_tailoring": TailoringAgentOutput(
            professional_summary=(
                "Senior software engineer with 8+ years building high-throughput "
                "distributed systems at Stripe and Cloudflare."
            ),
            rewritten_bullets=[
                "Re-architected Stripe's payment routing; cut p99 from 240ms to 45ms.",
                "Built ETL pipelines on Apache Spark and Hadoop processing PB-scale data.",
                "Owned the Airflow DAG infrastructure for the analytics platform.",
            ],
            # Spark, Hadoop, Airflow, Snowflake are in this candidate's
            # missing_hard_skills (resume mentions none of them).
            highlighted_skills=["Python", "Go", "AWS", "GCP", "Apache Spark", "Hadoop", "Airflow", "Snowflake"],
            cover_letter_themes=[
                "Lead with PB-scale Spark + Hadoop expertise.",
                "Show end-to-end Snowflake warehouse migration story.",
            ],
        ),
        # We expect ReviewAgent to either flag these in grounding_issues
        # or remove them from corrected_tailoring.highlighted_skills.
        "removable_skills": ["Apache Spark", "Hadoop", "Airflow", "Snowflake"],
        "flagged_terms": ["spark", "hadoop", "airflow", "snowflake"],
    },
    {
        "label": "adv_embellishment",
        "resume": "05-career-switcher.txt",
        "jd": "01-narvar-senior-ai-engineer.txt",
        "mode": "adversarial",
        "input_tailoring": TailoringAgentOutput(
            # Career switcher with 0 years ML production. Resume says
            # 'transitioning into AI/ML' and lists capstone projects.
            # This summary blatantly inflates that.
            professional_summary=(
                "Senior ML engineer with 5+ years deploying LLMs in production "
                "at scale, leading teams of 10+ engineers shipping inference "
                "services across regions. Architected end-to-end RAG platforms "
                "serving millions of queries per day."
            ),
            rewritten_bullets=[
                "Led a team of 12 ML engineers shipping a production LLM platform serving 10M+ queries/day.",
                "Architected the end-to-end RAG infrastructure handling 500K+ daily searches.",
                "Mentored 8 senior engineers through model-deployment cycles.",
            ],
            highlighted_skills=["Python", "PyTorch", "LLMs", "RAG", "Distributed inference", "Team leadership"],
            cover_letter_themes=[
                "Position as senior ML leader with a track record of shipping production LLM systems at scale.",
            ],
        ),
        # The summary claims '5+ years', '10+ engineers', 'millions per day'
        # — none of which are in the resume.
        "flagged_terms": ["5+", "5 years", "10+", "senior ml", "production", "scale"],
        "summary_must_not_contain": ["5+", "5 years", "10+ engineers", "millions"],
    },
    {
        "label": "adv_wrong_industry",
        "resume": "13-healthcare-rn.txt",
        "jd": "04-moloco-data-scientist.txt",
        "mode": "adversarial",
        "input_tailoring": TailoringAgentOutput(
            # Diana is a critical-care RN with zero programming/ML
            # background. This claims she's a Python data scientist.
            professional_summary=(
                "Data scientist with 5+ years building Python-based ML "
                "pipelines and SQL analytics at scale in healthcare settings. "
                "Strong PyTorch and TensorFlow background with experience "
                "deploying production ML services."
            ),
            rewritten_bullets=[
                "Built Python ML pipelines analyzing patient telemetry across 40-bed ICUs.",
                "Wrote SQL analytics queries against the hospital data warehouse.",
                "Trained PyTorch models for patient outcome prediction with AUROC 0.89.",
            ],
            highlighted_skills=["Python", "Machine Learning", "SQL", "Statistical Modeling", "PyTorch", "TensorFlow"],
            cover_letter_themes=[
                "Lead with Python-based ML production experience in healthcare.",
            ],
        ),
        "removable_skills": ["Python", "Machine Learning", "SQL", "Statistical Modeling", "PyTorch", "TensorFlow"],
        "flagged_terms": ["python", "machine learning", "sql", "pytorch", "tensorflow", "data scientist"],
    },
]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


SECTION_WEIGHTS = {
    "detection": 2.0,
    "correction": 2.0,
    "no_false_rejection": 1.5,
    "approval_consistency": 1.0,
    "format_compliance": 0.5,
}


def _final_tailoring(
    review_output: ReviewAgentOutput, input_tailoring: TailoringAgentOutput
) -> TailoringAgentOutput:
    """Mirror orchestrator's choice: corrected if present, else original."""
    return review_output.corrected_tailoring or input_tailoring


def _flagged_text(review_output: ReviewAgentOutput) -> str:
    return " ".join(
        review_output.grounding_issues
        + review_output.unresolved_issues
        + review_output.revision_requests
    ).lower()


def _score_detection(scenario: dict, review_output: ReviewAgentOutput) -> tuple[float, list[str]]:
    """For adversarial scenarios: did the agent flag the injected issue?"""
    if scenario["mode"] != "adversarial":
        return 1.0, []
    flagged_terms = scenario.get("flagged_terms") or []
    if not flagged_terms:
        return 1.0, []
    flagged_text = _flagged_text(review_output)
    detected_terms = [t for t in flagged_terms if t.lower() in flagged_text]
    if detected_terms:
        return 1.0, [f"detected: {', '.join(detected_terms[:4])}"]
    # Fallback: even if not mentioned by name, removing the offending
    # skill from corrected_tailoring is also "detection". Check that
    # path in correction_score; here we just note the gap.
    notes = [f"no flagged_terms in review notes; relying on corrected_tailoring"]
    return 0.5, notes


def _score_correction(
    scenario: dict,
    review_output: ReviewAgentOutput,
    input_tailoring: TailoringAgentOutput,
    profile_skills: list[str],
    missing_hard_skills: list[str],
    resume_text: str,
) -> tuple[float, list[str]]:
    if scenario["mode"] != "adversarial":
        return 1.0, []

    final = _final_tailoring(review_output, input_tailoring)
    notes = []

    # 1. Removable skills should be gone from final highlighted_skills.
    removable = scenario.get("removable_skills") or []
    still_present_skills = []
    if removable:
        final_canonical = {s.lower().strip() for s in final.highlighted_skills}
        still_present_skills = [
            s for s in removable if s.lower().strip() in final_canonical
        ]

    # 2. Summary must not contain claim phrases.
    must_not_contain = scenario.get("summary_must_not_contain") or []
    summary_lower = (final.professional_summary or "").lower()
    still_present_phrases = [
        p for p in must_not_contain if p.lower() in summary_lower
    ]

    # 3. Re-grounding score on the FINAL output.
    grounding_score, _ = _score_grounding(
        final.highlighted_skills, profile_skills, resume_text
    )
    gap_score, _ = _score_gap_avoidance(
        final.highlighted_skills, missing_hard_skills
    )

    # Compose a correction score:
    #   - skill removal: each remaining bad skill drops -0.2
    #   - summary phrase removal: each remaining bad phrase drops -0.2
    #   - grounding/gap floor: take the min of these and the score so far
    correction_score = 1.0
    if still_present_skills:
        correction_score -= 0.2 * len(still_present_skills)
        notes.append(f"still in final.highlighted_skills: {still_present_skills}")
    if still_present_phrases:
        correction_score -= 0.2 * len(still_present_phrases)
        notes.append(f"still in final.summary: {still_present_phrases}")

    correction_score = max(0.0, correction_score)
    correction_score = min(correction_score, grounding_score, gap_score)

    if correction_score >= 1.0 and not still_present_skills and not still_present_phrases:
        notes.append("all injected fabrications removed from final output")

    return correction_score, notes


def _score_no_false_rejection(
    scenario: dict,
    review_output: ReviewAgentOutput,
    input_tailoring: TailoringAgentOutput,
) -> tuple[float, list[str]]:
    if scenario["mode"] != "clean":
        return 1.0, []

    notes = []
    score = 1.0

    if not review_output.approved:
        score -= 0.5
        notes.append("clean input was not approved")

    # If unresolved_issues is non-empty on a clean input, that's a
    # false flag.
    if review_output.unresolved_issues:
        score -= 0.3
        notes.append(
            f"unresolved_issues raised on clean input: {review_output.unresolved_issues[:2]}"
        )

    # corrected_tailoring on a clean input is allowed (the agent may
    # propose minor wording polish), but a wholesale rewrite of
    # highlighted_skills indicates over-correction. Compare overlap.
    if review_output.corrected_tailoring is not None:
        original = set(s.lower() for s in input_tailoring.highlighted_skills)
        corrected = set(s.lower() for s in review_output.corrected_tailoring.highlighted_skills)
        overlap = len(original & corrected) / max(len(original), 1)
        if overlap < 0.5:
            score -= 0.2
            notes.append(
                f"clean highlighted_skills overlap dropped to {overlap:.2f} after review"
            )

    return max(0.0, score), notes


def _score_approval_consistency(
    review_output: ReviewAgentOutput,
) -> tuple[float, list[str]]:
    """Contract: approved=True iff unresolved_issues == [].

    This is enforced by ReviewAgent._normalize_review_output(), so a
    failure here indicates a bug in the normalizer or in the LLM
    payload coercion.
    """
    has_unresolved = bool(review_output.unresolved_issues)
    if has_unresolved and review_output.approved:
        return 0.0, ["approved=True with non-empty unresolved_issues — contract violation"]
    if not has_unresolved and not review_output.approved:
        # Approved=False with no unresolved is allowed when the
        # incoming draft was uncorrectable, but in practice we treat
        # this as a soft-warning (might be over-conservative).
        return 0.7, ["approved=False with empty unresolved_issues — possibly over-conservative"]
    return 1.0, []


def _score_format(review_output: ReviewAgentOutput) -> tuple[float, list[str]]:
    notes = []
    if len(review_output.grounding_issues) > 4:
        notes.append("grounding_issues exceeds limit 4")
    if len(review_output.unresolved_issues) > 4:
        notes.append("unresolved_issues exceeds limit 4")
    if len(review_output.revision_requests) > 4:
        notes.append("revision_requests exceeds limit 4")
    if len(review_output.final_notes) > 3:
        notes.append("final_notes exceeds limit 3")
    return (1.0 if not notes else 0.5), notes


def score_scenario(
    scenario: dict,
    review_output: ReviewAgentOutput,
    input_tailoring: TailoringAgentOutput,
    profile_skills: list[str],
    missing_hard_skills: list[str],
    resume_text: str,
) -> dict:
    detection, det_notes = _score_detection(scenario, review_output)
    correction, corr_notes = _score_correction(
        scenario,
        review_output,
        input_tailoring,
        profile_skills,
        missing_hard_skills,
        resume_text,
    )
    no_false_reject, nfr_notes = _score_no_false_rejection(
        scenario, review_output, input_tailoring
    )
    approval_consistency, ac_notes = _score_approval_consistency(review_output)
    format_compliance, fmt_notes = _score_format(review_output)

    sections = {
        "detection": (detection, det_notes),
        "correction": (correction, corr_notes),
        "no_false_rejection": (no_false_reject, nfr_notes),
        "approval_consistency": (approval_consistency, ac_notes),
        "format_compliance": (format_compliance, fmt_notes),
    }

    # Detection + correction are only weighted on adversarial pairs;
    # no_false_rejection is only weighted on clean pairs. Drop weights
    # of irrelevant sections so the overall doesn't dilute.
    relevant_weights = {}
    for section, weight in SECTION_WEIGHTS.items():
        if scenario["mode"] == "clean" and section in {"detection", "correction"}:
            continue
        if scenario["mode"] == "adversarial" and section == "no_false_rejection":
            continue
        relevant_weights[section] = weight

    weighted_total = 0.0
    weight_sum = 0.0
    for section, weight in relevant_weights.items():
        score, _ = sections[section]
        weighted_total += weight * score
        weight_sum += weight
    overall = weighted_total / weight_sum if weight_sum else 0.0

    return {
        "overall": round(overall, 3),
        "sections": {
            section: {"score": round(score, 3), "notes": notes}
            for section, (score, notes) in sections.items()
        },
        "raw": {
            "approved": review_output.approved,
            "grounding_issues": list(review_output.grounding_issues),
            "unresolved_issues": list(review_output.unresolved_issues),
            "revision_requests": list(review_output.revision_requests),
            "corrected_tailoring": (
                {
                    "professional_summary": review_output.corrected_tailoring.professional_summary,
                    "rewritten_bullets": list(review_output.corrected_tailoring.rewritten_bullets),
                    "highlighted_skills": list(review_output.corrected_tailoring.highlighted_skills),
                    "cover_letter_themes": list(review_output.corrected_tailoring.cover_letter_themes),
                }
                if review_output.corrected_tailoring is not None
                else None
            ),
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


def _run_deterministic(
    candidate_profile, job_description, fit_analysis, tailored_draft, tailoring_output
) -> ReviewAgentOutput:
    agent = ReviewAgent(openai_service=None)
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
) -> ReviewAgentOutput | None:
    if openai_service is None or not openai_service.is_available():
        return None
    agent = ReviewAgent(openai_service=openai_service)
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


def _print_scorecard(label: str, mode: str, results: dict[str, dict | None]):
    print()
    print(f"=== {label} ({mode}) ===")
    sections = list(SECTION_WEIGHTS.keys())
    modes = list(results.keys())
    header = f"{'Section':<25}" + "".join(f"{m:<18}" for m in modes)
    print(header)
    print("-" * len(header))
    for section in sections:
        row = f"{section:<25}"
        for mode_key in modes:
            data = results[mode_key]
            if data is None:
                row += f"{'(skipped)':<18}"
                continue
            score = data["sections"][section]["score"]
            row += f"{_format_score(score):<18}"
        print(row)
    print("-" * len(header))
    overall_row = f"{'OVERALL':<25}"
    for mode_key in modes:
        data = results[mode_key]
        if data is None:
            overall_row += f"{'(skipped)':<18}"
            continue
        overall_row += f"{_format_score(data['overall']):<18}"
    print(overall_row)

    for mode_key, data in results.items():
        if data is None:
            continue
        notes = []
        for section, payload in data["sections"].items():
            for note in payload["notes"]:
                notes.append(f"  - [{section}] {note}")
        if notes:
            print()
            print(f"  [{mode_key}] notes:")
            for note in notes:
                print(note)
        print(
            f"  [{mode_key}] approved={data['raw']['approved']}, "
            f"grounding_issues={len(data['raw']['grounding_issues'])}, "
            f"unresolved={len(data['raw']['unresolved_issues'])}, "
            f"corrected={'yes' if data['raw']['corrected_tailoring'] else 'no'}"
        )


def _print_summary(per_scenario: list[dict]):
    print()
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    modes = list(per_scenario[0]["modes"].keys()) if per_scenario else []
    header = f"{'Scenario':<32}{'Mode':<14}" + "".join(f"{m:<18}" for m in modes)
    print(header)
    print("-" * len(header))
    for entry in per_scenario:
        row = f"{entry['label']:<32}{entry['mode']:<14}"
        for mode_key in modes:
            data = entry["modes"][mode_key]
            if data is None:
                row += f"{'(skipped)':<18}"
            else:
                row += f"{_format_score(data['overall']):<18}"
        print(row)
    print("-" * len(header))
    avg_row = f"{'AVERAGE (overall)':<46}"
    for mode_key in modes:
        scores = [
            entry["modes"][mode_key]["overall"]
            for entry in per_scenario
            if entry["modes"][mode_key] is not None
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

    per_scenario: list[dict] = []
    for scenario in SCENARIOS:
        resume_path = RESUMES_DIR / scenario["resume"]
        jd_path = JDS_DIR / scenario["jd"]
        if not resume_path.exists() or not jd_path.exists():
            print(f"SKIP {scenario['label']}: missing fixture")
            continue

        candidate_profile, job_description, fit_analysis, tailored_draft = _build_inputs(
            resume_path, jd_path
        )

        input_tailoring = scenario["input_tailoring"]

        deterministic_review = _run_deterministic(
            candidate_profile,
            job_description,
            fit_analysis,
            tailored_draft,
            input_tailoring,
        )
        deterministic_score = score_scenario(
            scenario,
            deterministic_review,
            input_tailoring,
            candidate_profile.skills,
            fit_analysis.missing_hard_skills,
            candidate_profile.resume_text,
        )

        llm_score = None
        if openai_service is not None:
            llm_review = _run_llm(
                openai_service,
                candidate_profile,
                job_description,
                fit_analysis,
                tailored_draft,
                input_tailoring,
            )
            if llm_review is not None:
                llm_score = score_scenario(
                    scenario,
                    llm_review,
                    input_tailoring,
                    candidate_profile.skills,
                    fit_analysis.missing_hard_skills,
                    candidate_profile.resume_text,
                )

        modes = {
            "deterministic": deterministic_score,
            "llm_only": llm_score,
        }
        _print_scorecard(scenario["label"], scenario["mode"], modes)
        per_scenario.append(
            {
                "label": scenario["label"],
                "mode": scenario["mode"],
                "resume": scenario["resume"],
                "jd": scenario["jd"],
                "modes": modes,
            }
        )

    _print_summary(per_scenario)

    if args.json:
        args.json.write_text(json.dumps(per_scenario, indent=2), encoding="utf-8")
        print(f"\nWrote full scorecard to {args.json}")


if __name__ == "__main__":
    main()
