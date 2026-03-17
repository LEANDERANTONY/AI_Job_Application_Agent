from typing import Iterable, List

from src.errors import InputValidationError
from src.parsers.jd import clean_text, extract_job_details
from src.schemas import JobDescription, JobRequirements
from src.utils import dedupe_strings


def _extract_requirement_lines(cleaned_text: str, markers: Iterable[str]) -> List[str]:
    matches = []
    for line in cleaned_text.splitlines():
        normalized_line = line.strip()
        lowered = normalized_line.lower()
        if normalized_line and any(marker in lowered for marker in markers):
            matches.append(normalized_line)
    return dedupe_strings(matches[:5])


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
        requirements=JobRequirements(
            hard_skills=dedupe_strings(extracted.get("skills", [])),
            soft_skills=dedupe_strings(extracted.get("soft_skills", [])),
            experience_requirement=extracted.get("experience_required"),
            must_haves=must_haves,
            nice_to_haves=nice_to_haves,
        ),
    )
