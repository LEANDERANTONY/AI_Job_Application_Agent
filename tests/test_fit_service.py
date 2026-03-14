from src.schemas import ResumeDocument
from src.services.fit_service import build_fit_analysis
from src.services.job_service import build_job_description_from_text
from src.services.profile_service import build_candidate_profile_from_resume


def test_build_fit_analysis_scores_grounded_match():
    candidate_profile = build_candidate_profile_from_resume(
        ResumeDocument(
            text=(
                "Leander Antony\n"
                "Chennai, India\n"
                "Python SQL Docker communication\n"
                "3 years of machine learning experience.\n"
                "Built machine learning pipelines and production apps.\n"
                "ML Engineer at Example Labs\n"
                "Led communication across teams while shipping ML services."
            ),
            filetype="TXT",
            source="uploaded",
        )
    )
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
