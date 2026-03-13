from src.schemas import ResumeDocument, WorkExperience
from src.services.fit_service import build_fit_analysis
from src.services.job_service import build_job_description_from_text
from src.services.profile_service import build_candidate_profile_from_resume
from src.services.tailoring_service import build_tailored_resume_draft


def test_build_tailored_resume_draft_returns_grounded_sections():
    candidate_profile = build_candidate_profile_from_resume(
        ResumeDocument(
            text=(
                "Leander Antony\n"
                "Chennai, India\n"
                "Python SQL Docker communication\n"
                "Built production ML systems."
            ),
            filetype="TXT",
            source="uploaded",
        )
    )
    candidate_profile.experience = [
        WorkExperience(
            title="AI Engineer",
            organization="Example Labs",
            location="Chennai",
            description="Built production ML APIs and automated model evaluation.",
            start={"year": 2023},
            end={"year": 2025},
        )
    ]
    job_description = build_job_description_from_text(
        "Machine Learning Engineer\n"
        "Required: Python, SQL, Docker, AWS, communication.\n"
        "Must have experience deploying ML services.\n"
    )
    fit_analysis = build_fit_analysis(candidate_profile, job_description)

    tailored_draft = build_tailored_resume_draft(
        candidate_profile,
        job_description,
        fit_analysis,
    )

    assert tailored_draft.target_role == "Machine Learning Engineer"
    assert "Machine Learning Engineer" in tailored_draft.professional_summary
    assert tailored_draft.highlighted_skills[:3] == ["Python", "SQL", "Docker"]
    assert tailored_draft.priority_bullets
    assert any("AWS" in step for step in tailored_draft.gap_mitigation_steps)
