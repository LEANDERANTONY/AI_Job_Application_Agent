import re
from typing import Iterable, List, Optional

from src.schemas import (
    CandidateProfile,
    EducationEntry,
    JobPreferences,
    LinkedInProfile,
    ResumeDocument,
    WorkExperience,
)
from src.taxonomy import HARD_SKILL_KEYWORDS, SOFT_SKILL_KEYWORDS
from src.utils import dedupe_strings, match_keywords


SECTION_HEADERS = {
    "experience",
    "education",
    "skills",
    "projects",
    "summary",
    "profile",
    "certifications",
    "achievements",
}


def _first_meaningful_lines(text: str) -> List[str]:
    return [line.strip() for line in text.splitlines() if line.strip()][:5]


def _looks_like_name(line: str) -> bool:
    if not line or line.lower() in SECTION_HEADERS:
        return False
    words = line.split()
    if len(words) < 2 or len(words) > 4:
        return False
    if any(char.isdigit() for char in line):
        return False
    return all(word[:1].isupper() for word in words if word[:1].isalpha())


def _extract_name_from_resume(text: str) -> str:
    for line in _first_meaningful_lines(text):
        if _looks_like_name(line):
            return line
    return ""


def _extract_location_from_resume(text: str) -> str:
    for line in _first_meaningful_lines(text):
        if "@" in line or any(char.isdigit() for char in line):
            continue
        if "," in line and len(line.split()) <= 6:
            return line
    return ""


def _collect_resume_signals(
    resume_document: ResumeDocument, skills: List[str]
) -> List[str]:
    signals = [f"Resume parsed from {resume_document.filetype} upload."]
    if skills:
        signals.append(f"Detected {len(skills)} reusable skill keywords from the resume text.")
    if len(resume_document.text.split()) >= 150:
        signals.append("Resume text appears detailed enough for downstream tailoring.")
    return signals


def _safe_payload_list(payload: dict, key: str) -> List:
    value = payload.get(key, [])
    return value if isinstance(value, list) else []


def build_candidate_profile_from_resume(resume_document: ResumeDocument) -> CandidateProfile:
    if not isinstance(resume_document, ResumeDocument):
        raise TypeError("resume_document must be a ResumeDocument instance.")

    resume_text = (resume_document.text or "").strip()
    detected_skills = dedupe_strings(
        match_keywords(resume_text, HARD_SKILL_KEYWORDS + SOFT_SKILL_KEYWORDS)
    )
    return CandidateProfile(
        full_name=_extract_name_from_resume(resume_text),
        location=_extract_location_from_resume(resume_text),
        source=resume_document.source or "resume_upload",
        resume_text=resume_text,
        skills=detected_skills,
        source_signals=_collect_resume_signals(resume_document, detected_skills),
    )


def build_candidate_profile_from_linkedin_data(payload: dict) -> CandidateProfile:
    if not isinstance(payload, dict):
        raise TypeError("payload must be a parsed LinkedIn payload dictionary.")

    summary = payload.get("summary", {}) if isinstance(payload.get("summary", {}), dict) else {}
    experiences = [
        WorkExperience(
            title=item.get("title", ""),
            organization=item.get("company", ""),
            location=item.get("location", ""),
            description=item.get("description", ""),
            start=item.get("start"),
            end=item.get("end"),
        )
        for item in _safe_payload_list(payload, "experience")
        if isinstance(item, dict)
    ]
    education = [
        EducationEntry(
            institution=item.get("school", ""),
            degree=item.get("degree", ""),
            field_of_study=item.get("field", ""),
            start=item.get("start", ""),
            end=item.get("end", ""),
        )
        for item in _safe_payload_list(payload, "education")
        if isinstance(item, dict)
    ]
    preferences = payload.get("preferences", {}) if isinstance(payload.get("preferences", {}), dict) else {}
    linkedin_profile = LinkedInProfile(
        full_name=str(summary.get("name", "") or "").strip(),
        headline=str(summary.get("headline", "") or "").strip(),
        location=str(summary.get("location", "") or "").strip(),
        summary=str(summary.get("summary", "") or "").strip(),
        skills=dedupe_strings(_safe_payload_list(payload, "skills")),
        experience=experiences,
        education=education,
        certifications=dedupe_strings(_safe_payload_list(payload, "certifications")),
        projects=[item for item in _safe_payload_list(payload, "projects") if isinstance(item, dict)],
        publications=[
            item for item in _safe_payload_list(payload, "publications") if isinstance(item, dict)
        ],
        preferences=JobPreferences(
            preferred_titles=[str(preferences.get("Preferred Title"))]
            if preferences.get("Preferred Title")
            else [],
            raw_preferences=preferences,
        ),
    )
    source_signals = ["LinkedIn export parsed into a structured profile."]
    if linkedin_profile.skills:
        source_signals.append(
            f"LinkedIn export contributed {len(linkedin_profile.skills)} explicit skills."
        )
    if linkedin_profile.experience:
        source_signals.append(
            f"LinkedIn export contributed {len(linkedin_profile.experience)} experience entries."
        )

    return CandidateProfile(
        full_name=linkedin_profile.full_name,
        location=linkedin_profile.location,
        source="linkedin_export",
        resume_text=linkedin_profile.summary,
        linkedin_profile=linkedin_profile,
        skills=linkedin_profile.skills,
        experience=linkedin_profile.experience,
        education=linkedin_profile.education,
        certifications=linkedin_profile.certifications,
        source_signals=source_signals,
    )


def merge_candidate_profiles(
    resume_profile: Optional[CandidateProfile],
    linkedin_profile: Optional[CandidateProfile],
) -> Optional[CandidateProfile]:
    if resume_profile is None and linkedin_profile is None:
        return None

    profiles = [profile for profile in [resume_profile, linkedin_profile] if profile is not None]
    primary = linkedin_profile or resume_profile
    combined_resume_segments = []
    for profile in profiles:
        if profile.resume_text and profile.resume_text not in combined_resume_segments:
            combined_resume_segments.append(profile.resume_text)
    combined_resume_text = "\n\n".join(combined_resume_segments).strip()

    merged_linkedin_profile = linkedin_profile.linkedin_profile if linkedin_profile else None
    merged_skills = dedupe_strings(
        skill for profile in profiles for skill in profile.skills
    )
    merged_experience = [
        experience for profile in profiles for experience in profile.experience if experience.title or experience.organization
    ]
    merged_education = [
        entry for profile in profiles for entry in profile.education if entry.institution or entry.degree
    ]
    merged_certifications = dedupe_strings(
        certification for profile in profiles for certification in profile.certifications
    )
    merged_signals = dedupe_strings(
        signal for profile in profiles for signal in profile.source_signals
    )
    merged_sources = dedupe_strings(profile.source for profile in profiles if profile.source)

    return CandidateProfile(
        full_name=primary.full_name or (resume_profile.full_name if resume_profile else ""),
        location=primary.location or (resume_profile.location if resume_profile else ""),
        source="+".join(merged_sources),
        resume_text=combined_resume_text,
        linkedin_profile=merged_linkedin_profile,
        skills=merged_skills,
        experience=merged_experience,
        education=merged_education,
        certifications=merged_certifications,
        source_signals=merged_signals,
    )


def build_candidate_context_text(candidate_profile: CandidateProfile) -> str:
    if not isinstance(candidate_profile, CandidateProfile):
        raise TypeError("candidate_profile must be a CandidateProfile instance.")

    sections = [candidate_profile.resume_text]
    if candidate_profile.linkedin_profile:
        linkedin_profile = candidate_profile.linkedin_profile
        sections.extend(
            [
                linkedin_profile.headline,
                linkedin_profile.summary,
                " ".join(linkedin_profile.skills),
                " ".join(
                    experience.description
                    for experience in linkedin_profile.experience
                    if experience.description
                ),
                " ".join(candidate_profile.certifications),
            ]
        )
    return "\n".join(section.strip() for section in sections if section and section.strip())
