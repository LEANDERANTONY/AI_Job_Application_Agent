import pytest

from src.errors import InputValidationError
from src.services.job_service import build_job_description_from_text, extract_job_summary_sections


def test_build_job_description_from_text_extracts_requirement_signals():
    raw_text = (
        "Machine Learning Engineer\n"
        "Location: Chennai, India\n"
        "Required: Python, SQL, Docker, and strong communication.\n"
        "Must have experience deploying ML services.\n"
        "Nice to have: AWS exposure.\n"
        "Need 3+ years of experience.\n"
    )

    job_description = build_job_description_from_text(raw_text)

    assert job_description.title == "Machine Learning Engineer"
    assert job_description.location == "Chennai, India"
    assert job_description.requirements.experience_requirement == "3+ years of experience"
    assert job_description.requirements.hard_skills == ["Python", "SQL", "Docker", "AWS"]
    assert job_description.requirements.soft_skills == ["communication"]
    assert job_description.requirements.must_haves
    assert job_description.requirements.nice_to_haves == ["Nice to have: AWS exposure."]


def test_build_job_description_from_text_rejects_blank_input():
    with pytest.raises(InputValidationError):
        build_job_description_from_text("   ")


def test_build_job_description_from_text_deduplicates_requirement_lines():
    raw_text = (
        "Backend Engineer\n"
        "Required: Python and SQL.\n"
        "Required: Python and SQL.\n"
        "Must have production API experience.\n"
        "Must have production API experience.\n"
    )

    job_description = build_job_description_from_text(raw_text)

    assert job_description.requirements.must_haves == [
        "Required: Python and SQL.",
        "Must have production API experience.",
    ]


def test_extract_job_summary_sections_maps_heading_aliases():
    cleaned_text = (
        "Sr. AI Engineer We’re building Navi for post-purchase resolution. "
        "What You’ll Work On Design and build conversational AI agents. "
        "Build RAG pipelines for grounded responses. "
        "What We’re Looking For Have strong Python skills. "
        "Have production LLM experience. "
        "Signals That You’ll Thrive Here You’ve worked in startup environments."
    )

    sections = extract_job_summary_sections(cleaned_text, title="Sr. AI Engineer")

    assert [section["title"] for section in sections] == [
        "Overview",
        "What You'll Work On",
        "What They're Looking For",
        "Good Signals",
    ]
    assert any("conversational AI agents" in item for item in sections[1]["items"])
    assert any("Python skills" in item for item in sections[2]["items"])


def test_extract_job_summary_sections_falls_back_to_overview():
    cleaned_text = (
        "Backend Engineer focused on building internal tooling and APIs for analytics teams."
    )

    sections = extract_job_summary_sections(cleaned_text, title="Backend Engineer")

    assert sections == [
        {
            "title": "Overview",
            "items": ["focused on building internal tooling and APIs for analytics teams."],
        }
    ]
