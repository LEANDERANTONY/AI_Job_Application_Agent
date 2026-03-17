import re
from io import BytesIO
import logging

import docx
from pypdf import PdfReader

from src.errors import ParsingError
from src.logging_utils import get_logger, log_event
from src.parsers.common import decode_text, detect_file_type, normalize_extracted_text, read_file_bytes
from src.taxonomy import HARD_SKILL_KEYWORDS, SOFT_SKILL_KEYWORDS
from src.utils import match_keywords


LOGGER = get_logger(__name__)


def _parse_jd_bytes(file_bytes, file_type):
    if file_type == "text/plain":
        text = normalize_extracted_text(decode_text(file_bytes))
    elif file_type == "application/pdf":
        try:
            pdf = PdfReader(BytesIO(file_bytes))
        except Exception as exc:
            raise ParsingError("Failed to open the PDF job description.") from exc
        text = normalize_extracted_text("\n".join((page.extract_text() or "").strip() for page in pdf.pages))
    elif file_type in {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    }:
        try:
            document = docx.Document(BytesIO(file_bytes))
        except Exception as exc:
            raise ParsingError("Failed to open the DOCX job description.") from exc
        text = normalize_extracted_text("\n".join(
            paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text
        ))
    else:
        raise ParsingError("Unsupported job-description file type. Use PDF, DOCX, or TXT.")

    if not text.strip():
        raise ParsingError("The job description was parsed, but no readable text was extracted.")
    return text


def parse_jd_text(file):
    file_name = getattr(file, "name", "uploaded")
    try:
        file_type = detect_file_type(file)
        file_bytes = read_file_bytes(file)
        return _parse_jd_bytes(file_bytes, file_type)
    except ParsingError as error:
        log_event(
            LOGGER,
            logging.ERROR,
            "job_description_parse_failed",
            "Job description parsing failed.",
            file_name=file_name,
            file_type=locals().get("file_type"),
            file_size_bytes=len(locals().get("file_bytes", b"")),
            error_type=type(error).__name__,
        )
        raise


def clean_text(text):
    normalized_lines = []
    for raw_line in text.replace("\r", "\n").replace("\xa0", " ").splitlines():
        line = re.sub(r"[\u2022\u25cf*]", " ", raw_line)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            normalized_lines.append(line)
    return "\n".join(normalized_lines)


def extract_job_details(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    title = lines[0] if lines else "Unknown Role"
    if len(title) > 120:
        title = "Unknown Role"

    body_text = "\n".join(lines[1:]) if len(lines) > 1 else text
    location_match = re.search(
        r"(?:location|based in|work location)\s*[:\-]?\s*([^\n]+)",
        text,
        re.IGNORECASE,
    )
    experience_match = re.search(
        r"((?:required experience\s*[:\-]?\s*)?\d+\+?\s*(?:years?|yrs?)(?:\s+(?:of|in))?\s+(?:experience|[a-z][^\n,.;]{0,80}))",
        text,
        re.IGNORECASE,
    )
    return {
        "title": title,
        "location": location_match.group(1).strip() if location_match else None,
        "experience_required": re.sub(r"^required experience\s*[:\-]?\s*", "", experience_match.group(1).strip(), flags=re.IGNORECASE)
        if experience_match
        else None,
        "skills": match_keywords(body_text, HARD_SKILL_KEYWORDS),
        "soft_skills": match_keywords(body_text, SOFT_SKILL_KEYWORDS),
    }
