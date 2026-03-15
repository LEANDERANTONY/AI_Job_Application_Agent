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


def test_build_product_help_context_includes_saved_workspace_navigation(monkeypatch):
    monkeypatch.setattr(page_assistant, "is_authenticated", lambda: True)

    context = page_assistant._build_product_help_context(
        workflow_view_model=SimpleNamespace(candidate_profile=object(), job_description=object()),
        artifact=object(),
        report=object(),
    )

    assert "Saved Workspace" in context["available_pages"]
    assert context["signed_in_actions"] == ["Reload Saved Workspace"]
    assert context["has_resume"] is True
    assert context["has_job_description"] is True
    assert context["has_tailored_resume"] is True
    assert context["has_report"] is True