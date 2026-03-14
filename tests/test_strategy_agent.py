from src.agents.strategy_agent import StrategyAgent
from src.schemas import FitAgentOutput, ResumeDocument
from src.services.fit_service import build_fit_analysis
from src.services.job_service import build_job_description_from_text
from src.services.profile_service import build_candidate_profile_from_resume


def _build_candidate_profile():
    return build_candidate_profile_from_resume(
        ResumeDocument(
            text=(
                "Leander Antony\n"
                "Chennai, India\n"
                "Python SQL Docker communication\n"
                "Built machine learning pipelines and production applications."
            ),
            filetype="TXT",
            source="uploaded",
        )
    )


def _build_job_description():
    return build_job_description_from_text(
        "Machine Learning Engineer\n"
        "Location: Chennai, India\n"
        "Required: Python, SQL, Docker, AWS, communication.\n"
        "Need 3+ years of experience.\n"
    )


def test_strategy_agent_fallback_returns_grounded_sections():
    candidate_profile = _build_candidate_profile()
    job_description = _build_job_description()
    fit_analysis = build_fit_analysis(candidate_profile, job_description)
    fit_output = FitAgentOutput(
        fit_summary="Strong fit overall with one visible cloud gap.",
        top_matches=["Python", "SQL", "Docker"],
        key_gaps=["AWS"],
        interview_themes=["Production delivery", "Cross-team communication"],
    )

    result = StrategyAgent()._fallback(
        candidate_profile,
        job_description,
        fit_analysis,
        fit_output,
    )

    assert "Machine Learning Engineer" in result.recruiter_positioning
    assert result.cover_letter_talking_points
    assert result.interview_preparation_themes
    assert result.portfolio_project_emphasis