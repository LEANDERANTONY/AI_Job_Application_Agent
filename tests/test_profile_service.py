from src.schemas import ResumeDocument
from src.services.profile_service import (
    build_candidate_profile_from_resume,
    build_candidate_context_text,
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


def test_build_candidate_context_text_uses_resume_fields_only():
    profile = build_candidate_profile_from_resume(
        ResumeDocument(
            text="Leander Antony\nChennai, India\nPython SQL\nBuilt ML services.",
            filetype="TXT",
            source="uploaded",
        )
    )

    context = build_candidate_context_text(profile)

    assert "Leander Antony" in context
    assert "Python SQL" in context
