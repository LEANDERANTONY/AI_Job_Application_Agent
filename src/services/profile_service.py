import logging
import re
from typing import List

from src.openai_service import OpenAIService
from src.schemas import (
    CandidateProfile,
    EducationEntry,
    ProjectEntry,
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
    "publications",
    "achievements",
}

SECTION_ALIASES = {
    "professional summary": "summary",
    "summary": "summary",
    "about": "summary",
    "profile": "profile",
    "research interests": "summary",
    "technical skills": "skills",
    "core skills": "skills",
    "skills": "skills",
    "projects": "projects",
    "project": "projects",
    "selected projects": "projects",
    "personal projects": "projects",
    "professional experience": "experience",
    "experience": "experience",
    "work experience": "experience",
    "work history": "experience",
    "employment": "experience",
    "employment history": "experience",
    "professional history": "experience",
    "academic appointments": "experience",
    "research experience": "experience",
    "industry experience": "experience",
    "relevant experience": "experience",
    "education": "education",
    "academic background": "education",
    "academic qualifications": "education",
    "certifications": "certifications",
    "certification": "certifications",
    "licenses and certifications": "certifications",
    "publications": "publications",
    "publication": "publications",
    "selected publications": "publications",
    "papers": "publications",
    "achievements": "achievements",
    "achievement": "achievements",
    "awards": "achievements",
    "awards and honors": "achievements",
    "honors": "achievements",
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
    "b.s.",
    "b.s ",
    "b.a.",
    "b.a ",
    "ba in",
    "bs in",
    "m.a.",
    "m.s.",
    "ms in",
    "ma in",
    "ph.d",
    "phd",
    "doctorate",
    "doctoral",
    "associate of",
    "diploma",
    "immersive",
    "bootcamp",
    "certificate program",
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
    "researcher",
    "professor",
    "fellow",
    "postdoc",
    "postdoctoral",
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
    "founder",
    "co-founder",
    "owner",
    "principal",
    "associate",
    "officer",
    "ceo",
    "cto",
    "cfo",
    "vp",
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


# ---------------------------------------------------------------------------
# Multi-line / multi-separator header parser
# ---------------------------------------------------------------------------
#
# Real resumes split a single experience entry across several formats and
# multiple lines. The single-line _split_experience_title_and_org above
# only handles the simplest 'Title, Org' case; the helpers below pick up
# everything else we've seen in the wild:
#
#   - "Stripe — Senior Software Engineer\nSan Francisco, CA | Jul 2021 - Present"
#   - "Frontend Engineer Intern · Klarna · Remote\nSep 2024 - Dec 2024"
#   - "Assistant Professor, University of Toronto, Jul 2022 - Present"
#   - "Tata Motors Engineering Research Centre, Pune\nSenior Mechanical Engineer · Aug 2020 - Present"
#
# The strategy is "split header by likely separator → classify each piece
# as title/org/location/date" rather than assuming a fixed positional
# layout.

_HEADER_SEPARATORS = (" — ", " – ", " | ", " · ", " / ")
_LOCATION_TOKENS = {"remote", "hybrid", "on-site", "onsite"}
_LOCATION_COUNTRIES = (
    "india", "usa", "u.s.a.", "u.s.", "us", "canada", "uk", "u.k.",
    "australia", "germany", "france", "china", "japan", "singapore",
    "ireland", "netherlands", "spain", "italy", "brazil", "mexico",
)


def _split_header_parts(line: str) -> List[str]:
    """Split a single header line by the most likely separator. Tries
    the unambiguous separators first (em-dash/en-dash/pipe/middle-dot/
    slash), then falls back to comma when it yields multiple sensible
    parts. Trailing parenthesised dates ('Acme Corp (2023 - Present)')
    are peeled into a separate part so they classify independently."""
    normalized = _normalize_line(line)
    if not normalized:
        return []

    # Peel a trailing '(2023 - Present)' off the end first so the
    # split below doesn't have to fight with parens.
    head, parens_date = _peel_parenthesised_date(normalized)
    base = head if parens_date else normalized

    best: List[str] = []
    for sep in _HEADER_SEPARATORS:
        if sep in base:
            parts = [p.strip() for p in base.split(sep) if p.strip()]
            if len(parts) >= 2 and len(parts) > len(best):
                best = parts
    if not best and "," in base:
        parts = [p.strip() for p in base.split(",") if p.strip()]
        if len(parts) >= 2 and all(len(p) >= 2 for p in parts[:3]):
            best = parts
    if not best:
        best = [base]

    if parens_date:
        best = best + [parens_date]
    return best


_KNOWN_LOCATION_CITIES = (
    "san francisco", "new york", "brooklyn", "manhattan", "seattle", "boston",
    "austin", "los angeles", "chicago", "denver", "portland", "atlanta",
    "remote", "hybrid", "on-site", "onsite", "bengaluru", "bangalore",
    "mumbai", "delhi", "chennai", "hyderabad", "pune", "kolkata", "noida",
    "gurgaon", "gurugram", "london", "berlin", "amsterdam", "paris",
    "toronto", "vancouver", "montreal", "sydney", "melbourne", "singapore",
    "tokyo", "dublin", "zurich", "stockholm", "tel aviv",
)


def _classify_header_part(part: str) -> str:
    """Classify one part of a split header line as 'title' | 'org'
    | 'location' | 'date' | 'unknown'. Used by the multi-line
    experience parser to pick out which piece is which.

    Conservative on location detection: only flag a part as a location
    if it has a strong location signal (city + state code, country
    name in a list, explicit 'Remote'/'Hybrid' label, or appears in a
    known-cities allowlist). Single capitalised words like 'Stripe'
    default to 'org' rather than being mis-classified as cities.
    """
    if not part:
        return "unknown"
    normalized = _normalize_line(part)
    lowered = normalized.lower()

    # Date detection — month-year, year ranges, parenthesised year, etc.
    if MONTH_YEAR_PATTERN.search(normalized):
        return "date"
    if re.match(r"^\(?(?:19|20)\d{2}\b", normalized):
        return "date"
    if re.search(
        r"\b(?:19|20)\d{2}\s*[\-–—]\s*"
        r"(?:(?:19|20)\d{2}|present|current|ongoing|now)\b",
        lowered,
    ):
        return "date"

    # Title detection — must have a role keyword.
    if any(re.search(r"\b" + re.escape(kw) + r"\b", lowered) for kw in ROLE_KEYWORDS):
        return "title"

    # Location detection — only on strong signals.
    if lowered in _LOCATION_TOKENS:
        return "location"
    if re.search(r",\s*[A-Z]{2}\s*$", normalized):  # "Brooklyn, NY"
        return "location"
    if any(
        re.search(r"\b" + re.escape(country) + r"\b", lowered)
        for country in _LOCATION_COUNTRIES
    ):
        if len(normalized.split()) <= 5:
            return "location"
    if any(city == lowered or lowered.startswith(city + ",") or lowered.endswith(", " + city) for city in _KNOWN_LOCATION_CITIES):
        return "location"

    # Anything left is treated as an organisation.
    return "org"


def _peel_parenthesised_date(part: str) -> tuple[str, str]:
    """Given a piece like 'Acme Corp (2023 - Present)', return
    ('Acme Corp', '2023 - Present'). Used during header splitting so
    the date inside parens gets classified separately."""
    if not part:
        return part, ""
    match = re.search(r"\(([^)]+)\)\s*$", part)
    if not match:
        return part, ""
    inner = match.group(1).strip()
    head = part[: match.start()].strip()
    if MONTH_YEAR_PATTERN.search(inner) or re.search(
        r"(?:19|20)\d{2}", inner
    ):
        return head, inner
    return part, ""


def _is_pure_date_line(text: str) -> bool:
    """True for lines that are nothing but a date range. We use this
    to recognise the 'Sep 2024 - Dec 2024' or '(2020 - 2024)' lines
    that follow a header."""
    normalized = _normalize_line(text)
    if not normalized:
        return False
    if DATE_ONLY_PATTERN.match(normalized):
        return True
    if re.match(
        r"^\(?(?:19|20)\d{2}\s*[\-–—]\s*"
        r"(?:(?:19|20)\d{2}|present|current|ongoing|now)\)?$",
        normalized,
        re.IGNORECASE,
    ):
        return True
    if re.match(
        r"^(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{4}",
        normalized,
        re.IGNORECASE,
    ):
        # Starts with a month-year and contains a range — treat as a
        # pure date line even when followed by 'Present' / a second
        # month-year (the regex above only matched purist forms).
        if re.search(
            r"[\-–—]\s*(?:present|current|ongoing|now|"
            r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{4}|"
            r"(?:19|20)\d{2})",
            normalized,
            re.IGNORECASE,
        ):
            return True
    return False


def _is_bullet_line(raw: str) -> bool:
    if raw is None:
        return False
    stripped = raw.lstrip()
    if not stripped:
        return False
    return bool(re.match(r"^[•\-\*–—]\s+", stripped))


def _match_experience_header(rows: List[dict], start: int) -> dict | None:
    """Try to interpret rows[start] (and possibly rows[start+1]) as an
    experience-entry header. Returns the parsed fields + how many rows
    were consumed, or None if no header pattern matches."""
    if start >= len(rows):
        return None
    row = rows[start]
    text = row["text"]
    if not text or row["is_bullet"]:
        return None
    if _normalize_section_header(text):
        return None
    if _is_pure_date_line(text):
        return None
    if _looks_like_education_line(text):
        return None

    # Quick rejection: header lines are short-ish noun phrases. Wrapped
    # bullet continuations ('by enterprise customers.') are sentence
    # fragments — we reject anything that starts lowercase or ends with
    # a sentence terminator on a single un-split line.
    if text[:1].islower():
        return None
    parts1 = _split_header_parts(text)
    if len(parts1) == 1 and text.endswith((".", "!", "?")):
        return None
    classified1 = [(_classify_header_part(p), p) for p in parts1]
    has_title_1 = any(k == "title" for k, _ in classified1)
    has_org_1 = any(k == "org" for k, _ in classified1)
    has_date_1 = any(k == "date" for k, _ in classified1)

    # First-line must look like at least a title or an org.
    if not (has_title_1 or has_org_1):
        return None
    # Org-only single-part lines need a corroborating second line to
    # avoid grabbing stray text fragments.
    if not has_title_1 and len(parts1) == 1 and len(text.split()) <= 3:
        # 'Stripe' on its own would qualify only if line 2 carries
        # date/title metadata.
        next_row = rows[start + 1] if start + 1 < len(rows) else None
        if not next_row or next_row["is_bullet"] or not next_row["text"]:
            return None
        next_text = next_row["text"]
        if not (
            _is_pure_date_line(next_text)
            or any(
                k in {"date", "title"}
                for k, _ in [(_classify_header_part(p), p) for p in _split_header_parts(next_text)]
            )
        ):
            return None

    # Optional second-line consumption: a meta line with date / location.
    consumed = 1
    combined = list(classified1)

    if start + 1 < len(rows):
        next_row = rows[start + 1]
        next_text = next_row["text"]
        if next_text and not next_row["is_bullet"]:
            if _is_pure_date_line(next_text):
                combined.append(("date", next_text))
                consumed = 2
            else:
                parts2 = _split_header_parts(next_text)
                classified2 = [(_classify_header_part(p), p) for p in parts2]
                has_date_2 = any(k == "date" for k, _ in classified2)
                has_title_2 = any(k == "title" for k, _ in classified2)
                # Pull in line 2 if it carries metadata we still need
                # (date when line 1 had none, or title when line 1 was
                # an org-only line). We deliberately don't consume
                # bullet-paragraph or institution-shaped follow-ups.
                if (
                    (has_date_2 and not has_date_1)
                    or (has_title_2 and not has_title_1)
                ):
                    if not _looks_like_education_line(next_text):
                        combined.extend(classified2)
                        consumed = 2

    title, org, location, dates = "", "", "", ""
    extra_orgs: list[str] = []
    for kind, value in combined:
        if kind == "title" and not title:
            title = value
        elif kind == "date" and not dates:
            dates = value
        elif kind == "location" and not location:
            location = value
        elif kind == "org":
            if not org:
                org = value
            else:
                extra_orgs.append(value)

    # If we have a leftover org-like value and no location yet, assume
    # the second org-shaped piece is actually a location label.
    if extra_orgs and not location:
        location = extra_orgs[0]

    if not (title or org):
        return None

    return {
        "title": title,
        "organization": org,
        "location": location,
        "dates": dates,
        "consumed": consumed,
    }


def _append_experience_entry(
    entries: List[WorkExperience],
    *,
    title: str,
    organization: str = "",
    location: str = "",
    date_text: str = "",
    description_lines: List[str] | None = None,
):
    title = _normalize_line(title)
    organization = _normalize_line(organization)
    location = _normalize_line(location)
    if not title and not organization:
        return
    start, end = _split_date_range_parts(date_text)
    description = "\n".join(
        _normalize_line(line) for line in (description_lines or []) if _normalize_line(line)
    ).strip()
    # Keep header-only entries (title + org without date or description)
    # only when both title and organization are present — otherwise the
    # row was probably a stray header that didn't belong to a real role.
    if not (start or end or description) and not (title and organization):
        return
    entries.append(
        WorkExperience(
            title=title or "Relevant Experience",
            organization=organization,
            location=location,
            description=description,
            start=start or None,
            end=end or None,
        )
    )


def _parse_experience_entries(section_lines: List[str], all_lines: List[str]) -> List[WorkExperience]:
    """Parse the Experience section into structured entries.

    The implementation uses a header-aware multi-line scanner: we look
    for a 'header line' at each position, optionally consume the next
    line if it carries date / location metadata, and then collect the
    bullet/description lines that follow until the next header. This
    handles the four common real-world layouts:
      A. Single line with everything ('Title, Org, City, Date - Date')
      B. Header on line 1, 'Location | Date - Date' meta on line 2
      C. Header on line 1, pure 'Date - Date' on line 2
      D. Org-first on line 1, 'Title · Date - Date' on line 2

    Earlier versions handled only A; B-D produced 0 entries on
    Stripe / Cloudflare / Klarna / Tata Motors style resumes.
    """
    if not section_lines:
        return []

    rows: List[dict] = []
    for raw in section_lines:
        is_bullet = _is_bullet_line(raw)
        text = _normalize_line(_clean_bullet_prefix(raw)) if is_bullet else _normalize_line(raw)
        rows.append({"raw": raw, "text": text, "is_bullet": is_bullet})

    entries: List[WorkExperience] = []
    index = 0
    while index < len(rows):
        row = rows[index]
        if not row["text"] or row["is_bullet"]:
            index += 1
            continue
        if _is_pure_date_line(row["text"]):
            index += 1
            continue

        match = _match_experience_header(rows, index)
        if not match:
            index += 1
            continue

        index += match["consumed"]
        description_lines: list[str] = []
        while index < len(rows):
            row = rows[index]
            if not row["text"]:
                index += 1
                continue
            if row["is_bullet"]:
                description_lines.append(row["text"])
                index += 1
                continue
            if _is_pure_date_line(row["text"]):
                # Stray date on its own line — likely belongs to the
                # current entry (rare formatting); attach if we have
                # nothing else, otherwise skip.
                if match["dates"] == "":
                    match["dates"] = row["text"]
                index += 1
                continue
            # Could be the next entry's header — peek with the same
            # detector and break if it is.
            if _match_experience_header(rows, index):
                break
            # Otherwise treat as a continuation paragraph.
            if _looks_like_experience_description(row["text"]):
                description_lines.append(row["text"])
            index += 1

        _append_experience_entry(
            entries,
            title=match["title"],
            organization=match["organization"],
            location=match["location"],
            date_text=match["dates"],
            description_lines=description_lines,
        )

    return entries


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


def _matches_degree_keyword(text: str) -> bool:
    """Word-boundary degree-keyword check. Substring matching here used
    to false-positive on lines like 'Postdoctoral Researcher' where
    'doctoral' is buried inside 'postdoctoral' and the line was wrongly
    routed to the education parser."""
    if not text:
        return False
    lowered = text.lower()
    for keyword in DEGREE_KEYWORDS:
        kw = keyword.strip()
        if not kw:
            continue
        # Use word boundaries when the keyword is alphanumeric. Keywords
        # with periods (like "ph.d.") need a regex with escaped dots.
        if re.search(r"(?<![A-Za-z])" + re.escape(kw) + r"(?![A-Za-z])", lowered):
            return True
    return False


def _looks_like_education_line(line: str) -> bool:
    normalized = _normalize_line(line)
    if not _matches_degree_keyword(normalized):
        return False
    if normalized.endswith("."):
        return False

    content, _ = _split_education_date(normalized)
    content, _ = _split_leading_date_range(content)
    leading_window = " ".join(content.lower().split()[:6])
    return _matches_degree_keyword(leading_window)


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
    if len(cleaned) > 160:
        return False
    # Reject hyphen / asterisk-prefixed lines (those are description
    # sub-bullets). Heavy round-bullets ('•') are intentionally allowed:
    # some resume layouts use '•' as a project-title marker and the
    # text after it is a short capitalised name like
    # '• Multi-Modal Deep Learning for ...'.
    leading = line.lstrip()
    if leading.startswith(("- ", "-\t", "* ", "*\t")) or leading in {"-", "*"}:
        return False
    words = cleaned.split()
    if len(words) < 2:
        return False

    # If the line has a project-title separator (em-dash / en-dash / hyphen
    # surrounded by spaces / colon), only the leading 'name' segment needs
    # to look title-cased. The trailing 'description' segment is allowed
    # to be lowercase prose ('Recipe Mixer — meal planner with ...').
    leading = re.split(r"\s+(?:[—–\-]|:)\s+", cleaned, maxsplit=1)[0].strip()
    leading_words = leading.split() or words
    titleish_leading = sum(
        1
        for word in leading_words
        if word[:1].isupper() or any(char.isupper() for char in word[1:]) or word.isupper()
    )
    if leading_words and titleish_leading >= max(2, len(leading_words) // 2):
        return True

    titleish_words = sum(
        1
        for word in words
        if word[:1].isupper() or any(char.isupper() for char in word[1:]) or word.isupper()
    )
    return titleish_words >= max(2, len(words) // 2)


def _parse_project_entries(section_lines: List[str]) -> List[ProjectEntry]:
    projects: List[ProjectEntry] = []
    current_title = ""
    current_lines: List[str] = []
    current_status = ""

    def flush_current():
        nonlocal current_title, current_lines
        if not current_title:
            return
        bullets = [line for line in current_lines if line]
        description = ""
        if current_status and current_status.lower() not in current_title.lower():
            description = current_status
        projects.append(
            ProjectEntry(
                name=current_title,
                description=description,
                bullets=bullets,
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


def _parse_publication_entries(section_lines: List[str]) -> List[str]:
    """Free-form citation strings, one per logical entry. Real-world
    citations often wrap to 2-3 lines (long titles / author lists), so
    we merge a continuation line into the previous entry when it
    starts with lowercase / a small connector and the previous line
    didn't end in a sentence-terminator. Also tolerates explicit
    indentation as a continuation cue."""
    entries: List[str] = []
    for raw_line in section_lines:
        if raw_line is None:
            continue
        stripped = raw_line.rstrip()
        if not stripped or not stripped.strip():
            continue
        cleaned = _clean_bullet_prefix(stripped).strip()
        if not cleaned:
            continue
        if _normalize_section_header(cleaned) == "publications":
            continue
        # Continuation cues:
        #   - leading whitespace on the original line (typical wrap)
        #   - first character is lowercase (mid-sentence)
        #   - previous entry didn't end with a closing punctuation
        is_indented_wrap = stripped.startswith(("  ", "\t")) and not _is_bullet_line(stripped)
        starts_lowercase = cleaned[:1].islower()
        previous_unfinished = bool(entries) and not entries[-1].endswith((".", "!", "?", ")"))
        if entries and (is_indented_wrap or starts_lowercase or previous_unfinished):
            entries[-1] = (entries[-1].rstrip() + " " + cleaned).strip()
            continue
        entries.append(cleaned.strip(" ."))
    # Final cleanup: trim trailing punctuation noise but keep terminator.
    return dedupe_strings(entries)


_INLINE_EDU_DEGREE_PATTERNS = (
    r"\b(?:b\.?s\.?|b\.?a\.?|m\.?s\.?|m\.?a\.?|b\.?tech|m\.?tech|"
    r"b\.?e\.?|m\.?e\.?|b\.?sc|m\.?sc|"
    r"ph\.?d\.?|phd|doctorate|doctoral|"
    r"bachelor(?:'?s)?|master(?:'?s)?|mba|"
    r"associate of|diploma|certificate)\b"
)


def _parse_inline_education_line(line: str) -> EducationEntry | None:
    """Recognise compact one-line education records that the
    section-by-section parser misses, e.g.:
        'B.S. Computer Science, San Jose State University, 2023'
        'Ph.D. in Computer Science, MIT, 2020'
        'Bachelor of Arts in Economics, Cornell University, 2020'
    """
    normalized = _normalize_line(line)
    if not normalized:
        return None
    if not re.search(_INLINE_EDU_DEGREE_PATTERNS, normalized, re.IGNORECASE):
        return None
    parts = [part.strip() for part in normalized.split(",") if part.strip()]
    if len(parts) < 2:
        return None
    # First part should contain the degree keyword.
    if not re.search(_INLINE_EDU_DEGREE_PATTERNS, parts[0], re.IGNORECASE):
        return None
    # Find the institution part: the first part containing a known
    # institution keyword OR the second-to-last comma-separated chunk.
    institution = ""
    date_text = ""
    for part in parts[1:]:
        if re.match(r"^\(?(?:19|20)\d{2}\b", part):
            date_text = part.strip(" ()")
            continue
        if MONTH_YEAR_PATTERN.search(part):
            date_text = part
            continue
        if _looks_like_institution(part) and not institution:
            institution = part
            continue
        if not institution:
            institution = part
    if not institution:
        return None
    return EducationEntry(
        institution=institution,
        degree=parts[0],
        start=date_text,
    )


def _parse_inline_bootcamp_line(line: str, next_line: str = "") -> EducationEntry | None:
    """Recognise bootcamp / two-line institutional patterns where the
    first line names the school and the second carries a degree-style
    phrase (e.g. 'General Assembly Software Engineering Immersive' →
    next line 'New York, NY · Jun 2024 - Sep 2024'). The institution
    line itself doesn't contain a degree keyword, but the school name
    does include an institution keyword OR the next line carries the
    degree phrase."""
    if not line or _is_bullet_line(line):
        return None
    normalized = _normalize_line(line)
    if not normalized:
        return None
    if normalized.endswith("."):
        # Sentences (bullet descriptions) shouldn't trigger this.
        return None
    lowered = normalized.lower()
    if len(normalized.split()) > 12:
        # Bootcamp titles are short; descriptive sentences are not.
        return None
    has_immersive = bool(re.search(r"\b(?:immersive|bootcamp|certificate program)\b", lowered))
    has_institution = _looks_like_institution(normalized) or any(
        marker in lowered for marker in ("general assembly", "academy", "bootcamp", "school")
    )
    if not (has_immersive and has_institution):
        return None
    # Pull a date from the next line if present.
    date_text = ""
    next_norm = _normalize_line(next_line)
    if next_norm:
        match = MONTH_YEAR_PATTERN.search(next_norm)
        if match:
            date_text = next_norm[match.start() :].strip(" ()")
    return EducationEntry(
        institution=normalized,
        degree=normalized,
        start=date_text,
    )


def _parse_education_entries(section_lines: List[str]) -> List[EducationEntry]:
    entries: List[EducationEntry] = []
    index = 0

    while index < len(section_lines):
        line = _normalize_line(section_lines[index])

        # Run the inline single-line parser FIRST. It's more precise on
        # well-formed 'Degree, Institution, Year' lines than the
        # multi-line stitch logic below, which used to greedy-split the
        # institution at a word boundary and mangle 'Massachusetts
        # Institute of Technology, 2020' into 'Massachusetts' + the
        # rest.
        inline = _parse_inline_education_line(line)
        if inline is not None:
            entries.append(inline)
            index += 1
            continue
        # Bootcamp / institution-on-line-1 patterns.
        next_line = (
            section_lines[index + 1] if index + 1 < len(section_lines) else ""
        )
        bootcamp = _parse_inline_bootcamp_line(line, next_line)
        if bootcamp is not None:
            entries.append(bootcamp)
            index += 2 if next_line else 1
            continue

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
            # Reject if the FULL previous line contained a 4-digit year
            # (likely already part of a previous education entry's
            # 'Institution · Date' line, e.g. 'Liverpool ... Jan 2025'),
            # not just the date-stripped content.
            previous_has_year = bool(re.search(r"(?:19|20)\d{2}", previous_line))
            if (
                _looks_like_institution(previous_content)
                and not _matches_degree_keyword(previous_content)
                and not previous_has_year
            ):
                institution = previous_content

        if index + 1 < len(section_lines):
            next_line = _normalize_line(section_lines[index + 1])
            if next_line and not _matches_degree_keyword(next_line):
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
    """Section-mode parser: every non-empty, non-header line inside
    the Certifications section counts as a certification, even when
    the line doesn't carry an obvious cert keyword (e.g. 'Google
    Cloud Professional Cloud Architect, 2020' has no 'certified' /
    'certificate' / 'license' word but is clearly a cert)."""
    certifications: list[str] = []
    for raw_line in section_lines:
        if raw_line is None:
            continue
        cleaned = _clean_bullet_prefix(raw_line).strip()
        if not cleaned:
            continue
        if _normalize_section_header(cleaned) == "certifications":
            continue
        lowered = cleaned.lower()
        # 'Certifications: AWS Cert, GCP Cert' inline-list pattern.
        if re.search(r"\bcertifications?\s*:", lowered):
            suffix = cleaned.split(":", 1)[1].strip() if ":" in cleaned else cleaned
            parts = [
                part.strip(" .")
                for part in re.split(r"\s*,\s*(?=[A-Z])", suffix)
                if part.strip(" .")
            ]
            certifications.extend(parts)
            continue
        certifications.append(cleaned.strip(" ."))
    return dedupe_strings(certifications)


def _parse_certifications_from_resume_text(text: str) -> List[str]:
    """Whole-resume scan: only keep lines that strongly look like
    certifications (carry a cert keyword). Used as a fallback when
    the section parser returns nothing."""
    certifications: list[str] = []
    for raw_line in text.splitlines():
        cleaned = _clean_bullet_prefix(raw_line).strip()
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if _normalize_section_header(cleaned) == "certifications":
            continue
        if re.search(r"\bcertifications?\s*:", lowered):
            suffix = cleaned.split(":", 1)[1].strip() if ":" in cleaned else cleaned
            parts = [
                part.strip(" .")
                for part in re.split(r"\s*,\s*(?=[A-Z])", suffix)
                if part.strip(" .")
            ]
            certifications.extend(parts)
            continue
        if any(keyword in lowered for keyword in CERTIFICATION_KEYWORDS):
            certifications.append(cleaned.strip(" ."))
    return dedupe_strings(certifications)


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


_HONORIFIC_PREFIXES = (
    "dr.", "dr", "prof.", "prof", "professor", "mr.", "mr", "ms.", "ms",
    "mrs.", "mrs", "miss", "mx.", "mx",
)


def _strip_honorifics(name: str) -> str:
    """Drop a leading honorific (Dr./Prof./Mr./Ms./Mrs./Mx.) from a
    detected name. The honorifics list is case-insensitive and matches
    both 'Dr.' and 'Dr' forms. Names like 'Dr. Priya Venkataraman'
    return 'Priya Venkataraman'."""
    if not name:
        return name
    parts = name.split()
    while parts and parts[0].lower().rstrip(".") in {p.rstrip(".") for p in _HONORIFIC_PREFIXES}:
        parts = parts[1:]
    return " ".join(parts).strip() or name


def _looks_like_name(line: str) -> bool:
    if not line or line.lower() in SECTION_HEADERS:
        return False
    lowered = line.lower()
    if any(keyword in lowered for keyword in INSTITUTION_KEYWORDS):
        return False
    candidate = _strip_honorifics(line)
    words = candidate.split()
    if len(words) < 2 or len(words) > 4:
        return False
    if any(char.isdigit() for char in candidate):
        return False
    return all(word[:1].isupper() for word in words if word[:1].isalpha())


def _extract_name_from_resume(text: str) -> str:
    for line in [line.strip() for line in text.splitlines() if line.strip()][:40]:
        if _looks_like_name(line):
            return _strip_honorifics(line)
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
    resume_document: ResumeDocument,
    skills: List[str],
    sections: dict[str, List[str]],
    project_entries: List[ProjectEntry],
    publication_entries: List[str] | None = None,
) -> List[str]:
    signals = [f"Resume parsed from {resume_document.filetype} upload."]
    if skills:
        signals.append(f"Detected {len(skills)} reusable skill keywords from the resume text.")
    if len(resume_document.text.split()) >= 150:
        signals.append("Resume text appears detailed enough for downstream tailoring.")
    if project_entries:
        signals.append(f"Structured {len(project_entries)} project entries from the Projects section.")
    if publication_entries:
        signals.append(f"Captured {len(publication_entries)} publication entries from the resume.")
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
    publication_entries = _parse_publication_entries(sections.get("publications", []))
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
    # Projects no longer fall back into experience: students who only
    # have project work get an empty Experience section (which the
    # exporter drops) and a populated Projects section instead.
    return CandidateProfile(
        full_name=_extract_name_from_resume(resume_text),
        location=_extract_location_from_resume(resume_text),
        contact_lines=_extract_contact_lines_from_resume(resume_text),
        source=resume_document.source or "resume_upload",
        resume_text=resume_text,
        skills=detected_skills,
        experience=professional_experience,
        education=education_entries,
        certifications=certifications,
        projects=project_entries,
        publications=publication_entries,
        source_signals=_collect_resume_signals(
            resume_document,
            detected_skills,
            sections,
            project_entries,
            publication_entries,
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


def _build_project_entry_from_llm_payload(entry: dict) -> ProjectEntry | None:
    name = _normalize_line(entry.get("title")) or _normalize_line(entry.get("name"))
    description = _normalize_line(entry.get("description"))
    start = _normalize_line(entry.get("start"))
    end = _normalize_line(entry.get("end"))
    bullets_payload = entry.get("bullets") or entry.get("highlights") or []
    if isinstance(bullets_payload, list):
        bullets = [_normalize_line(item) for item in bullets_payload if _normalize_line(item)]
    else:
        bullets = []
    if not bullets and description:
        # If the LLM only returned a free-form description, split it into
        # bullet-style sentences so the renderer has something useful.
        sentences = [
            piece.strip()
            for piece in re.split(r"(?<=[.!?])\s+", description)
            if piece.strip()
        ]
        bullets = sentences[:3]
    technologies_payload = entry.get("technologies") or entry.get("tech_stack") or []
    if isinstance(technologies_payload, list):
        technologies = [_normalize_line(item) for item in technologies_payload if _normalize_line(item)]
    else:
        technologies = []
    links_payload = entry.get("links") or []
    link = ""
    if isinstance(links_payload, list) and links_payload:
        link = _normalize_line(links_payload[0])
    elif isinstance(links_payload, str):
        link = _normalize_line(links_payload)
    if not (name or description or bullets):
        return None
    return ProjectEntry(
        name=name or "Project",
        description=description,
        bullets=bullets,
        technologies=technologies,
        start=start,
        end=end,
        link=link,
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
            list(payload.get("publications") or []),
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

    # Confidence-aware merge for projects/publications: if the LLM
    # included the key in its response (even as an empty list), trust
    # that signal rather than falling back to the deterministic
    # parser's content. The LLM's empty-vs-populated decision is
    # generally more reliable than the regex-based scans, and the
    # fallback occasionally promoted stray text into phantom entries.
    llm_projects_raw = payload.get("projects")
    project_entries: list[ProjectEntry] = []
    if llm_projects_raw is not None:
        for entry in llm_projects_raw or []:
            if not isinstance(entry, dict):
                continue
            project = _build_project_entry_from_llm_payload(entry)
            if project:
                project_entries.append(project)
    llm_projects_authoritative = llm_projects_raw is not None

    llm_publications_raw = payload.get("publications")
    publication_entries: list[str] = []
    if llm_publications_raw is not None:
        publication_entries = [
            _normalize_line(item)
            for item in (llm_publications_raw or [])
            if _normalize_line(item)
        ]
    llm_publications_authoritative = llm_publications_raw is not None

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
    project_count = len(project_entries)
    if project_count:
        llm_source_signals.append(
            "Structured {count} project entries with the LLM parser.".format(
                count=project_count
            )
        )
    if publication_entries:
        llm_source_signals.append(
            "Captured {count} publication entries with the LLM parser.".format(
                count=len(publication_entries)
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
        projects=(
            project_entries
            if llm_projects_authoritative
            else (project_entries or list(deterministic_profile.projects))
        ),
        publications=dedupe_strings(
            publication_entries
            if llm_publications_authoritative
            else (publication_entries or deterministic_profile.publications)
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

    # Previously TXT uploads short-circuited to deterministic-only.
    # Tier-1 parser-quality testing showed the deterministic parser
    # averaged ~0.77 vs the LLM-hybrid path's ~0.99 across realistic
    # resumes, so we now route every filetype through the LLM hybrid.
    # Cost is ~$0.01 per upload — trivial vs the quality lift.
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
