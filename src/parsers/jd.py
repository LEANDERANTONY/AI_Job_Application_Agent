import re
from io import BytesIO

import docx
import streamlit as st
from pypdf import PdfReader

from src.errors import ParsingError
from src.parsers.common import decode_text, detect_file_type, read_file_bytes


SKILL_KEYWORDS = [
    "Python",
    "SQL",
    "Machine Learning",
    "Data Analysis",
    "Deep Learning",
    "NLP",
    "AWS",
    "Excel",
    "TensorFlow",
    "PyTorch",
    "Power BI",
    "Docker",
    "Kubernetes",
]

SOFT_SKILL_KEYWORDS = [
    "communication",
    "teamwork",
    "problem-solving",
    "leadership",
    "adaptability",
    "time management",
    "collaboration",
    "critical thinking",
]


def _unique_matches(text, keywords):
    lowered_text = text.lower()
    return [keyword for keyword in keywords if keyword.lower() in lowered_text]


@st.cache_data(show_spinner="Parsing uploaded job description...")
def _parse_jd_bytes(file_bytes, file_type):
    if file_type == "text/plain":
        text = decode_text(file_bytes)
    elif file_type == "application/pdf":
        try:
            pdf = PdfReader(BytesIO(file_bytes))
        except Exception as exc:
            raise ParsingError("Failed to open the PDF job description.") from exc
        text = "\n".join((page.extract_text() or "").strip() for page in pdf.pages)
    elif file_type in {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
    }:
        try:
            document = docx.Document(BytesIO(file_bytes))
        except Exception as exc:
            raise ParsingError("Failed to open the DOCX job description.") from exc
        text = "\n".join(
            paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text
        )
    else:
        raise ParsingError("Unsupported job-description file type. Use PDF, DOCX, or TXT.")

    if not text.strip():
        raise ParsingError("The job description was parsed, but no readable text was extracted.")
    return text


def parse_jd_text(file):
    file_type = detect_file_type(file)
    file_bytes = read_file_bytes(file)
    return _parse_jd_bytes(file_bytes, file_type)


@st.cache_data(show_spinner="Cleaning job description...")
def clean_text(text):
    normalized_lines = []
    for raw_line in text.replace("\r", "\n").replace("\xa0", " ").splitlines():
        line = re.sub(r"[\u2022\u25cf*]", " ", raw_line)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            normalized_lines.append(line)
    return "\n".join(normalized_lines)


@st.cache_data(show_spinner="Extracting job info...")
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
        r"(\d+\+?\s*(?:years?|yrs?)(?:\s+of)?\s+experience)",
        text,
        re.IGNORECASE,
    )
    return {
        "title": title,
        "location": location_match.group(1).strip() if location_match else None,
        "experience_required": experience_match.group(1).strip()
        if experience_match
        else None,
        "skills": _unique_matches(body_text, SKILL_KEYWORDS),
        "soft_skills": _unique_matches(body_text, SOFT_SKILL_KEYWORDS),
    }

