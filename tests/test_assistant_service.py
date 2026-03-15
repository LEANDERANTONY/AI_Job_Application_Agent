from types import SimpleNamespace

from src.assistant_service import AssistantService
from src.errors import AgentExecutionError
from src.schemas import ResumeDocument, WorkExperience
from src.services.fit_service import build_fit_analysis
from src.services.job_service import build_job_description_from_text
from src.services.profile_service import build_candidate_profile_from_resume
from src.services.tailoring_service import build_tailored_resume_draft


def _build_view_model():
    candidate_profile = build_candidate_profile_from_resume(
        ResumeDocument(
            text=(
                "Leander Antony\n"
                "Chennai, India\n"
                "Python SQL Docker communication\n"
                "Built production ML applications."
            ),
            filetype="TXT",
            source="uploaded",
        )
    )
    candidate_profile.experience = [
        WorkExperience(
            title="AI Engineer",
            organization="Example Labs",
            description="Built production ML APIs and model evaluation workflows.",
            start={"year": 2023},
            end={"year": 2025},
        )
    ]
    job_description = build_job_description_from_text(
        "Machine Learning Engineer\n"
        "Location: Chennai, India\n"
        "Required: Python, SQL, Docker, AWS, communication.\n"
        "Need 3+ years of experience.\n"
    )
    fit_analysis = build_fit_analysis(candidate_profile, job_description)
    tailored_draft = build_tailored_resume_draft(
        candidate_profile,
        job_description,
        fit_analysis,
    )
    return SimpleNamespace(
        candidate_profile=candidate_profile,
        job_description=job_description,
        fit_analysis=fit_analysis,
        tailored_draft=tailored_draft,
        agent_result=None,
    )


def test_product_help_fallback_explains_report_vs_resume():
    service = AssistantService()

    response = service.answer_product_help(
        "What is the difference between the report and the resume?",
        current_page="Manual JD Input",
        app_context={},
    )

    assert "tailored resume" in response.answer.lower()
    assert "report" in response.answer.lower()
    assert response.sources


def test_product_help_fallback_explains_navigation():
    service = AssistantService()

    response = service.answer_product_help(
        "Can you explain how the navigation tab works?",
        current_page="Saved Workspace",
        app_context={},
    )

    assert "sidebar navigation" in response.answer.lower()
    assert "saved workspace" in response.answer.lower()


def test_product_help_fallback_answers_assistant_identity_question():
    service = AssistantService()

    response = service.answer_product_help(
        "Hello what is your name?",
        current_page="Upload Resume",
        app_context={},
    )

    assert "product help assistant" in response.answer.lower()


def test_product_help_fallback_explains_session_and_daily_limits():
    service = AssistantService()

    response = service.answer_product_help(
        "What are the token and daily limits here?",
        current_page="Manual JD Input",
        app_context={},
    )

    assert "browser-session" in response.answer.lower()
    assert "daily quota" in response.answer.lower()
    assert response.sources


def test_application_qa_fallback_explains_gaps():
    service = AssistantService()
    view_model = _build_view_model()

    response = service.answer_application_qa(
        "What are my biggest gaps?",
        workflow_view_model=view_model,
        report=None,
        artifact=SimpleNamespace(highlighted_skills=["Python", "SQL"], validation_notes=[]),
    )

    assert "gap" in response.answer.lower() or "main gaps" in response.answer.lower()
    assert response.sources


def test_application_qa_requires_context_when_inputs_missing():
    service = AssistantService()
    empty_view_model = SimpleNamespace(candidate_profile=None, job_description=None)

    response = service.answer_application_qa(
        "Is this safe to submit?",
        workflow_view_model=empty_view_model,
        report=None,
        artifact=None,
    )

    assert "needs both a resume and a job description" in response.answer.lower()


def test_application_qa_fallback_supports_broader_resume_coaching():
    service = AssistantService()
    view_model = _build_view_model()

    response = service.answer_application_qa(
        "How can I show cross-functional collaboration without formal work experience?",
        workflow_view_model=view_model,
        report=None,
        artifact=SimpleNamespace(highlighted_skills=["Python", "SQL"], validation_notes=[]),
    )

    assert "general advice" in response.answer.lower()
    assert "context-specific recommendation" in response.answer.lower()
    assert response.sources


def test_product_help_falls_back_when_model_returns_blank_answer():
    class FakeOpenAIService:
        @staticmethod
        def is_available():
            return True

        @staticmethod
        def run_json_prompt(*args, **kwargs):
            return {
                "answer": "   ",
                "sources": ["Manual JD Input"],
                "suggested_follow_ups": [],
            }

    service = AssistantService(openai_service=FakeOpenAIService())

    response = service.answer_product_help(
        "How do I use the report?",
        current_page="Manual JD Input",
        app_context={},
    )

    assert response.answer
    assert "report" in response.answer.lower()


def test_product_help_uses_fast_fail_request_shape():
    class FakeOpenAIService:
        def __init__(self):
            self.calls = []

        @staticmethod
        def is_available():
            return True

        def run_json_prompt(self, *args, **kwargs):
            self.calls.append(kwargs)
            return {
                "answer": "Use Upload Resume first.",
                "sources": ["Upload Resume"],
                "suggested_follow_ups": [],
            }

    openai_service = FakeOpenAIService()
    service = AssistantService(openai_service=openai_service)

    response = service.answer_product_help(
        "Where do I start?",
        current_page="Upload Resume",
        app_context={},
    )

    assert response.answer == "Use Upload Resume first."
    assert len(openai_service.calls) == 1
    assert openai_service.calls[0]["task_name"] == "assistant_product_help"
    assert openai_service.calls[0]["temperature"] is None
    assert openai_service.calls[0]["allow_output_budget_retry"] is False


def test_build_response_raises_on_blank_answer_payload():
    try:
        AssistantService._build_response({"answer": "  "}, max_sources=3)
    except AgentExecutionError as exc:
        assert "empty answer" in exc.user_message.lower()
    else:
        raise AssertionError("Expected AgentExecutionError for blank assistant answer")


def test_build_application_qa_context_includes_review_and_skill_signals():
    artifact = SimpleNamespace(
        summary="Tailored summary",
        validation_notes=["Check claim wording"],
        highlighted_skills=["Python", "Communication"],
    )
    review = SimpleNamespace(
        approved=True,
        revision_requests=["Tighten bullet wording"],
        grounding_issues=[],
    )
    workflow_view_model = _build_view_model()
    workflow_view_model.agent_result = SimpleNamespace(review=review)

    context = AssistantService._build_application_qa_context(
        workflow_view_model,
        report=SimpleNamespace(summary="Report summary"),
        artifact=artifact,
    )

    assert context["current_highlighted_skills"] == ["Python", "Communication"]
    assert context["review_approved"] is True
    assert context["review_revision_requests"] == ["Tighten bullet wording"]