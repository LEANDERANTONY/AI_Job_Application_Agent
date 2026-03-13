import re
from datetime import datetime
from typing import List, Optional

from src.schemas import CandidateProfile, FitAnalysis, JobDescription
from src.services.profile_service import build_candidate_context_text
from src.utils import dedupe_strings, match_keywords


def _extract_year_from_token(token) -> Optional[int]:
    if isinstance(token, dict):
        year = token.get("year")
        return year if isinstance(year, int) else None
    if isinstance(token, str):
        match = re.search(r"(19|20)\d{2}", token)
        if match:
            return int(match.group(0))
    return None


def _infer_candidate_experience_years(candidate_profile: CandidateProfile) -> Optional[float]:
    total_years = 0.0
    found_duration = False
    current_year = datetime.utcnow().year

    for experience in candidate_profile.experience:
        start_year = _extract_year_from_token(experience.start)
        end_year = _extract_year_from_token(experience.end) or current_year
        if start_year and end_year >= start_year:
            total_years += max(end_year - start_year, 0.5)
            found_duration = True

    if found_duration:
        return round(total_years, 1)

    text = build_candidate_context_text(candidate_profile)
    matches = re.findall(r"(\d+)\+?\s*(?:years?|yrs?)", text, re.IGNORECASE)
    if matches:
        return float(max(int(match) for match in matches))
    return None


def _parse_required_years(experience_requirement: Optional[str]) -> Optional[int]:
    if not experience_requirement:
        return None
    match = re.search(r"(\d+)", experience_requirement)
    if match:
        return int(match.group(1))
    return None


def _score_components(components: List[tuple]) -> int:
    if not components:
        return 40
    total_weight = sum(weight for _, weight in components)
    weighted_score = sum(score * weight for score, weight in components) / total_weight
    return int(round(weighted_score * 100))


def _readiness_label(overall_score: int) -> str:
    if overall_score >= 80:
        return "Strong match"
    if overall_score >= 60:
        return "Viable match"
    if overall_score >= 40:
        return "Stretch match"
    return "Low match"


def _experience_signal(
    candidate_years: Optional[float], required_years: Optional[int]
) -> str:
    if required_years is None:
        if candidate_years is None:
            return "The JD does not specify experience, and candidate experience could not be inferred."
        return f"Approx. {candidate_years} years of experience were inferred from candidate data."
    if candidate_years is None:
        return f"The JD asks for about {required_years}+ years, but candidate experience could not be inferred."
    return (
        f"Approx. {candidate_years} years of experience were inferred against a requirement "
        f"of about {required_years}+ years."
    )


def build_fit_analysis(
    candidate_profile: CandidateProfile, job_description: JobDescription
) -> FitAnalysis:
    if not isinstance(candidate_profile, CandidateProfile):
        raise TypeError("candidate_profile must be a CandidateProfile instance.")
    if not isinstance(job_description, JobDescription):
        raise TypeError("job_description must be a JobDescription instance.")

    candidate_text = build_candidate_context_text(candidate_profile)
    job_requirements = job_description.requirements

    matched_hard_skills = dedupe_strings(
        job_skill
        for job_skill in job_requirements.hard_skills
        if job_skill.lower() in {skill.lower() for skill in candidate_profile.skills}
        or job_skill in match_keywords(candidate_text, [job_skill])
    )
    missing_hard_skills = [
        skill for skill in job_requirements.hard_skills if skill not in matched_hard_skills
    ]

    matched_soft_skills = match_keywords(candidate_text, job_requirements.soft_skills)
    matched_soft_skills = dedupe_strings(matched_soft_skills)
    missing_soft_skills = [
        skill for skill in job_requirements.soft_skills if skill not in matched_soft_skills
    ]

    candidate_years = _infer_candidate_experience_years(candidate_profile)
    required_years = _parse_required_years(job_requirements.experience_requirement)

    score_components = []
    if job_requirements.hard_skills:
        score_components.append(
            (len(matched_hard_skills) / len(job_requirements.hard_skills), 0.65)
        )
    if job_requirements.soft_skills:
        score_components.append(
            (len(matched_soft_skills) / len(job_requirements.soft_skills), 0.2)
        )
    if required_years is not None:
        experience_score = 0.0 if candidate_years is None else min(candidate_years / required_years, 1.0)
        score_components.append((experience_score, 0.15))

    overall_score = _score_components(score_components)
    readiness_label = _readiness_label(overall_score)

    strengths = []
    if matched_hard_skills:
        strengths.append(
            f"Hard-skill coverage: {len(matched_hard_skills)}/{len(job_requirements.hard_skills)} matched."
        )
    if matched_soft_skills:
        strengths.append(
            f"Soft-skill evidence found for {', '.join(matched_soft_skills[:3])}."
        )
    if candidate_profile.linkedin_profile:
        strengths.append("Structured LinkedIn experience is available to ground tailoring.")
    if candidate_profile.resume_text:
        strengths.append("Resume text is available for evidence extraction and wording reuse.")
    strengths = dedupe_strings(strengths[:4])

    gaps = []
    if missing_hard_skills:
        gaps.append("Missing hard-skill evidence: " + ", ".join(missing_hard_skills[:5]) + ".")
    if missing_soft_skills:
        gaps.append("Missing soft-skill evidence: " + ", ".join(missing_soft_skills[:4]) + ".")
    if required_years is not None and candidate_years is not None and candidate_years < required_years:
        gaps.append(
            f"Inferred experience is below the JD signal ({candidate_years} vs {required_years}+ years)."
        )
    if required_years is not None and candidate_years is None:
        gaps.append("Candidate experience could not be inferred from the current profile inputs.")
    if not score_components:
        gaps.append("The JD lacks explicit requirements, so the fit score is only a weak signal.")
    gaps = dedupe_strings(gaps[:4])

    recommendations = []
    if matched_hard_skills:
        recommendations.append(
            "Lead the resume summary with: " + ", ".join(matched_hard_skills[:4]) + "."
        )
    if missing_hard_skills:
        recommendations.append(
            "Add grounded project or work evidence for: " + ", ".join(missing_hard_skills[:4]) + "."
        )
    if not candidate_profile.linkedin_profile:
        recommendations.append("Import LinkedIn data to add structured experience and preferences.")
    if not candidate_profile.full_name:
        recommendations.append("Confirm candidate identity details before generating recruiter-facing output.")
    if not job_requirements.hard_skills:
        recommendations.append("Use a fuller JD with explicit skill requirements for stronger tailoring.")
    recommendations = dedupe_strings(recommendations[:5])

    return FitAnalysis(
        target_role=job_description.title,
        overall_score=overall_score,
        readiness_label=readiness_label,
        matched_hard_skills=matched_hard_skills,
        missing_hard_skills=missing_hard_skills,
        matched_soft_skills=matched_soft_skills,
        missing_soft_skills=missing_soft_skills,
        experience_signal=_experience_signal(candidate_years, required_years),
        strengths=strengths,
        gaps=gaps,
        recommendations=recommendations,
    )
