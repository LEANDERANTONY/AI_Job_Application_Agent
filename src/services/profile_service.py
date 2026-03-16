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

SECTION_ALIASES = {
    "professional summary": "summary",
    "summary": "summary",
    "profile": "profile",
    "technical skills": "skills",
    "skills": "skills",
    "projects": "projects",
    "project": "projects",
    "professional experience": "experience",
    "experience": "experience",
    "education": "education",
    "certifications": "certifications",
    "certification": "certifications",
    "publications": "achievements",
    "publication": "achievements",
    "achievements": "achievements",
}

DEGREE_KEYWORDS = (
    "master",
    "b.tech",
    "b. tech",
    "btech",
    "b.e",
    "b. e",
    "be ",
    "bachelor",
    "m.tech",
    "m. tech",
    "executive pg",
    "pg program",
    "postgraduate",
    "m.sc",
    "m. sc",
    "msc",
    "degree",
)


def _normalize_line(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _normalize_section_header(line: str) -> str:
    normalized = re.sub(r"[^a-zA-Z ]+", " ", line or "").strip().lower()
    normalized = re.sub(r"\s+", " ", normalized)
    return SECTION_ALIASES.get(normalized, "")


def _split_resume_sections(text: str) -> dict[str, List[str]]:
    sections: dict[str, List[str]] = {}
    current_section = "profile"

    for raw_line in text.splitlines():
        line = _normalize_line(raw_line)
        if not line:
            continue
        maybe_header = _normalize_section_header(line)
        if maybe_header:
            current_section = maybe_header
            sections.setdefault(current_section, [])
            continue
        sections.setdefault(current_section, []).append(line)

    return sections


def _clean_bullet_prefix(line: str) -> str:
    return re.sub(r"^[\u2022\-\*\s]+", "", line or "").strip()


def _looks_like_project_title(line: str) -> bool:
    cleaned = _clean_bullet_prefix(line)
    lowered = cleaned.lower()
    if not cleaned or lowered in {"ongoing", "completed"}:
        return False
    if cleaned.endswith(":") or cleaned.endswith("."):
        return False
    if len(cleaned) > 120:
        return False
    words = cleaned.split()
    if len(words) < 2:
        return False
    titleish_words = sum(
        1
        for word in words
        if word[:1].isupper() or any(char.isupper() for char in word[1:]) or word.isupper()
    )
    return titleish_words >= max(2, len(words) // 2)


def _parse_project_entries(section_lines: List[str]) -> List[WorkExperience]:
    projects: List[WorkExperience] = []
    current_title = ""
    current_lines: List[str] = []
    current_status = ""

    def flush_current():
        nonlocal current_title, current_lines
        if not current_title:
            return
        description = "\n".join(line for line in current_lines if line).strip()
        if current_status and current_status.lower() not in current_title.lower():
            description = (current_status + "\n" + description).strip()
        projects.append(
            WorkExperience(
                title=current_title,
                organization="Project Portfolio",
                description=description,
            )
        )
        current_title = ""
        current_lines = []

    for line in section_lines:
        cleaned = _clean_bullet_prefix(line)
        lowered = cleaned.lower()
        if lowered in {"ongoing", "completed"}:
            current_status = cleaned
            continue
        if _looks_like_project_title(line):
            flush_current()
            current_title = cleaned
            continue
        if current_title:
            current_lines.append(cleaned)

    flush_current()
    return projects


def _parse_education_entries(section_lines: List[str]) -> List[EducationEntry]:
    entries: List[EducationEntry] = []
    index = 0

    while index < len(section_lines):
        line = _normalize_line(section_lines[index])
        lowered = line.lower()
        if not any(keyword in lowered for keyword in DEGREE_KEYWORDS):
            index += 1
            continue

        degree_text = line
        institution = ""
        if "•" in degree_text:
            degree_text, trailing = [part.strip() for part in degree_text.split("•", 1)]
            date_text = trailing
        else:
            date_text = ""

        if index + 1 < len(section_lines):
            next_line = _normalize_line(section_lines[index + 1])
            next_lower = next_line.lower()
            if next_line and not any(keyword in next_lower for keyword in DEGREE_KEYWORDS):
                institution = next_line.split("•", 1)[0].strip()
                if not date_text and "•" in next_line:
                    date_text = next_line.split("•", 1)[1].strip()
                index += 1

        entries.append(
            EducationEntry(
                institution=institution,
                degree=degree_text,
                start=date_text,
            )
        )
        index += 1

    return entries


def _parse_certifications(section_lines: List[str]) -> List[str]:
    return dedupe_strings(_clean_bullet_prefix(line) for line in section_lines)


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
    resume_document: ResumeDocument, skills: List[str], sections: dict[str, List[str]], project_entries: List[WorkExperience]
) -> List[str]:
    signals = [f"Resume parsed from {resume_document.filetype} upload."]
    if skills:
        signals.append(f"Detected {len(skills)} reusable skill keywords from the resume text.")
    if len(resume_document.text.split()) >= 150:
        signals.append("Resume text appears detailed enough for downstream tailoring.")
    if project_entries:
        signals.append(f"Structured {len(project_entries)} project entries from the Projects section.")
    if sections.get("education"):
        signals.append("Education details were found in the resume.")
    if sections.get("certifications"):
        signals.append("Certification details were found in the resume.")
    return signals


def build_candidate_profile_from_resume(resume_document: ResumeDocument) -> CandidateProfile:
    if not isinstance(resume_document, ResumeDocument):
        raise TypeError("resume_document must be a ResumeDocument instance.")

    resume_text = (resume_document.text or "").strip()
    sections = _split_resume_sections(resume_text)
    detected_skills = dedupe_strings(
        match_keywords(resume_text, HARD_SKILL_KEYWORDS + SOFT_SKILL_KEYWORDS)
    )
    project_entries = _parse_project_entries(sections.get("projects", []))
    education_entries = _parse_education_entries(sections.get("education", []))
    certifications = _parse_certifications(sections.get("certifications", []))
    return CandidateProfile(
        full_name=_extract_name_from_resume(resume_text),
        location=_extract_location_from_resume(resume_text),
        source=resume_document.source or "resume_upload",
        resume_text=resume_text,
        skills=detected_skills,
        experience=project_entries,
        education=education_entries,
        certifications=certifications,
        source_signals=_collect_resume_signals(
            resume_document,
            detected_skills,
            sections,
            project_entries,
        ),
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
