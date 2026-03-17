import pytest

from src.errors import InputValidationError
from src.services.job_service import build_job_description_from_text


class FakeJDParserOpenAIService:
    @staticmethod
    def is_available():
        return True

    @staticmethod
    def run_json_prompt(system_prompt, user_prompt, expected_keys=None, **kwargs):
        return {
            "title": "Senior Machine Learning Engineer",
            "location": "Chennai, India",
            "hard_skills": ["Python", "SQL", "Docker", "AWS"],
            "soft_skills": ["communication", "leadership"],
            "experience_requirement": "5+ years of experience",
            "must_haves": ["Must have experience deploying ML services."],
            "nice_to_haves": ["Nice to have: AWS exposure."],
            "verification_notes": ["Adjusted the title and experience threshold from the JD header."],
        }


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


def test_build_job_description_from_text_applies_jd_parser_agent_corrections():
    raw_text = (
        "Senior Machine Learning Engineer\n"
        "Location: Chennai, India\n"
        "Required: Python, SQL, Docker, and strong communication.\n"
        "Must have experience deploying ML services.\n"
        "Need 5+ years of experience.\n"
    )

    job_description = build_job_description_from_text(
        raw_text,
        openai_service=FakeJDParserOpenAIService(),
    )

    assert job_description.title == "Senior Machine Learning Engineer"
    assert job_description.location == "Chennai, India"
    assert job_description.requirements.experience_requirement == "5+ years of experience"
    assert job_description.requirements.soft_skills == ["communication", "leadership"]
    assert "Adjusted the title and experience threshold from the JD header." in job_description.parsing_notes
