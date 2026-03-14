from typing import List

from src.schemas import CandidateProfile, FitAnalysis, JobDescription, TailoredResumeDraft
from src.utils import dedupe_strings


def _truncate_text(text: str, limit: int = 140) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _build_professional_summary(
    candidate_profile: CandidateProfile,
    job_description: JobDescription,
    fit_analysis: FitAnalysis,
) -> str:
    anchor_skills = fit_analysis.matched_hard_skills[:3] or candidate_profile.skills[:3]
    role_reference = job_description.title or fit_analysis.target_role or "the target role"

    intro = "Candidate profile aligned to {role}".format(role=role_reference)
    if anchor_skills:
        intro += " with grounded evidence around {skills}".format(
            skills=", ".join(anchor_skills)
        )

    evidence = []
    if candidate_profile.experience:
        latest_experience = candidate_profile.experience[0]
        if latest_experience.title or latest_experience.organization:
            evidence.append(
                "{title} at {organization}".format(
                    title=latest_experience.title or "recent experience",
                    organization=latest_experience.organization or "current organization",
                )
            )

    if evidence:
        intro += ". Position the summary around " + " and ".join(evidence[:2]) + "."
    else:
        intro += ". Keep the opening focused on verified project and work evidence."
    return intro


def _build_priority_bullets(
    candidate_profile: CandidateProfile, fit_analysis: FitAnalysis
) -> List[str]:
    bullets = []
    emphasis_skills = fit_analysis.matched_hard_skills[:3]

    for experience in candidate_profile.experience[:3]:
        if experience.description:
            bullets.append(
                "Reframe {title} at {organization} around: {description}".format(
                    title=experience.title or "recent work",
                    organization=experience.organization or "recent organization",
                    description=_truncate_text(experience.description),
                )
            )
        elif emphasis_skills:
            bullets.append(
                "Add a quantified bullet under {title} at {organization} that shows {skills}.".format(
                    title=experience.title or "recent work",
                    organization=experience.organization or "recent organization",
                    skills=", ".join(emphasis_skills),
                )
            )

    if not bullets and emphasis_skills:
        bullets.append(
            "Create impact bullets that prove hands-on use of " + ", ".join(emphasis_skills) + "."
        )
    if not bullets:
        bullets.append(
            "Surface the most relevant quantified outcomes from current resume content before tailoring further."
        )
    return dedupe_strings(bullets[:4])


def _build_gap_mitigation_steps(
    job_description: JobDescription, fit_analysis: FitAnalysis
) -> List[str]:
    steps = []
    if fit_analysis.missing_hard_skills:
        steps.append(
            "Only mention {skills} where you have real evidence; otherwise address them in a learning or project section.".format(
                skills=", ".join(fit_analysis.missing_hard_skills[:4])
            )
        )
    if fit_analysis.missing_soft_skills:
        steps.append(
            "Use outcome-oriented bullets to demonstrate {skills} instead of listing them abstractly.".format(
                skills=", ".join(fit_analysis.missing_soft_skills[:3])
            )
        )
    if job_description.requirements.must_haves:
        steps.append(
            "Mirror the JD language for must-have themes such as: "
            + _truncate_text(job_description.requirements.must_haves[0], limit=120)
        )
    if not steps:
        steps.append("Keep wording tightly aligned to the JD and avoid adding unsupported claims.")
    return dedupe_strings(steps[:4])


def build_tailored_resume_draft(
    candidate_profile: CandidateProfile,
    job_description: JobDescription,
    fit_analysis: FitAnalysis,
) -> TailoredResumeDraft:
    if not isinstance(candidate_profile, CandidateProfile):
        raise TypeError("candidate_profile must be a CandidateProfile instance.")
    if not isinstance(job_description, JobDescription):
        raise TypeError("job_description must be a JobDescription instance.")
    if not isinstance(fit_analysis, FitAnalysis):
        raise TypeError("fit_analysis must be a FitAnalysis instance.")

    highlighted_skills = fit_analysis.matched_hard_skills[:6] or candidate_profile.skills[:6]

    return TailoredResumeDraft(
        target_role=job_description.title,
        professional_summary=_build_professional_summary(
            candidate_profile, job_description, fit_analysis
        ),
        highlighted_skills=highlighted_skills,
        priority_bullets=_build_priority_bullets(candidate_profile, fit_analysis),
        gap_mitigation_steps=_build_gap_mitigation_steps(job_description, fit_analysis),
    )
