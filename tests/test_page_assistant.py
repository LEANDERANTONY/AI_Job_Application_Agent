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
    assert context["assistant_requires_login"] is True
    assert context["daily_quota"]["plan_tier"] == "free"


def test_build_product_help_context_for_question_includes_retrieved_knowledge(monkeypatch):
    monkeypatch.setattr(
        page_assistant,
        "retrieve_product_knowledge",
        lambda question, current_page="": [{"title": "Reload Workspace", "source": "Reload Workspace", "content": "Restores saved state."}],
    )

    context = page_assistant._build_product_help_context_for_question(
        "How long does the saved workspace last?",
        current_page="Manual JD Input",
        workflow_view_model=None,
        artifact=None,
        report=None,
        ai_session=None,
    )

    assert context["current_page"] == "Manual JD Input"
    assert context["knowledge_hits"][0]["source"] == "Reload Workspace"


def test_submit_assistant_question_returns_false_for_blank_input():
    submitted = page_assistant._submit_assistant_question(
        current_page="Upload Resume",
        question="   ",
        history=[],
    )

    assert submitted is False


def test_submit_assistant_question_returns_false_when_signed_out(monkeypatch):
    monkeypatch.setattr(page_assistant, "is_authenticated", lambda: False)

    submitted = page_assistant._submit_assistant_question(
        current_page="Upload Resume",
        question="How do I start?",
        history=[],
    )

    assert submitted is False


def test_submit_assistant_question_appends_turn_and_updates_usage(monkeypatch):
    captured = {}
    fake_response = SimpleNamespace(answer="Use Upload Resume first.", sources=["Upload Resume"], suggested_follow_ups=[])
    fake_session = SimpleNamespace(
        openai_service=SimpleNamespace(
            get_usage_snapshot=lambda: {
                "request_count": 1,
                "last_response_metadata": {"response_id": "resp_123"},
            }
        )
    )

    class FakeAssistantService:
        def __init__(self, openai_service=None):
            captured["openai_service"] = openai_service

        def answer(self, question, current_page, workflow_view_model=None, report=None, artifact=None, history=None, app_context=None, previous_response_id=None):
            captured["question"] = question
            captured["current_page"] = current_page
            captured["history"] = history
            captured["app_context"] = app_context
            return fake_response

    monkeypatch.setattr(page_assistant, "is_authenticated", lambda: True)
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
    assert captured["usage"]["request_count"] == 1


def test_clear_chat_resets_history_without_session_memory(monkeypatch):
    captured = {}

    monkeypatch.setattr(page_assistant, "is_authenticated", lambda: True)
    monkeypatch.setattr(page_assistant, "should_clear_assistant_input", lambda: False)
    monkeypatch.setattr(page_assistant, "get_assistant_history", lambda mode: [])
    monkeypatch.setattr(page_assistant, "get_pending_assistant_question", lambda: None)
    monkeypatch.setattr(page_assistant, "is_assistant_responding", lambda: False)
    monkeypatch.setattr(page_assistant.st, "text_input", lambda *args, **kwargs: "")

    button_calls = {"count": 0}

    def fake_button(*args, **kwargs):
        button_calls["count"] += 1
        return button_calls["count"] == 2

    monkeypatch.setattr(page_assistant.st, "button", fake_button)
    monkeypatch.setattr(page_assistant, "clear_assistant_history", lambda mode: captured.update({"cleared_history": mode}))
    monkeypatch.setattr(page_assistant, "set_pending_assistant_question", lambda value: captured.update({"pending": value}))
    monkeypatch.setattr(page_assistant, "set_assistant_responding", lambda value: captured.update({"responding": value}))
    monkeypatch.setattr(page_assistant, "set_clear_assistant_input", lambda value: captured.update({"clear_input": value}))
    monkeypatch.setattr(page_assistant, "_rerun_assistant_panel", lambda compact=False: captured.update({"rerun": compact}))
    monkeypatch.setattr(page_assistant, "render_section_head", lambda *args, **kwargs: None)
    monkeypatch.setattr(page_assistant.st, "markdown", lambda *args, **kwargs: None)

    page_assistant._render_assistant_panel_contents(
        "Manual JD Input",
        show_divider=False,
        show_header=False,
        compact=False,
    )

    assert captured["cleared_history"] == "assistant"
    assert captured["pending"] is None
    assert captured["responding"] is False
    assert captured["clear_input"] is True
    assert captured["rerun"] is False
