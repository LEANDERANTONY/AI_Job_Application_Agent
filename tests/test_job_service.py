from src.services.job_service import build_job_description_from_text


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
