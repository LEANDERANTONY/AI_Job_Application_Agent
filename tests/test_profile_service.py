from src.schemas import ResumeDocument
from src.services.profile_service import (
    build_candidate_profile_from_linkedin_data,
    build_candidate_profile_from_resume,
    merge_candidate_profiles,
)


def test_build_candidate_profile_from_resume_extracts_core_signals():
    document = ResumeDocument(
        text=(
            "Leander Antony\n"
            "Chennai, India\n"
            "Machine Learning Engineer\n"
            "Python SQL Docker communication"
        ),
        filetype="PDF",
        source="uploaded",
    )

    profile = build_candidate_profile_from_resume(document)

    assert profile.full_name == "Leander Antony"
    assert profile.location == "Chennai, India"
    assert {"Python", "SQL", "Docker", "communication"}.issubset(set(profile.skills))
    assert "Resume parsed from PDF upload." in profile.source_signals


def test_merge_candidate_profiles_combines_resume_and_linkedin_data():
    resume_profile = build_candidate_profile_from_resume(
        ResumeDocument(
            text="Leander Antony\nChennai, India\nPython SQL",
            filetype="TXT",
            source="uploaded",
        )
    )
    linkedin_profile = build_candidate_profile_from_linkedin_data(
        {
            "summary": {
                "name": "Leander Antony",
                "headline": "AI Engineer",
                "location": "Chennai",
                "summary": "Builds production AI apps.",
            },
            "skills": ["Python", "AWS"],
            "experience": [
                {
                    "title": "AI Engineer",
                    "company": "Example Labs",
                    "location": "Chennai",
                    "description": "Built ML services.",
                    "start": {"year": 2023},
                    "end": {"year": 2025},
                }
            ],
        }
    )

    merged = merge_candidate_profiles(resume_profile, linkedin_profile)

    assert merged is not None
    assert merged.full_name == "Leander Antony"
    assert merged.location == "Chennai"
    assert merged.source == "uploaded+linkedin_export"
    assert set(merged.skills) == {"Python", "SQL", "AWS"}
    assert len(merged.experience) == 1
    assert len(merged.source_signals) >= 2
