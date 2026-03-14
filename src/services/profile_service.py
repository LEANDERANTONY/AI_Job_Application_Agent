import re
from typing import List

from src.schemas import (
    CandidateProfile,
    EducationEntry,
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


def build_candidate_context_text(candidate_profile: CandidateProfile) -> str:
    if not isinstance(candidate_profile, CandidateProfile):
        raise TypeError("candidate_profile must be a CandidateProfile instance.")

    sections = [candidate_profile.resume_text]
    sections.extend(
        [
            " ".join(candidate_profile.skills),
            " ".join(
                experience.description
                for experience in candidate_profile.experience
                if experience.description
            ),
            " ".join(candidate_profile.certifications),
        ]
    )
    return "\n".join(section.strip() for section in sections if section and section.strip())
