from src.agents.resume_generation_agent import ResumeGenerationAgent
from src.schemas import CandidateProfile, FitAnalysis, ResumeGenerationAgentOutput, TailoredResumeDraft, TailoringAgentOutput


class FakePronounResumeOpenAIService:
    model = "fake-model"

    @staticmethod
    def is_available():
        return True

    @staticmethod
    def run_json_prompt(system_prompt, user_prompt, expected_keys=None, **kwargs):
        return {
            "professional_summary": "I am a project-based machine learning candidate with strong predictive modeling experience.",
            "highlighted_skills": ["Python", "SQL", "XGBoost"],
            "experience_bullets": [
                "I built predictive models for fraud detection.",
                "Leander Antony developed validation workflows for ML projects.",
            ],
            "section_order": ["Professional Summary", "Core Skills", "Professional Experience", "Education"],
            "template_hint": "classic_ats",
        }


def test_resume_generation_agent_falls_back_when_ai_uses_self_referential_resume_voice():
    agent = ResumeGenerationAgent(openai_service=FakePronounResumeOpenAIService())
    candidate_profile = CandidateProfile(full_name="Leander Antony")
    fit_analysis = FitAnalysis(
        target_role="Data Scientist",
        overall_score=84,
        readiness_label="Strong",
        matched_hard_skills=["Python", "SQL", "XGBoost"],
    )
    tailored_draft = TailoredResumeDraft(
        target_role="Data Scientist",
        professional_summary="Candidate profile aligned to Data Scientist with grounded evidence around Python, SQL, XGBoost.",
        highlighted_skills=["Python", "SQL", "XGBoost"],
        priority_bullets=["Built predictive modeling workflows for fraud detection use cases."],
    )
    tailoring_output = TailoringAgentOutput(
        professional_summary="Candidate profile aligned to Data Scientist with grounded evidence around Python, SQL, XGBoost.",
        rewritten_bullets=["Built predictive modeling workflows for fraud detection use cases."],
        highlighted_skills=["Python", "SQL", "XGBoost"],
    )

    result = agent.run(
        candidate_profile,
        job_description={"title": "Data Scientist"},
        fit_analysis=fit_analysis,
        tailored_draft=tailored_draft,
        tailoring_output=tailoring_output,
    )

    assert isinstance(result, ResumeGenerationAgentOutput)
    assert result.professional_summary == tailoring_output.professional_summary
    assert result.experience_bullets == ["Built predictive modeling workflows for fraud detection use cases."]
    assert all("I " not in bullet for bullet in result.experience_bullets)
