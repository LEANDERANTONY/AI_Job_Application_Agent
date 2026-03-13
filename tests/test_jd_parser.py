from io import BytesIO

from src.jd_parser import clean_text, extract_job_details, parse_jd_file


class NamedBytesIO(BytesIO):
    def __init__(self, initial_bytes, name):
        super().__init__(initial_bytes)
        self.name = name


def test_parse_jd_file_reads_text_upload():
    handle = NamedBytesIO(b"ML Engineer\nLocation: Bengaluru", "sample_jd.txt")

    parsed = parse_jd_file(handle)

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

