from types import SimpleNamespace

from src.ui import page_assistant


def test_resolve_assistant_ai_session_prefers_workflow_session():
    existing_session = SimpleNamespace(openai_service=object())
    workflow_view_model = SimpleNamespace(ai_session=existing_session)

    resolved = page_assistant._resolve_assistant_ai_session(workflow_view_model)

    assert resolved is existing_session


def test_resolve_assistant_ai_session_builds_shared_session_when_missing(monkeypatch):
    built_session = SimpleNamespace(openai_service=object())
    monkeypatch.setattr(page_assistant, "build_ai_session_view_model", lambda: built_session)

    resolved = page_assistant._resolve_assistant_ai_session(None)

    assert resolved is built_session


def test_build_product_help_context_includes_reload_action(monkeypatch):
    monkeypatch.setattr(page_assistant, "is_authenticated", lambda: True)
    ai_session = SimpleNamespace(
        usage={
            "remaining_calls": 10,
            "remaining_total_tokens": 50000,
            "max_calls": 24,
            "max_total_tokens": 120000,
        },
        budget_reached=False,
        daily_quota=SimpleNamespace(
            plan_tier="free",
            remaining_calls=5,
            remaining_total_tokens=20000,
            quota_exhausted=False,
        ),
    )

    context = page_assistant._build_product_help_context(
        workflow_view_model=SimpleNamespace(candidate_profile=object(), job_description=object()),
        artifact=object(),
        report=object(),
        ai_session=ai_session,
    )

    assert context["available_pages"] == ["Upload Resume", "Job Search", "Manual JD Input"]
    assert context["signed_in_actions"] == ["Reload Workspace"]
    assert context["has_resume"] is True
    assert context["has_job_description"] is True
    assert context["has_tailored_resume"] is True
    assert context["has_report"] is True
    assert context["has_cover_letter"] is False
    assert context["session_usage"]["remaining_calls"] == 10
    assert context["daily_quota"]["plan_tier"] == "free"


def test_build_product_help_context_for_question_includes_retrieved_knowledge(monkeypatch):
    monkeypatch.setattr(
        page_assistant,
        "retrieve_product_knowledge",
        lambda question, current_page="": [{"title": "Saved Workspace", "source": "Saved Workspace", "content": "Restores saved state."}],
    )

    context = page_assistant._build_product_help_context_for_question(
        "How long does the saved workspace last?",
        current_page="Saved Workspace",
        workflow_view_model=None,
        artifact=None,
        report=None,
        ai_session=None,
    )

    assert context["current_page"] == "Saved Workspace"
    assert context["knowledge_hits"][0]["source"] == "Saved Workspace"


def test_submit_assistant_question_returns_false_for_blank_input():
    submitted = page_assistant._submit_assistant_question(
        current_page="Upload Resume",
        question="   ",
        history=[],
    )

    assert submitted is False


def test_submit_assistant_question_appends_turn_and_updates_usage(monkeypatch):
    captured = {}
    fake_response = SimpleNamespace(answer="Use Upload Resume first.", sources=["Upload Resume"], suggested_follow_ups=[])
    fake_session = SimpleNamespace(
        openai_service=SimpleNamespace(get_usage_snapshot=lambda: {"request_count": 1})
    )

    class FakeAssistantService:
        def __init__(self, openai_service=None):
            captured["openai_service"] = openai_service

        def answer(self, question, current_page, workflow_view_model=None, report=None, artifact=None, history=None, app_context=None):
            captured["question"] = question
            captured["current_page"] = current_page
            captured["history"] = history
            captured["app_context"] = app_context
            return fake_response

    monkeypatch.setattr(page_assistant, "_resolve_assistant_ai_session", lambda workflow_view_model=None: fake_session)
    monkeypatch.setattr(page_assistant, "AssistantService", FakeAssistantService)
    monkeypatch.setattr(page_assistant, "append_assistant_turn", lambda mode, turn: captured.update({"mode": mode, "turn": turn}))
    monkeypatch.setattr(page_assistant, "set_openai_session_usage", lambda usage: captured.update({"usage": usage}))

    submitted = page_assistant._submit_assistant_question(
        current_page="Upload Resume",
        question="How do I start?",
        history=[],
    )

    assert submitted is True
    assert captured["question"] == "How do I start?"
    assert captured["turn"].question == "How do I start?"
    assert captured["mode"] == "assistant"
    assert captured["turn"].response.answer == "Use Upload Resume first."
    assert captured["usage"] == {"request_count": 1}