from src.agents.strategy_agent import StrategyAgent
from src.schemas import FitAgentOutput, ResumeDocument, TailoringAgentOutput
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
    )

    result = StrategyAgent()._fallback(
        candidate_profile,
        job_description,
        fit_analysis,
        fit_output,
    )

    assert "Machine Learning Engineer" in result.recruiter_positioning
    assert result.cover_letter_talking_points
    assert result.portfolio_project_emphasis


def test_strategy_agent_run_uses_openai_payload_when_available():
    candidate_profile = _build_candidate_profile()
    job_description = _build_job_description()
    fit_analysis = build_fit_analysis(candidate_profile, job_description)
    fit_output = FitAgentOutput(
        fit_summary="Strong fit overall.",
        top_matches=["Python", "SQL"],
        key_gaps=["AWS"],
    )
    captured = {}

    class FakeOpenAIService:
        def is_available(self):
            return True

        def run_json_prompt(
            self,
            system_prompt,
            user_prompt,
            expected_keys=None,
            max_completion_tokens=None,
            task_name=None,
            metadata=None,
        ):
            captured["task_name"] = task_name
            captured["expected_keys"] = expected_keys
            captured["max_completion_tokens"] = max_completion_tokens
            return {
                "recruiter_positioning": "Position the candidate around delivery strength.",
                "cover_letter_talking_points": ["Lead with delivery outcomes", "Lead with delivery outcomes"],
                "portfolio_project_emphasis": ["Platform APIs", "Platform APIs"],
            }

    result = StrategyAgent(openai_service=FakeOpenAIService()).run(
        candidate_profile,
        job_description,
        fit_analysis,
        fit_output=fit_output,
        tailoring_output=TailoringAgentOutput(
            professional_summary="Summary",
            rewritten_bullets=["Bullet"],
            highlighted_skills=["Python"],
            cover_letter_themes=["Theme"],
        ),
    )

    assert captured["task_name"] == "strategy"
    assert captured["max_completion_tokens"] == 2500
    assert result.cover_letter_talking_points == ["Lead with delivery outcomes"]
    assert result.portfolio_project_emphasis == ["Platform APIs"]
