from src.agents.cover_letter_agent import CoverLetterAgent
from src.schemas import CandidateProfile, FitAnalysis, JobDescription, JobRequirements, TailoredResumeDraft, TailoringAgentOutput, WorkExperience


class FakeThirdPersonOpenAIService:
    model = "fake-model"

    @staticmethod
    def is_available():
        return True

    @staticmethod
    def run_json_prompt(system_prompt, user_prompt, expected_keys=None, **kwargs):
        return {
            "greeting": "Dear Hiring Team",
            "opening_paragraph": "I am excited to apply for the Data Scientist role. Leander Antony is a project-based machine-learning candidate with hands-on Python experience.",
            "body_paragraphs": [
                "His portfolio work includes predictive modeling and validation projects.",
            ],
            "closing_paragraph": "He would welcome the opportunity to discuss the role further.",
            "signoff": "Sincerely",
            "signature_name": "Leander Antony",
        }


def test_cover_letter_agent_falls_back_when_ai_uses_third_person_self_reference():
    agent = CoverLetterAgent(openai_service=FakeThirdPersonOpenAIService())
    candidate_profile = CandidateProfile(
        full_name="Leander Antony",
        experience=[
            WorkExperience(
                title="AI Engineer",
                organization="Example Labs",
            )
        ],
    )
    job_description = JobDescription(
        title="Data Scientist",
        raw_text="",
        cleaned_text="",
        requirements=JobRequirements(hard_skills=["Python", "SQL"]),
    )
    fit_analysis = FitAnalysis(
        target_role="Data Scientist",
        overall_score=82,
        readiness_label="Strong",
        matched_hard_skills=["Python", "SQL"],
        experience_signal="I have built predictive models and validation workflows in portfolio projects.",
    )
    tailored_draft = TailoredResumeDraft(
        target_role="Data Scientist",
        professional_summary="Project-based machine learning candidate with grounded Python experience.",
        highlighted_skills=["Python", "SQL"],
    )
    tailoring_output = TailoringAgentOutput(
        professional_summary="Project-based machine learning candidate with grounded Python experience.",
        cover_letter_themes=["Highlight predictive modeling and validation work."],
    )

    result = agent.run(
        candidate_profile,
        job_description,
        fit_analysis,
        tailored_draft,
        tailoring_output,
    )

    assert "Leander Antony is" not in result.opening_paragraph
    assert "His portfolio work" not in " ".join(result.body_paragraphs)
    assert result.opening_paragraph.startswith("I am excited to apply for the Data Scientist role.")
    assert result.closing_paragraph.startswith("I would welcome the opportunity to discuss")
