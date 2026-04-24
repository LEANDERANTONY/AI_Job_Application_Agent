import logging
import re
from typing import List

from src.openai_service import OpenAIService
from src.schemas import (
    CandidateProfile,
    EducationEntry,
    ResumeDocument,
    WorkExperience,
)
from src.services.resume_llm_parser_service import ResumeLLMParserService
from src.taxonomy import HARD_SKILL_KEYWORDS, SOFT_SKILL_KEYWORDS
from src.utils import dedupe_strings, match_keywords


logger = logging.getLogger(__name__)


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

INSTITUTION_KEYWORDS = (
    "university",
    "institute",
    "college",
    "school",
    "academy",
    "polytechnic",
    "iiit",
    "iit",
    "nit",
)

ROLE_KEYWORDS = (
    "manager",
    "engineer",
    "designer",
    "developer",
    "analyst",
    "scientist",
    "intern",
    "internship",
    "lead",
    "director",
    "coordinator",
    "consultant",
    "specialist",
    "architect",
    "executive",
    "accountant",
    "treasurer",
    "technician",
    "tech",
)

CERTIFICATION_KEYWORDS = (
    "certified",
    "certification",
    "certificate",
    "license",
    "licence",
    "specialization",
    "specialisation",
    "coursera",
    "edx",
    "udemy",
    "credential",
)

ORGANIZATION_KEYWORDS = (
    "company",
    "co .",
    "co.",
    "partners",
    "industries",
    "labs",
    "solutions",
    "program",
    "studio",
    "group",
    "agency",
)

DATE_SEPARATOR = "•"

EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_PATTERN = re.compile(
    r"(?:(?:\+\d{1,3}[\s\-]?)?(?:\(?\d{2,5}\)?[\s\-]?){2,4}\d{2,4})"
)
DATE_ONLY_PATTERN = re.compile(
    r"^(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{4}\s*[\-–—]\s*(?:present|current|ongoing|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{4})$",
    re.IGNORECASE,
)
DATE_RANGE_PREFIX_PATTERN = re.compile(
    r"^(?P<dates>(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{4}\s*[\-–—]\s*(?:present|current|ongoing|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{4}))\s+(?P<content>.+)$",
    re.IGNORECASE,
)
MONTH_YEAR_PATTERN = re.compile(
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{4}",
    re.IGNORECASE,
)
PROFILE_LINK_PATTERN = re.compile(
    r"\b(?:https?://)?(?:www\.)?(?:linkedin\.com/in/[^\s|•·,;]+|github\.com/[^\s|•·,;]+|[A-Z0-9.-]+\.[A-Z]{2,}(?:/[^\s|•·,;]*)?)\b",
    re.IGNORECASE,
)


def _normalize_line(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip())


def _normalize_contact_segment(value: str) -> str:
    normalized = _normalize_line(value)
    normalized = re.sub(r"\s*@\s*", "@", normalized)
    normalized = re.sub(r"\s*\.\s*", ".", normalized)
    normalized = re.sub(r"\s*:\s*", ":", normalized)
    normalized = re.sub(r"\s*/\s*", "/", normalized)
    return normalized


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


def _split_education_date(line: str) -> tuple[str, str]:
    normalized = _normalize_line(line)
    date_matches = list(MONTH_YEAR_PATTERN.finditer(normalized))
    if len(date_matches) < 1:
        return normalized, ""
    first_date_start = date_matches[0].start()
    if first_date_start == 0:
        return normalized, ""
    trailing = normalized[first_date_start:].strip()
    if len(date_matches) < 2 and not re.search(r"\b(?:present|current|ongoing)\b", trailing, re.IGNORECASE):
        return normalized, ""
    content = normalized[:first_date_start].rstrip(" -–—•·\ufffd").strip()
    return content, trailing


def _split_leading_date_range(line: str) -> tuple[str, str]:
    normalized = _normalize_line(line)
    match = DATE_RANGE_PREFIX_PATTERN.match(normalized)
    if not match:
        return normalized, ""
    return match.group("content").strip(), match.group("dates").strip()


def _split_trailing_date_range(line: str) -> tuple[str, str]:
    normalized = _normalize_line(line)
    date_matches = list(MONTH_YEAR_PATTERN.finditer(normalized))
    if len(date_matches) < 1:
        return normalized, ""
    first_date_start = date_matches[0].start()
    if first_date_start == 0:
        return normalized, ""
    trailing = normalized[first_date_start:].strip()
    if len(date_matches) < 2 and not re.search(r"\b(?:present|current|ongoing)\b", trailing, re.IGNORECASE):
        return normalized, ""
    content = normalized[:first_date_start].rstrip(" -–—•·\ufffd").strip()
    return content, trailing


def _looks_like_institution(line: str) -> bool:
    lowered = _normalize_line(line).lower()
    return bool(lowered) and any(keyword in lowered for keyword in INSTITUTION_KEYWORDS)


def _split_inline_institution(degree_text: str) -> tuple[str, str]:
    normalized = _normalize_line(degree_text)
    match = re.match(r"(?P<degree>.+?)\s+from\s+(?P<institution>.+)$", normalized, flags=re.IGNORECASE)
    if match:
        return match.group("degree").strip(), match.group("institution").strip()
    return normalized, ""


def _split_trailing_institution(degree_text: str) -> tuple[str, str]:
    normalized = _normalize_line(degree_text)
    if not normalized or " from " in normalized.lower():
        return normalized, ""

    words = normalized.split()
    for split_index in range(len(words) - 1, 0, -1):
        degree_part = " ".join(words[:split_index]).strip()
        institution_part = " ".join(words[split_index:]).strip()
        if degree_part and _looks_like_institution(institution_part):
            return degree_part, institution_part

    return normalized, ""


def _degree_needs_continuation(degree_text: str) -> bool:
    lowered = _normalize_line(degree_text).lower()
    return lowered.endswith(
        (
            " in",
            "with specialization in",
            "with specialisation in",
            "specialization in",
            "specialisation in",
            "focus on",
            "major in",
            "minor in",
        )
    )


def _should_extend_degree_with_next_line(degree_text: str, next_line: str) -> bool:
    normalized_degree = _normalize_line(degree_text)
    normalized_next = _normalize_line(next_line)
    if not normalized_degree or not normalized_next:
        return False
    if _looks_like_institution(normalized_next):
        return False
    if any(keyword in normalized_next.lower() for keyword in DEGREE_KEYWORDS):
        return False
    if DATE_RANGE_PREFIX_PATTERN.match(normalized_next):
        return False
    if _normalize_section_header(normalized_next):
        return False
    if len(normalized_next.split()) > 6:
        return False
    return normalized_degree[-1].isalnum()


def _split_date_range_parts(date_text: str) -> tuple[str, str]:
    normalized = _normalize_line(date_text)
    if not normalized:
        return "", ""
    parts = re.split(r"\s*[\-–—]\s*", normalized, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return normalized, ""


def _looks_like_company_line(line: str) -> bool:
    lowered = _normalize_line(line).lower()
    if not lowered:
        return False
    return any(keyword in lowered for keyword in ORGANIZATION_KEYWORDS) or bool(re.search(r"\b(?:st\.?|street|city|remote)\b", lowered))


def _looks_like_role_title(line: str) -> bool:
    normalized = _normalize_line(line)
    title_segment = normalized.split(",", 1)[0].split(" , ", 1)[0].strip()
    lowered = title_segment.lower()
    if not normalized or len(normalized) > 90:
        return False
    if not title_segment or len(title_segment.split()) > 5:
        return False
    if ":" in title_segment:
        return False
    if ":" in normalized:
        label = _normalize_section_header(normalized.split(":", 1)[0].strip())
        if label:
            return False
    if _looks_like_company_line(normalized) and not title_segment:
        return False
    if _normalize_section_header(normalized):
        return False
    return any(re.search(r"\b{keyword}\b".format(keyword=re.escape(keyword)), lowered) for keyword in ROLE_KEYWORDS)


def _looks_like_experience_description(line: str) -> bool:
    normalized = _normalize_line(line)
    lowered = normalized.lower()
    if not normalized:
        return False
    if _looks_like_company_line(normalized) or _looks_like_role_title(normalized):
        return False
    if _looks_like_education_line(normalized) or DATE_ONLY_PATTERN.match(normalized):
        return False
    if _normalize_section_header(normalized):
        return False
    if any(token in lowered for token in ("@", "www.", "http://", "https://")):
        return False
    return len(normalized.split()) >= 6


def _split_experience_title_and_org(line: str) -> tuple[str, str]:
    normalized = _normalize_line(line)
    if " , " in normalized:
        title, organization = [part.strip() for part in normalized.split(" , ", 1)]
        return title, organization
    if "," in normalized:
        title, organization = [part.strip() for part in normalized.split(",", 1)]
        return title, organization
    return normalized, ""


def _append_experience_entry(entries: List[WorkExperience], *, title: str, organization: str = "", date_text: str = "", description_lines: List[str] | None = None):
    title = _normalize_line(title)
    organization = _normalize_line(organization)
    if not title:
        return
    start, end = _split_date_range_parts(date_text)
    description = "\n".join(_normalize_line(line) for line in (description_lines or []) if _normalize_line(line)).strip()
    if not (start or end or description):
        return
    entries.append(
        WorkExperience(
            title=title,
            organization=organization,
            description=description,
            start=start or None,
            end=end or None,
        )
    )


def _parse_experience_entries(section_lines: List[str], all_lines: List[str]) -> List[WorkExperience]:
    entries: List[WorkExperience] = []
    current_entry = None

    def flush_current():
        nonlocal current_entry
        if not current_entry:
            return
        _append_experience_entry(entries, **current_entry)
        current_entry = None

    def scan_lines(lines_to_scan: List[str]):
        nonlocal current_entry
        for raw_line in lines_to_scan:
            line = _normalize_line(raw_line)
            if not line:
                continue

            if current_entry and not current_entry["date_text"] and DATE_ONLY_PATTERN.match(line):
                current_entry["date_text"] = line
                continue

            maybe_header = _normalize_section_header(line)
            if maybe_header:
                flush_current()
                continue

            content, leading_date = _split_leading_date_range(line)
            if leading_date and _looks_like_role_title(content) and not _looks_like_education_line(content):
                flush_current()
                title, organization = _split_experience_title_and_org(content)
                current_entry = {
                    "title": title,
                    "organization": organization,
                    "date_text": leading_date,
                    "description_lines": [],
                }
                continue

            content, trailing_date = _split_trailing_date_range(line)
            if trailing_date and _looks_like_role_title(content) and not _looks_like_education_line(content):
                flush_current()
                title, organization = _split_experience_title_and_org(content)
                current_entry = {
                    "title": title,
                    "organization": organization,
                    "date_text": trailing_date,
                    "description_lines": [],
                }
                continue

            if (
                (_looks_like_role_title(line) or ("," in line and _looks_like_role_title(_split_experience_title_and_org(line)[0])))
                and not _looks_like_education_line(line)
                and ("," in line or " , " in line)
            ):
                flush_current()
                title, organization = _split_experience_title_and_org(line)
                current_entry = {
                    "title": title,
                    "organization": organization,
                    "date_text": "",
                    "description_lines": [],
                }
                continue

            if current_entry and _looks_like_experience_description(line):
                current_entry["description_lines"].append(line)
                continue

            if current_entry and _looks_like_role_title(line):
                flush_current()

    scan_lines(section_lines or all_lines)

    flush_current()

    if entries or not section_lines:
        return entries

    scan_lines(all_lines)
    flush_current()

    if entries:
        return entries

    role_lines = [line for line in section_lines if _looks_like_role_title(line)]
    organization_lines = [line for line in section_lines if _looks_like_company_line(line)]
    date_lines = [line for line in all_lines if DATE_ONLY_PATTERN.match(_normalize_line(line))]

    paired_entries: List[WorkExperience] = []
    pair_count = min(len(role_lines), len(organization_lines), len(date_lines))
    for index in range(pair_count):
        title, organization_inline = _split_experience_title_and_org(role_lines[index])
        organization = organization_inline or organization_lines[index]
        _append_experience_entry(
            paired_entries,
            title=title,
            organization=organization,
            date_text=date_lines[index],
            description_lines=[],
        )
    return paired_entries


def _merge_education_entries(primary: List[EducationEntry], secondary: List[EducationEntry]) -> List[EducationEntry]:
    merged: List[EducationEntry] = []
    seen = set()

    for entry in list(primary) + list(secondary):
        key = (
            _normalize_line(entry.institution).lower(),
            _normalize_line(entry.degree).lower(),
            _normalize_line(entry.start).lower(),
            _normalize_line(entry.end).lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(entry)

    return merged


def _looks_like_education_line(line: str) -> bool:
    normalized = _normalize_line(line)
    lowered = normalized.lower()
    if not any(keyword in lowered for keyword in DEGREE_KEYWORDS):
        return False
    if normalized.endswith("."):
        return False

    content, _ = _split_education_date(normalized)
    content, _ = _split_leading_date_range(content)
    leading_window = " ".join(content.lower().split()[:6])
    return any(keyword in leading_window for keyword in DEGREE_KEYWORDS)


def _prune_education_entries(entries: List[EducationEntry]) -> List[EducationEntry]:
    best_by_key = {}
    ordered_keys = []

    for entry in entries:
        degree_key = _normalize_line(entry.degree).lower()
        start_key = _normalize_line(entry.start).lower()
        key = (degree_key, start_key)
        score = 0
        if entry.institution:
            score += 2
        if entry.start or entry.end:
            score += 1
        if key not in best_by_key:
            best_by_key[key] = (score, entry)
            ordered_keys.append(key)
            continue
        current_score, _ = best_by_key[key]
        if score > current_score:
            best_by_key[key] = (score, entry)

    return [best_by_key[key][1] for key in ordered_keys]


def _split_degree_continuation_and_institution(line: str) -> tuple[str, str]:
    normalized = _normalize_line(line)
    if not normalized:
        return "", ""

    words = normalized.split()
    for split_index in range(len(words) - 1, 0, -1):
        continuation = " ".join(words[:split_index]).strip()
        institution = " ".join(words[split_index:]).strip()
        if continuation and _looks_like_institution(institution):
            return continuation, institution

    if _looks_like_institution(normalized):
        return "", normalized

    return normalized, ""


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
        if not _looks_like_education_line(line):
            index += 1
            continue

        degree_text, date_text = _split_education_date(line)
        degree_text, leading_date = _split_leading_date_range(degree_text)
        if not date_text and leading_date:
            date_text = leading_date
        degree_text, institution = _split_inline_institution(degree_text)
        if not institution:
            degree_text, institution = _split_trailing_institution(degree_text)

        if not institution and index > 0:
            previous_line = _normalize_line(section_lines[index - 1])
            previous_content, _ = _split_education_date(previous_line)
            if _looks_like_institution(previous_content) and not any(
                keyword in previous_content.lower() for keyword in DEGREE_KEYWORDS
            ) and not re.search(r"\d{4}", previous_content):
                institution = previous_content

        if index + 1 < len(section_lines):
            next_line = _normalize_line(section_lines[index + 1])
            next_lower = next_line.lower()
            if next_line and not any(keyword in next_lower for keyword in DEGREE_KEYWORDS):
                next_content, next_date = _split_education_date(next_line)
                next_content, next_leading_date = _split_leading_date_range(next_content)
                if not date_text and next_date:
                    date_text = next_date
                if not date_text and next_leading_date:
                    date_text = next_leading_date

                if _should_extend_degree_with_next_line(degree_text, next_content):
                    degree_text = _normalize_line("{degree} {continuation}".format(
                        degree=degree_text,
                        continuation=next_content,
                    ))
                    index += 1

                if _looks_like_institution(next_content) and not _degree_needs_continuation(degree_text):
                    institution = next_content

                if not institution:
                    if _degree_needs_continuation(degree_text):
                        continuation, parsed_institution = _split_degree_continuation_and_institution(next_content)
                        if continuation:
                            degree_text = _normalize_line("{degree} {continuation}".format(
                                degree=degree_text,
                                continuation=continuation,
                            ))
                        institution = parsed_institution
                index += 1

        entries.append(
            EducationEntry(
                institution=institution,
                degree=degree_text,
                start=date_text,
            )
        )
        index += 1

    return _prune_education_entries(entries)


def _parse_certifications(section_lines: List[str]) -> List[str]:
    certifications = []
    for raw_line in section_lines:
        line = _clean_bullet_prefix(raw_line)
        lowered = line.lower()
        if _normalize_section_header(line) == "certifications":
            continue
        if re.search(r"\bcertifications?\s*:", lowered):
            suffix = line.split(":", 1)[1].strip() if ":" in line else line
            parts = [part.strip(" .") for part in re.split(r"\s*,\s*(?=[A-Z])", suffix) if part.strip(" .")]
            certifications.extend(parts)
            continue
        if any(keyword in lowered for keyword in CERTIFICATION_KEYWORDS):
            certifications.append(line.strip(" ."))
    return dedupe_strings(certifications)


def _parse_certifications_from_resume_text(text: str) -> List[str]:
    return _parse_certifications(text.splitlines())


def _first_meaningful_lines(text: str) -> List[str]:
    return [line.strip() for line in text.splitlines() if line.strip()][:5]


def _resume_header_lines(text: str) -> List[str]:
    lines: List[str] = []
    for raw_line in text.splitlines():
        line = _normalize_line(raw_line)
        if not line:
            continue
        maybe_header = _normalize_section_header(line)
        if maybe_header and lines:
            break
        lines.append(line)
        if len(lines) >= 8:
            break
    return lines


def _looks_like_name(line: str) -> bool:
    if not line or line.lower() in SECTION_HEADERS:
        return False
    lowered = line.lower()
    if any(keyword in lowered for keyword in INSTITUTION_KEYWORDS):
        return False
    words = line.split()
    if len(words) < 2 or len(words) > 4:
        return False
    if any(char.isdigit() for char in line):
        return False
    return all(word[:1].isupper() for word in words if word[:1].isalpha())


def _extract_name_from_resume(text: str) -> str:
    for line in [line.strip() for line in text.splitlines() if line.strip()][:40]:
        if _looks_like_name(line):
            return line
    return ""


def _extract_location_from_resume(text: str) -> str:
    for line in _resume_header_lines(text):
        segments = [segment.strip() for segment in re.split(r"[|•·]", line) if segment.strip()]
        for segment in segments or [line]:
            if "@" in segment or any(char.isdigit() for char in segment):
                continue
            if "," in segment and len(segment.split()) <= 6:
                return segment
    return ""


def _extract_contact_lines_from_resume(text: str) -> List[str]:
    contact_values: List[str] = []

    header_lines = _resume_header_lines(text)
    all_lines = [line.strip() for line in text.splitlines() if line.strip()]

    def collect_from_lines(lines_to_scan):
        for line in lines_to_scan:
            segments = [segment.strip() for segment in re.split(r"[|•·]", line) if segment.strip()]
            for segment in segments or [line]:
                normalized_segment = _normalize_contact_segment(segment)

                for email in EMAIL_PATTERN.findall(normalized_segment):
                    contact_values.append(email)

                for link in PROFILE_LINK_PATTERN.findall(normalized_segment):
                    lowered_link = link.lower()
                    if "@" in lowered_link:
                        continue
                    if lowered_link.startswith("www."):
                        contact_values.append("https://" + link)
                    elif lowered_link.startswith("http://") or lowered_link.startswith("https://"):
                        contact_values.append(link)
                    elif any(token in lowered_link for token in ("linkedin.com/", "github.com/")):
                        contact_values.append("https://" + link)

                lowered_segment = normalized_segment.lower()
                if any(token in lowered_segment for token in ("phone", "mobile", "tel", "+")) or re.search(r"\d", normalized_segment):
                    phone_match = PHONE_PATTERN.search(normalized_segment)
                    if phone_match:
                        candidate = phone_match.group(0).strip(" -|,;:")
                        digits_only = re.sub(r"\D", "", candidate)
                        if len(digits_only) >= 8:
                            contact_values.append(candidate)

    fallback_lines = all_lines[:40]
    lines_to_scan = header_lines + [line for line in fallback_lines if line not in header_lines]
    collect_from_lines(lines_to_scan)
    if len(dedupe_strings(contact_values)) < 2:
        collect_from_lines(all_lines[:120])

    return dedupe_strings(contact_values)


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
    professional_experience = _parse_experience_entries(sections.get("experience", []), resume_text.splitlines())
    education_entries = _parse_education_entries(sections.get("education", []))
    if len(education_entries) < 2:
        education_entries = _prune_education_entries(
            _merge_education_entries(
                education_entries,
                _parse_education_entries(resume_text.splitlines()),
            )
        )
    certifications = _parse_certifications(sections.get("certifications", []))
    if not certifications:
        certifications = _parse_certifications_from_resume_text(resume_text)
    return CandidateProfile(
        full_name=_extract_name_from_resume(resume_text),
        location=_extract_location_from_resume(resume_text),
        contact_lines=_extract_contact_lines_from_resume(resume_text),
        source=resume_document.source or "resume_upload",
        resume_text=resume_text,
        skills=detected_skills,
        experience=professional_experience or project_entries,
        education=education_entries,
        certifications=certifications,
        source_signals=_collect_resume_signals(
            resume_document,
            detected_skills,
            sections,
            project_entries,
        ),
    )


def _build_experience_entry_from_llm_payload(
    entry: dict, fallback_organization: str = ""
) -> WorkExperience | None:
    title = _normalize_line(entry.get("title"))
    organization = _normalize_line(entry.get("organization")) or fallback_organization
    location = _normalize_line(entry.get("location"))
    description = _normalize_line(entry.get("description"))
    start = _normalize_line(entry.get("start")) or None
    end = _normalize_line(entry.get("end")) or None
    if not (title or organization or description):
        return None
    return WorkExperience(
        title=title or "Relevant Experience",
        organization=organization,
        location=location,
        description=description,
        start=start,
        end=end,
    )


def _llm_payload_has_viable_snapshot(
    payload: dict, resume_text: str, deterministic_profile: CandidateProfile
) -> bool:
    combined_experience = list(payload.get("experience") or []) + list(
        payload.get("projects") or []
    )
    has_structured_content = any(
        [
            _normalize_line(payload.get("full_name")),
            list(payload.get("skills") or []),
            combined_experience,
            list(payload.get("education") or []),
            list(payload.get("certifications") or []),
        ]
    )
    if not has_structured_content:
        return False

    lowered_resume_text = str(resume_text or "").lower()
    if "projects" in lowered_resume_text and not combined_experience and deterministic_profile.experience:
        return False
    return True


def _build_candidate_profile_from_llm_payload(
    *,
    resume_document: ResumeDocument,
    deterministic_profile: CandidateProfile,
    payload: dict,
) -> CandidateProfile:
    experience_entries: list[WorkExperience] = []
    for entry in payload.get("experience") or []:
        experience = _build_experience_entry_from_llm_payload(entry)
        if experience:
            experience_entries.append(experience)
    for entry in payload.get("projects") or []:
        project = _build_experience_entry_from_llm_payload(
            entry,
            fallback_organization="Project Portfolio",
        )
        if project:
            experience_entries.append(project)

    education_entries = []
    for item in payload.get("education") or []:
        if not isinstance(item, dict):
            continue
        education_entries.append(
            EducationEntry(
                institution=_normalize_line(item.get("institution")),
                degree=_normalize_line(item.get("degree")),
                field_of_study=_normalize_line(item.get("field_of_study")),
                start=_normalize_line(item.get("start")),
                end=_normalize_line(item.get("end")),
            )
        )

    llm_source_signals = dedupe_strings(payload.get("source_signals") or [])
    project_count = len(payload.get("projects") or [])
    if project_count:
        llm_source_signals.append(
            "Structured {count} project entries with the LLM parser.".format(
                count=project_count
            )
        )
    llm_source_signals.append("Candidate profile structured with the LLM parser.")

    return CandidateProfile(
        full_name=_normalize_line(payload.get("full_name")) or deterministic_profile.full_name,
        location=_normalize_line(payload.get("location")) or deterministic_profile.location,
        contact_lines=dedupe_strings(
            payload.get("contact_lines") or deterministic_profile.contact_lines
        ),
        source=resume_document.source or "resume_upload",
        resume_text=resume_document.text,
        skills=dedupe_strings(payload.get("skills") or deterministic_profile.skills),
        experience=experience_entries or list(deterministic_profile.experience),
        education=_prune_education_entries(education_entries)
        or list(deterministic_profile.education),
        certifications=dedupe_strings(
            payload.get("certifications") or deterministic_profile.certifications
        ),
        source_signals=dedupe_strings(
            llm_source_signals + list(deterministic_profile.source_signals)
        ),
    )


def build_candidate_profile_from_resume_auto(
    resume_document: ResumeDocument,
    parser_service: ResumeLLMParserService | None = None,
) -> CandidateProfile:
    if not isinstance(resume_document, ResumeDocument):
        raise TypeError("resume_document must be a ResumeDocument instance.")

    deterministic_profile = build_candidate_profile_from_resume(resume_document)
    if resume_document.filetype.upper() == "TXT":
        return deterministic_profile

    llm_parser = parser_service or ResumeLLMParserService(
        openai_service=OpenAIService()
    )
    if not llm_parser.is_available():
        logger.warning(
            "Resume auto parser fallback: LLM parser unavailable. filetype=%s source=%s",
            resume_document.filetype,
            resume_document.source,
        )
        return deterministic_profile

    try:
        payload = llm_parser.parse(resume_document)
    except Exception as exc:
        logger.exception(
            "Resume auto parser fallback: LLM parsing failed. filetype=%s source=%s error=%s",
            resume_document.filetype,
            resume_document.source,
            exc,
        )
        return deterministic_profile

    if not _llm_payload_has_viable_snapshot(
        payload, resume_document.text, deterministic_profile
    ):
        logger.warning(
            "Resume auto parser fallback: LLM snapshot not viable. filetype=%s source=%s payload_keys=%s",
            resume_document.filetype,
            resume_document.source,
            sorted(list(payload.keys())),
        )
        return deterministic_profile

    logger.info(
        "Resume auto parser accepted LLM snapshot. filetype=%s source=%s experience=%s projects=%s skills=%s",
        resume_document.filetype,
        resume_document.source,
        len(payload.get("experience") or []),
        len(payload.get("projects") or []),
        len(payload.get("skills") or []),
    )

    return _build_candidate_profile_from_llm_payload(
        resume_document=resume_document,
        deterministic_profile=deterministic_profile,
        payload=payload,
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
