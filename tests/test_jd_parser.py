from io import BytesIO
from pathlib import Path

from src.parsers.jd import clean_text, extract_job_details, parse_jd_text
from src.services.job_service import build_job_description_from_text


class NamedBytesIO(BytesIO):
    def __init__(self, initial_bytes, name):
        super().__init__(initial_bytes)
        self.name = name


def test_parse_jd_file_reads_text_upload():
    handle = NamedBytesIO(b"ML Engineer\nLocation: Bengaluru", "sample_jd.txt")

    parsed = parse_jd_text(handle)

    assert parsed == "ML Engineer\nLocation: Bengaluru"


def test_clean_text_preserves_lines_and_removes_bullets():
    raw_text = "ML Engineer\n\n• Python and SQL\n* Communication"

    cleaned = clean_text(raw_text)

    assert cleaned == "ML Engineer\nPython and SQL\nCommunication"


def test_extract_job_details_finds_core_fields():
    text = (
        "Machine Learning Engineer\n"
        "Location: Bengaluru, India\n"
        "Need 3+ years of experience with Python, SQL, Docker, and communication."
    )

    extracted = extract_job_details(text)

    assert extracted["title"] == "Machine Learning Engineer"
    assert extracted["location"] == "Bengaluru, India"
    assert extracted["experience_required"] == "3+ years of experience"
    assert extracted["skills"] == ["Python", "SQL", "Docker"]
    assert extracted["soft_skills"] == ["communication"]


def test_parse_jd_file_reads_pdf_fixture():
    sample_path = Path(__file__).resolve().parents[1] / "static" / "demo_job_description" / "Sample_Job_Description_MLEngineer.pdf"

    with sample_path.open("rb") as handle:
        parsed = parse_jd_text(handle)

    assert "Machine Learning Engineer" in parsed
    assert "Location: Hyderabad, India" in parsed
    assert "PyTorch" in parsed


def test_parse_jd_file_reads_docx_fixture():
    sample_path = Path(__file__).resolve().parents[1] / "static" / "demo_job_description" / "Sample_Job_Description_DataAnalyst.docx"

    with sample_path.open("rb") as handle:
        parsed = parse_jd_text(handle)

    assert "Data Analyst - Business Intelligence" in parsed
    assert "Location: Remote (India preferred)" in parsed
    assert "Power BI" in parsed


def test_build_job_description_from_pdf_fixture_extracts_expected_signals():
    sample_path = Path(__file__).resolve().parents[1] / "static" / "demo_job_description" / "Sample_Job_Description_MLEngineer.pdf"

    with sample_path.open("rb") as handle:
        parsed = parse_jd_text(handle)

    job_description = build_job_description_from_text(parsed)

    assert job_description.title == "Machine Learning Engineer"
    assert job_description.location == "Hyderabad, India"
    assert job_description.requirements.experience_requirement == "4+ years of experience"
    assert "PyTorch" in job_description.requirements.hard_skills
    assert "communication" in job_description.requirements.soft_skills


def test_build_job_description_from_docx_fixture_extracts_expected_signals():
    sample_path = Path(__file__).resolve().parents[1] / "static" / "demo_job_description" / "Sample_Job_Description_DataAnalyst.docx"

    with sample_path.open("rb") as handle:
        parsed = parse_jd_text(handle)

    job_description = build_job_description_from_text(parsed)

    assert job_description.title == "Data Analyst - Business Intelligence"
    assert job_description.location == "Remote (India preferred)"
    assert job_description.requirements.experience_requirement == "2+ years in data analysis or business intelligence"
    assert "SQL" in job_description.requirements.hard_skills
    assert "problem-solving" in job_description.requirements.soft_skills
    assert job_description.requirements.nice_to_haves == []

