from src.agents.orchestrator import ApplicationOrchestrator
from src.errors import AgentExecutionError
from src.schemas import ResumeDocument
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


class FakeUnavailableOpenAIService:
    model = "fake-model"

    @staticmethod
    def is_available():
        return False


class FakeOpenAIService:
    def __init__(self):
        self.model = "fake-model"
        self._responses = [
            {
                "positioning_headline": "Applied AI engineer with grounded product delivery evidence",
                "evidence_highlights": ["Python", "Docker", "Production applications"],
                "strengths": ["Hands-on Python delivery", "Usable resume evidence"],
                "cautions": ["AWS is not evidenced directly"],
            },
            {
                "requirement_summary": "Production ML role with strong implementation expectations.",
                "priority_skills": ["Python", "SQL", "Docker", "AWS"],
                "must_have_themes": ["Production ML systems", "Communication"],
                "messaging_guidance": ["Mirror delivery language from the JD."],
            },
            {
                "fit_summary": "Strong fit overall with one visible cloud gap.",
                "top_matches": ["Python", "SQL", "Docker"],
                "key_gaps": ["AWS"],
                "interview_themes": ["Production delivery", "Cross-team communication"],
            },
            {
                "professional_summary": "Grounded summary for the role.",
                "rewritten_bullets": ["Built production applications using Python and Docker."],
                "highlighted_skills": ["Python", "SQL", "Docker"],
                "cover_letter_themes": ["Strong implementation fit."],
            },
            {
                "approved": True,
                "grounding_issues": [],
                "revision_requests": [],
                "final_notes": ["Grounded output."],
            },
        ]

    @staticmethod
    def is_available():
        return True

    def run_json_prompt(self, system_prompt, user_prompt, expected_keys=None, **kwargs):
        return self._responses.pop(0)


class FailingOpenAIService:
    model = "failing-model"

    @staticmethod
    def is_available():
        return True

    @staticmethod
    def run_json_prompt(system_prompt, user_prompt, expected_keys=None, **kwargs):
        raise AgentExecutionError("boom")


def test_orchestrator_runs_in_deterministic_fallback_mode():
    orchestrator = ApplicationOrchestrator(openai_service=FakeUnavailableOpenAIService())

    result = orchestrator.run(_build_candidate_profile(), _build_job_description())

    assert result.mode == "deterministic_fallback"
    assert result.model == "fallback"
    assert result.profile.positioning_headline
    assert result.fit.fit_summary
    assert result.tailoring.professional_summary


def test_orchestrator_uses_openai_service_when_available():
    orchestrator = ApplicationOrchestrator(openai_service=FakeOpenAIService())

    result = orchestrator.run(_build_candidate_profile(), _build_job_description())

    assert result.mode == "openai"
    assert result.model == "fake-model"
    assert result.profile.positioning_headline == (
        "Applied AI engineer with grounded product delivery evidence"
    )
    assert result.review.approved is True
    assert result.tailoring.rewritten_bullets == [
        "Built production applications using Python and Docker."
    ]


def test_orchestrator_falls_back_if_ai_execution_fails():
    orchestrator = ApplicationOrchestrator(openai_service=FailingOpenAIService())

    result = orchestrator.run(_build_candidate_profile(), _build_job_description())

    assert result.mode == "deterministic_fallback"
    assert result.model == "fallback"
    assert result.review.final_notes
