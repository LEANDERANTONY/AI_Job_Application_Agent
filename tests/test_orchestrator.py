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
                "fit_summary": "Strong fit overall with one visible cloud gap.",
                "top_matches": ["Python", "SQL", "Docker"],
                "key_gaps": ["AWS"],
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
                "unresolved_issues": [],
                "revision_requests": [],
                "final_notes": ["Grounded output."],
                "corrected_tailoring": {
                    "professional_summary": "Grounded summary for the role.",
                    "rewritten_bullets": ["Built production applications using Python and Docker."],
                    "highlighted_skills": ["Python", "SQL", "Docker"],
                    "cover_letter_themes": ["Strong implementation fit."],
                },
            },
            {
                "professional_summary": "Final tailored summary for the generated resume.",
                "highlighted_skills": ["Python", "SQL", "Docker"],
                "experience_bullets": ["Built production applications using Python and Docker."],
                "section_order": ["Professional Summary", "Core Skills", "Professional Experience", "Education"],
                "template_hint": "classic_ats",
            },
            {
                "greeting": "Dear Hiring Team",
                "opening_paragraph": "I am excited to apply for the Machine Learning Engineer role and bring grounded implementation experience.",
                "body_paragraphs": [
                    "Strong implementation fit.",
                    "Built production applications using Python and Docker.",
                ],
                "closing_paragraph": "I would welcome the opportunity to discuss how my experience can support your team.",
                "signoff": "Sincerely",
                "signature_name": "Leander Antony",
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


class FakeCorrectionOpenAIService(FakeOpenAIService):
    def __init__(self):
        self.model = "fake-model"
        self._responses = [
            {
                "fit_summary": "Strong fit overall with one visible cloud gap.",
                "top_matches": ["Python", "SQL", "Docker"],
                "key_gaps": ["AWS"],
            },
            {
                "professional_summary": "Initial summary with unsupported AWS emphasis.",
                "rewritten_bullets": ["Led AWS-native production deployments for ML services."],
                "highlighted_skills": ["Python", "SQL", "AWS"],
                "cover_letter_themes": ["Strong cloud fit."],
            },
            {
                "approved": False,
                "grounding_issues": ["AWS claim is stronger than the source profile supports."],
                "unresolved_issues": [],
                "revision_requests": ["Remove unsupported AWS delivery claims and keep the summary grounded."],
                "final_notes": ["Grounded after direct review corrections."],
                "corrected_tailoring": {
                    "professional_summary": "Revised grounded summary for the role.",
                    "rewritten_bullets": ["Built production applications using Python and Docker."],
                    "highlighted_skills": ["Python", "SQL", "Docker"],
                    "cover_letter_themes": ["Lead with delivery evidence in Python and Docker."],
                },
            },
            {
                "professional_summary": "Resume-ready grounded summary for the role.",
                "highlighted_skills": ["Python", "SQL", "Docker"],
                "experience_bullets": ["Built production applications using Python and Docker."],
                "section_order": ["Professional Summary", "Core Skills", "Professional Experience", "Education"],
                "template_hint": "classic_ats",
            },
            {
                "greeting": "Dear Hiring Team",
                "opening_paragraph": "I am excited to apply for the Machine Learning Engineer role and bring grounded implementation experience.",
                "body_paragraphs": [
                    "Lead with delivery evidence in Python and Docker.",
                    "Highlight production applications that show end-to-end delivery.",
                ],
                "closing_paragraph": "I would welcome the opportunity to discuss how my experience can support your team.",
                "signoff": "Sincerely",
                "signature_name": "Leander Antony",
            },
        ]


def test_orchestrator_runs_in_deterministic_fallback_mode():
    orchestrator = ApplicationOrchestrator(openai_service=FakeUnavailableOpenAIService())

    result = orchestrator.run(_build_candidate_profile(), _build_job_description())

    assert result.mode == "deterministic_fallback"
    assert result.model == "fallback"
    assert result.attempted_assisted is False
    assert result.fit.fit_summary
    assert result.tailoring.professional_summary
    assert result.review_history == []


def test_orchestrator_uses_openai_service_when_available():
    orchestrator = ApplicationOrchestrator(openai_service=FakeOpenAIService())

    result = orchestrator.run(_build_candidate_profile(), _build_job_description())

    assert result.mode == "openai"
    assert result.model == "fake-model"
    assert result.profile.positioning_headline == ""
    assert result.job.requirement_summary == ""
    assert result.review.approved is True
    assert result.tailoring.rewritten_bullets == [
        "Built production applications using Python and Docker."
    ]
    assert result.strategy is None
    assert result.resume_generation.professional_summary == "Final tailored summary for the generated resume."
    assert result.cover_letter.opening_paragraph == "I am excited to apply for the Machine Learning Engineer role and bring grounded implementation experience."
    assert result.review_history == []


def test_orchestrator_falls_back_if_ai_execution_fails():
    orchestrator = ApplicationOrchestrator(openai_service=FailingOpenAIService())

    result = orchestrator.run(_build_candidate_profile(), _build_job_description())

    assert result.mode == "deterministic_fallback"
    assert result.model == "fallback"
    assert result.attempted_assisted is True
    assert result.fallback_reason == "boom"
    assert result.review.final_notes


def test_orchestrator_applies_review_corrections_without_second_pass():
    orchestrator = ApplicationOrchestrator(openai_service=FakeCorrectionOpenAIService())

    result = orchestrator.run(_build_candidate_profile(), _build_job_description())

    assert result.mode == "openai"
    assert result.review.approved is True
    assert result.review.grounding_issues == ["AWS claim is stronger than the source profile supports."]
    assert result.review.unresolved_issues == []
    assert result.tailoring.professional_summary == "Revised grounded summary for the role."
    assert result.strategy is None
    assert result.review.corrected_tailoring is not None
    assert result.review.corrected_strategy is None
    assert result.resume_generation.professional_summary == "Resume-ready grounded summary for the role."
    assert result.cover_letter is not None
    assert result.cover_letter.body_paragraphs[0] == "Lead with delivery evidence in Python and Docker."
    assert result.review_history == []


def test_orchestrator_reports_progress_updates_for_single_pass_flow():
    orchestrator = ApplicationOrchestrator(openai_service=FakeCorrectionOpenAIService())
    updates = []

    result = orchestrator.run(
        _build_candidate_profile(),
        _build_job_description(),
        progress_callback=lambda title, detail, value: updates.append((title, detail, value)),
    )

    assert result.mode == "openai"
    assert updates[0] == (
        "Workflow crew",
        "Opening your application brief and assigning the first agent.",
        3,
    )
    assert any(
        title == "Matchmaker agent"
        and detail == "Comparing both sides, scoring overlap, and flagging the real gaps."
        for title, detail, _ in updates
    )
    assert any(
        title == "Gatekeeper agent"
        and detail == "Reviewing the drafted outputs and applying grounded corrections."
        for title, detail, _ in updates
    )
    assert any(
        title == "Cover letter agent"
        and detail == "Turning the approved story into a role-specific cover letter that is ready to send."
        for title, detail, _ in updates
    )
    assert not any(title == "Navigator agent" for title, _, _ in updates)
    assert not any("Sent it back" in detail for _, detail, _ in updates)
    assert updates[-1] == (
        "Workflow crew",
        "All agents are done. Finalizing your application outputs.",
        100,
    )
