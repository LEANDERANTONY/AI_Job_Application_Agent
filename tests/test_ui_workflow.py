import pytest

from src.errors import InputValidationError
from src.schemas import (
    ArtifactRecord,
    CandidateProfile,
    JobDescription,
    JobRequirements,
    ResumeDocument,
    WorkflowRunRecord,
)
from src.ui import workflow


def test_resolve_job_description_input_prefers_pasted_text(monkeypatch):
    monkeypatch.setattr(workflow, "get_state", lambda key, default=None: default)
    monkeypatch.setattr(workflow, "parse_jd_text", lambda uploaded_jd: "uploaded text")
    monkeypatch.setattr(workflow, "_load_sample_jd", lambda filename: "sample text")

    jd_text, jd_source = workflow.resolve_job_description_input(
        uploaded_jd=object(),
        selected_sample="sample.txt",
        pasted_text="pasted text",
    )

    assert jd_text == "pasted text"
    assert jd_source == "Pasted text"


def test_use_sample_resume_stores_resume_and_profile(monkeypatch):
    resume_document = ResumeDocument(text="resume text", filetype="TXT", source="sample:test")
    candidate_profile = CandidateProfile(full_name="Leander Antony")
    stored = {}

    monkeypatch.setattr(workflow, "_load_sample_resume", lambda filename: resume_document)
    monkeypatch.setattr(
        workflow,
        "build_candidate_profile_from_resume",
        lambda document: candidate_profile,
    )
    monkeypatch.setattr(
        workflow,
        "store_resume_intake",
        lambda document, profile: stored.update({"document": document, "profile": profile}),
    )

    result_document, result_profile = workflow.use_sample_resume("sample.txt")

    assert result_document is resume_document
    assert result_profile is candidate_profile
    assert stored["document"] is resume_document
    assert stored["profile"] is candidate_profile


def test_build_job_workflow_view_model_returns_job_only_without_candidate_profile(monkeypatch):
    job_description = JobDescription(
        title="Machine Learning Engineer",
        raw_text="raw",
        cleaned_text="cleaned",
        requirements=JobRequirements(hard_skills=["Python"]),
    )

    monkeypatch.setattr(workflow, "build_job_description_from_text", lambda text: job_description)
    monkeypatch.setattr(workflow, "store_job_description_inputs", lambda *args, **kwargs: None)
    monkeypatch.setattr(workflow, "get_active_candidate_profile", lambda: None)

    view_model = workflow.build_job_workflow_view_model("jd text", "Pasted text")

    assert view_model.job_description is job_description
    assert view_model.candidate_profile is None
    assert view_model.fit_analysis is None
    assert view_model.ai_session is None


def test_run_supervised_workflow_requires_authentication_when_enabled(monkeypatch):
    monkeypatch.setattr(workflow, "AUTH_REQUIRED_FOR_ASSISTED_WORKFLOW", True)
    monkeypatch.setattr(workflow, "is_authenticated", lambda: False)

    view_model = workflow.JobWorkflowViewModel(jd_text="jd", jd_source="Manual")

    with pytest.raises(InputValidationError):
        workflow.run_supervised_workflow(view_model)


def test_refresh_authenticated_history_selects_requested_run(monkeypatch):
    workflow_runs = [
        WorkflowRunRecord(
            id="run-1",
            user_id="user-123",
            job_title="Data Analyst",
            fit_score=82,
            review_approved=True,
            model_policy="gpt-5.4",
            created_at="2026-03-14T00:00:00+00:00",
        ),
        WorkflowRunRecord(
            id="run-2",
            user_id="user-123",
            job_title="ML Engineer",
            fit_score=76,
            review_approved=False,
            model_policy="gpt-5-mini-2025-08-07",
            created_at="2026-03-14T01:00:00+00:00",
        ),
    ]
    artifacts = [
        ArtifactRecord(
            id="artifact-1",
            workflow_run_id="run-2",
            artifact_type="application_bundle_zip",
            filename_stem="ml-engineer-application-bundle",
            storage_path="ml-engineer-application-bundle.zip",
            created_at="2026-03-14T01:05:00+00:00",
        )
    ]
    captured = {}

    class FakeHistoryStore:
        def is_configured(self):
            return True

        def list_recent_workflow_runs(self, access_token, refresh_token, user_id, limit=10):
            captured["workflow_runs_request"] = (access_token, refresh_token, user_id, limit)
            return workflow_runs

        def list_recent_artifacts(self, access_token, refresh_token, workflow_run_id, limit=20):
            captured["artifact_request"] = (access_token, refresh_token, workflow_run_id, limit)
            return artifacts

    monkeypatch.setattr(workflow, "get_app_user_record", lambda: type("AppUser", (), {"id": "user-123"})())
    monkeypatch.setattr(workflow, "get_auth_tokens", lambda: ("access-token", "refresh-token"))
    monkeypatch.setattr(workflow, "get_selected_history_workflow_run_id", lambda: None)
    monkeypatch.setattr(workflow, "get_active_workflow_run", lambda: None)
    monkeypatch.setattr(workflow, "AuthService", lambda: object())
    monkeypatch.setattr(workflow, "HistoryStore", lambda auth_service: FakeHistoryStore())
    monkeypatch.setattr(workflow, "set_workflow_history", lambda rows: captured.update({"workflow_runs": rows}))
    monkeypatch.setattr(workflow, "set_selected_history_workflow_run_id", lambda run_id: captured.update({"selected_run_id": run_id}))
    monkeypatch.setattr(workflow, "set_artifact_history", lambda rows: captured.update({"artifacts": rows}))

    resolved_runs, resolved_artifacts = workflow.refresh_authenticated_history("run-2")

    assert resolved_runs == workflow_runs
    assert resolved_artifacts == artifacts
    assert captured["selected_run_id"] == "run-2"
    assert captured["artifact_request"] == ("access-token", "refresh-token", "run-2", 20)


def test_refresh_authenticated_history_clears_state_without_auth(monkeypatch):
    captured = {}

    monkeypatch.setattr(workflow, "get_app_user_record", lambda: None)
    monkeypatch.setattr(workflow, "get_auth_tokens", lambda: (None, None))
    monkeypatch.setattr(workflow, "set_workflow_history", lambda rows: captured.update({"workflow_runs": rows}))
    monkeypatch.setattr(workflow, "set_artifact_history", lambda rows: captured.update({"artifacts": rows}))
    monkeypatch.setattr(workflow, "set_selected_history_workflow_run_id", lambda run_id: captured.update({"selected_run_id": run_id}))

    resolved_runs, resolved_artifacts = workflow.refresh_authenticated_history()

    assert resolved_runs == []
    assert resolved_artifacts == []
    assert captured["workflow_runs"] == []
    assert captured["artifacts"] == []
    assert captured["selected_run_id"] is None


def test_build_saved_documents_from_workflow_run_payloads():
    workflow_run = WorkflowRunRecord(
        id="run-1",
        user_id="user-123",
        report_payload_json='{"title": "Saved Report", "filename_stem": "saved-report", "summary": "summary", "markdown": "# Report", "plain_text": "Report"}',
        tailored_resume_payload_json='{"title": "Saved Resume", "filename_stem": "saved-resume", "summary": "summary", "markdown": "# Resume", "plain_text": "Resume", "theme": "modern_professional"}',
    )

    saved_report = workflow.build_saved_report_from_workflow_run(workflow_run)
    saved_resume = workflow.build_saved_tailored_resume_from_workflow_run(workflow_run)

    assert saved_report.title == "Saved Report"
    assert saved_report.filename_stem == "saved-report"
    assert saved_resume.title == "Saved Resume"
    assert saved_resume.theme == "modern_professional"