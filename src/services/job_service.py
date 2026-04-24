import re
from typing import Iterable, List

from src.errors import InputValidationError
from src.parsers.jd import clean_text, extract_job_details
from src.schemas import JobDescription, JobRequirements
from src.utils import dedupe_strings


SECTION_ALIASES = {
    "Overview": [
        "about the role",
        "role summary",
        "job summary",
        "overview",
        "about this role",
    ],
    "What You'll Work On": [
        "what you’ll work on",
        "what you'll work on",
        "what you will work on",
        "what you’ll do",
        "what you'll do",
        "responsibilities",
        "what you will do",
    ],
    "What They're Looking For": [
        "what we’re looking for",
        "what we're looking for",
        "qualifications",
        "requirements",
        "you are likely a strong fit if",
        "we're looking for",
        "we are looking for",
    ],
    "Good Signals": [
        "signals that you’ll thrive here",
        "signals that you'll thrive here",
        "preferred qualifications",
        "nice to have",
        "nice-to-have",
        "good to have",
        "bonus",
    ],
}


def _extract_requirement_lines(cleaned_text: str, markers: Iterable[str]) -> List[str]:
    matches = []
    for line in cleaned_text.splitlines():
        normalized_line = line.strip()
        lowered = normalized_line.lower()
        if lowered.startswith("location:"):
            continue
        if normalized_line and any(marker in lowered for marker in markers):
            matches.append(normalized_line)
    return dedupe_strings(matches[:5])


def _normalize_summary_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _find_section_matches(normalized_text: str):
    lowered = normalized_text.lower()
    matches = []
    seen_labels = set()
    for label, aliases in SECTION_ALIASES.items():
        best_match = None
        for alias in aliases:
            index = lowered.find(alias)
            if index == -1:
                continue
            if best_match is None or index < best_match[0]:
                best_match = (index, alias)
        if best_match is not None and label not in seen_labels:
            seen_labels.add(label)
            matches.append((best_match[0], label, best_match[1]))
    return sorted(matches, key=lambda item: item[0])


def _split_section_body(body: str) -> List[str]:
    normalized = _normalize_summary_text(body)
    if not normalized:
        return []

    sentence_chunks = re.split(r"(?<=[.!?])\s+(?=[A-Z])", normalized)
    refined = []
    for chunk in sentence_chunks:
        chunk = chunk.strip(" -:")
        if not chunk:
            continue
        sub_chunks = re.split(
            r"\s+(?=(?:Design|Build|Own|Create|Implement|Integrate|Make|Collaborate|Have|Are|Take|You’ve|You've)\b)",
            chunk,
        )
        for sub_chunk in sub_chunks:
            cleaned = sub_chunk.strip(" -:")
            if cleaned:
                refined.append(cleaned)
    return dedupe_strings(refined)


def extract_job_summary_sections(cleaned_text: str, title: str = "") -> List[dict]:
    normalized_text = _normalize_summary_text(cleaned_text)
    if not normalized_text:
        return []

    normalized_title = _normalize_summary_text(title)
    body_text = normalized_text
    if normalized_title and body_text.lower().startswith(normalized_title.lower()):
        body_text = body_text[len(normalized_title):].strip(" :-")

    matches = _find_section_matches(body_text)
    if not matches:
        return [{"title": "Overview", "items": [body_text]}]

    sections = []
    first_index = matches[0][0]
    if first_index > 0:
        intro = body_text[:first_index].strip(" :-")
        if intro:
            sections.append({"title": "Overview", "items": _split_section_body(intro) or [intro]})

    for idx, (start_index, label, alias) in enumerate(matches):
        content_start = start_index + len(alias)
        next_start = matches[idx + 1][0] if idx + 1 < len(matches) else len(body_text)
        body = body_text[content_start:next_start].strip(" :-")
        if not body:
            continue
        items = _split_section_body(body) or [body]
        sections.append({"title": label, "items": items})

    return sections or [{"title": "Overview", "items": [body_text]}]


def build_job_description_from_text(raw_text: str) -> JobDescription:
    if not isinstance(raw_text, str):
        raise TypeError("raw_text must be a string.")

    if not raw_text.strip():
        raise InputValidationError("Add a job description before running analysis.")

    cleaned_text = clean_text(raw_text)
    extracted = extract_job_details(cleaned_text)
    must_haves = _extract_requirement_lines(
        cleaned_text,
        ["must", "required", "requirements", "you have", "need to", "qualification"],
    )
    nice_to_haves = _extract_requirement_lines(
        cleaned_text,
        ["preferred", "nice to have", "bonus", "plus", "good to have"],
    )

    return JobDescription(
        title=extracted.get("title", "Unknown Role"),
        raw_text=raw_text,
        cleaned_text=cleaned_text,
        location=extracted.get("location"),
        salary=extracted.get("salary"),
        requirements=JobRequirements(
            hard_skills=dedupe_strings(extracted.get("skills", [])),
            soft_skills=dedupe_strings(extracted.get("soft_skills", [])),
            experience_requirement=extracted.get("experience_required"),
            must_haves=must_haves,
            nice_to_haves=nice_to_haves,
        ),
    )
