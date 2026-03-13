from src.schemas import ResumeDocument
from src.services.fit_service import build_fit_analysis
from src.services.job_service import build_job_description_from_text
from src.services.profile_service import (
    build_candidate_profile_from_linkedin_data,
    build_candidate_profile_from_resume,
    merge_candidate_profiles,
)


def test_build_fit_analysis_scores_grounded_match():
    resume_profile = build_candidate_profile_from_resume(
        ResumeDocument(
            text=(
                "Leander Antony\n"
                "Chennai, India\n"
                "Python SQL Docker communication\n"
                "Built machine learning pipelines and production apps."
            ),
            filetype="TXT",
            source="uploaded",
        )
    )
    linkedin_profile = build_candidate_profile_from_linkedin_data(
        {
            "summary": {
                "name": "Leander Antony",
                "headline": "Machine Learning Engineer",
                "location": "Chennai",
                "summary": "Builds applied AI systems.",
            },
            "skills": ["Python", "SQL", "Docker"],
            "experience": [
                {
                    "title": "ML Engineer",
                    "company": "Example Labs",
                    "location": "Chennai",
                    "description": "Led communication across teams while shipping ML services.",
                    "start": {"year": 2022},
                    "end": {"year": 2025},
                }
            ],
        }
    )
    candidate_profile = merge_candidate_profiles(resume_profile, linkedin_profile)
    job_description = build_job_description_from_text(
        "Machine Learning Engineer\n"
        "Location: Chennai, India\n"
        "Need 3+ years of experience with Python, SQL, Docker, AWS, and communication.\n"
    )

    fit_analysis = build_fit_analysis(candidate_profile, job_description)

    assert fit_analysis.target_role == "Machine Learning Engineer"
    assert fit_analysis.readiness_label == "Strong match"
    assert fit_analysis.overall_score >= 80
    assert fit_analysis.matched_hard_skills == ["Python", "SQL", "Docker"]
    assert fit_analysis.missing_hard_skills == ["AWS"]
    assert fit_analysis.matched_soft_skills == ["communication"]
    assert "Approx. 3.0 years of experience" in fit_analysis.experience_signal
