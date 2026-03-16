import pytest
from types import SimpleNamespace

from src.errors import InputValidationError
from src.schemas import (
    CandidateProfile,
    JobDescription,
    JobRequirements,
    ResumeDocument,
)
from src.ui import workflow_history, workflow_intake
from src.ui import workflow


def test_resolve_job_description_input_prefers_pasted_text(monkeypatch):
    monkeypatch.setattr(workflow_intake, "get_state", lambda key, default=None: default)
    monkeypatch.setattr(workflow_intake, "parse_jd_text", lambda uploaded_jd: "uploaded text")
    monkeypatch.setattr(workflow_intake, "_load_sample_jd", lambda filename: "sample text")

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

    monkeypatch.setattr(workflow_intake, "_load_sample_resume", lambda filename: resume_document)
    monkeypatch.setattr(
        workflow_intake,
        "build_candidate_profile_from_resume",
        lambda document: candidate_profile,
    )
    monkeypatch.setattr(
        workflow_intake,
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


def test_run_supervised_workflow_forwards_progress_callback(monkeypatch):
    captured = {}
    progress_updates = []
    expected_result = object()

    class FakeOrchestrator:
        def __init__(self, openai_service=None):
            captured["openai_service"] = openai_service

        def run(self, candidate_profile, job_description, fit_analysis, tailored_draft, progress_callback=None):
            captured["progress_callback"] = progress_callback
            progress_callback(
                "Scout agent",
                "Pulling out the strongest grounded proof points from your resume.",
                12,
            )
            return expected_result

    refreshed_view_model = workflow.JobWorkflowViewModel(jd_text="jd", jd_source="Manual")
    refreshed_view_model.agent_result = expected_result

    ai_session = SimpleNamespace(
        daily_quota=None,
        openai_service=SimpleNamespace(get_usage_snapshot=lambda: {"request_count": 1}),
    )
    view_model = workflow.JobWorkflowViewModel(
        jd_text="jd",
        jd_source="Manual",
        candidate_profile=CandidateProfile(full_name="Leander Antony"),
        job_description=JobDescription(
            title="ML Engineer",
            raw_text="raw",
            cleaned_text="cleaned",
            requirements=JobRequirements(hard_skills=["Python"]),
        ),
        fit_analysis=SimpleNamespace(),
        tailored_draft=SimpleNamespace(),
        ai_session=ai_session,
    )

    monkeypatch.setattr(workflow, "AUTH_REQUIRED_FOR_ASSISTED_WORKFLOW", False)
    monkeypatch.setattr(workflow, "ApplicationOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(workflow, "set_agent_workflow_result", lambda value: captured.update({"agent_result": value}))
    monkeypatch.setattr(workflow, "set_openai_session_usage", lambda value: captured.update({"usage_snapshot": value}))
    monkeypatch.setattr(workflow, "build_job_workflow_view_model", lambda jd_text, jd_source: refreshed_view_model)
    monkeypatch.setattr(workflow, "get_state", lambda key: expected_result)
    monkeypatch.setattr(workflow, "_persist_workflow_run", lambda current_view_model: captured.update({"persisted": current_view_model}))
    monkeypatch.setattr(workflow, "get_app_user_record", lambda: None)

    result = workflow.run_supervised_workflow(
        view_model,
        progress_callback=lambda title, detail, value: progress_updates.append((title, detail, value)),
    )

    assert result is refreshed_view_model
    assert captured["agent_result"] is expected_result
    assert captured["progress_callback"] is not None
    assert progress_updates == [
        (
            "Scout agent",
            "Pulling out the strongest grounded proof points from your resume.",
            12,
        )
    ]
    assert captured["usage_snapshot"] == {"request_count": 1}
    assert captured["persisted"] is refreshed_view_model


def test_run_supervised_workflow_refreshes_daily_quota_after_authenticated_run(monkeypatch):
    captured = {}
    expected_result = object()

    class FakeOrchestrator:
        def __init__(self, openai_service=None):
            captured["openai_service"] = openai_service

        def run(self, candidate_profile, job_description, fit_analysis, tailored_draft, progress_callback=None):
            return expected_result

    refreshed_view_model = workflow.JobWorkflowViewModel(jd_text="jd", jd_source="Manual")
    refreshed_view_model.agent_result = expected_result

    ai_session = SimpleNamespace(
        daily_quota=None,
        openai_service=SimpleNamespace(get_usage_snapshot=lambda: {"request_count": 2}),
    )
    view_model = workflow.JobWorkflowViewModel(
        jd_text="jd",
        jd_source="Manual",
        candidate_profile=CandidateProfile(full_name="Leander Antony"),
        job_description=JobDescription(
            title="ML Engineer",
            raw_text="raw",
            cleaned_text="cleaned",
            requirements=JobRequirements(hard_skills=["Python"]),
        ),
        fit_analysis=SimpleNamespace(),
        tailored_draft=SimpleNamespace(),
        ai_session=ai_session,
    )

    monkeypatch.setattr(workflow, "AUTH_REQUIRED_FOR_ASSISTED_WORKFLOW", False)
    monkeypatch.setattr(workflow, "ApplicationOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(workflow, "set_agent_workflow_result", lambda value: captured.update({"agent_result": value}))
    monkeypatch.setattr(workflow, "set_openai_session_usage", lambda value: captured.update({"usage_snapshot": value}))
    monkeypatch.setattr(workflow, "build_job_workflow_view_model", lambda jd_text, jd_source: refreshed_view_model)
    monkeypatch.setattr(workflow, "get_state", lambda key: expected_result)
    monkeypatch.setattr(workflow, "_persist_workflow_run", lambda current_view_model: captured.update({"persisted": current_view_model}))
    monkeypatch.setattr(
        workflow,
        "get_app_user_record",
        lambda: type("AppUser", (), {"id": "user-123", "plan_tier": "free"})(),
    )
    monkeypatch.setattr(
        workflow,
        "refresh_daily_quota_status",
        lambda force=False, now=None, auth_service=None: captured.update({"quota_refresh_force": force}),
    )

    result = workflow.run_supervised_workflow(view_model)

    assert result is refreshed_view_model
    assert captured["agent_result"] is expected_result
    assert captured["usage_snapshot"] == {"request_count": 2}
    assert captured["quota_refresh_force"] is True
    assert captured["persisted"] is refreshed_view_model


def test_refresh_authenticated_history_is_noop_under_saved_workspace_model(monkeypatch):
    resolved_runs, resolved_artifacts = workflow.refresh_authenticated_history("run-2")

    assert resolved_runs == []
    assert resolved_artifacts == []


def test_refresh_authenticated_history_clears_state_without_auth(monkeypatch):
    resolved_runs, resolved_artifacts = workflow.refresh_authenticated_history()

    assert resolved_runs == []
    assert resolved_artifacts == []


def test_build_saved_documents_from_workflow_run_payloads():
    workflow_run = SimpleNamespace(
        report_payload_json='{"version": 1, "kind": "application_report", "data": {"title": "Saved Report", "filename_stem": "saved-report", "summary": "summary", "markdown": "# Report", "plain_text": "Report"}}',
        tailored_resume_payload_json='{"version": 1, "kind": "tailored_resume_artifact", "data": {"title": "Saved Resume", "filename_stem": "saved-resume", "summary": "summary", "markdown": "# Resume", "plain_text": "Resume", "theme": "modern_professional"}}',
    )

    saved_report = workflow.build_saved_report_from_workflow_run(workflow_run)
    saved_resume = workflow.build_saved_tailored_resume_from_workflow_run(workflow_run)

    assert saved_report.title == "Saved Report"
    assert saved_report.filename_stem == "saved-report"
    assert saved_resume.title == "Saved Resume"
    assert saved_resume.theme == "modern_professional"


def test_build_saved_documents_supports_legacy_payloads():
    workflow_run = SimpleNamespace(
        report_payload_json='{"title": "Legacy Report", "filename_stem": "legacy-report", "summary": "summary", "markdown": "# Report", "plain_text": "Report"}',
        tailored_resume_payload_json='{"title": "Legacy Resume", "filename_stem": "legacy-resume", "summary": "summary", "markdown": "# Resume", "plain_text": "Resume", "theme": "classic_ats"}',
    )

    status = workflow.get_saved_workflow_payload_status(workflow_run)
    saved_report = workflow.build_saved_report_from_workflow_run(workflow_run)
    saved_resume = workflow.build_saved_tailored_resume_from_workflow_run(workflow_run)

    assert status["supported"] is True
    assert status["label"] == "Legacy v0"
    assert saved_report.filename_stem == "legacy-report"
    assert saved_resume.filename_stem == "legacy-resume"


def test_saved_payload_status_blocks_unsupported_future_version():
    workflow_run = SimpleNamespace(
        report_payload_json='{"version": 99, "kind": "application_report", "data": {"title": "Future Report"}}',
    )

    status = workflow.get_saved_workflow_payload_status(workflow_run)

    assert status["supported"] is False
    assert status["label"] == "v99 Unsupported"
    assert workflow.build_saved_report_from_workflow_run(workflow_run) is None


def test_refresh_daily_quota_status_uses_quota_service(monkeypatch):
    daily_quota = type("DailyQuota", (), {"quota_exhausted": False, "plan_tier": "free"})()

    class FakeUsageStore:
        def __init__(self, auth_service):
            self.auth_service = auth_service

        def is_configured(self):
            return True

    class FakeQuotaService:
        def __init__(self, auth_service, usage_store):
            self.auth_service = auth_service
            self.usage_store = usage_store

        def get_daily_quota_status(self, access_token, refresh_token, user_id, plan_tier):
            return daily_quota

    captured = {}
    monkeypatch.setattr(workflow, "get_daily_quota_status", lambda: None)
    monkeypatch.setattr(workflow, "get_daily_quota_status_refreshed_at", lambda: None)
    monkeypatch.setattr(
        workflow,
        "get_app_user_record",
        lambda: type("AppUser", (), {"id": "user-123", "plan_tier": "free"})(),
    )
    monkeypatch.setattr(workflow, "get_auth_tokens", lambda: ("access-token", "refresh-token"))
    monkeypatch.setattr(workflow, "get_auth_service", lambda: object())
    monkeypatch.setattr(workflow, "UsageStore", FakeUsageStore)
    monkeypatch.setattr(workflow, "QuotaService", FakeQuotaService)
    monkeypatch.setattr(
        workflow,
        "set_daily_quota_status",
        lambda value: captured.update({"daily_quota": value}),
    )
    monkeypatch.setattr(
        workflow,
        "set_daily_quota_status_refreshed_at",
        lambda value: captured.update({"refreshed_at": value}),
    )

    result = workflow.refresh_daily_quota_status(now=100.0)

    assert result is daily_quota
    assert captured["daily_quota"] is daily_quota
    assert captured["refreshed_at"] == 100.0


def test_refresh_daily_quota_status_uses_recent_cached_value(monkeypatch):
    daily_quota = type("DailyQuota", (), {"quota_exhausted": False, "plan_tier": "free"})()
    fetches = {"count": 0}

    class FakeUsageStore:
        def __init__(self, auth_service):
            self.auth_service = auth_service

        def is_configured(self):
            return True

    class FakeQuotaService:
        def __init__(self, auth_service, usage_store):
            self.auth_service = auth_service
            self.usage_store = usage_store

        def get_daily_quota_status(self, access_token, refresh_token, user_id, plan_tier):
            fetches["count"] += 1
            return daily_quota

    monkeypatch.setattr(workflow, "DAILY_QUOTA_CACHE_TTL_SECONDS", 15)
    monkeypatch.setattr(workflow, "get_daily_quota_status", lambda: daily_quota)
    monkeypatch.setattr(workflow, "get_daily_quota_status_refreshed_at", lambda: 100.0)
    monkeypatch.setattr(
        workflow,
        "get_app_user_record",
        lambda: type("AppUser", (), {"id": "user-123", "plan_tier": "free"})(),
    )
    monkeypatch.setattr(workflow, "get_auth_tokens", lambda: ("access-token", "refresh-token"))
    monkeypatch.setattr(workflow, "get_auth_service", lambda: object())
    monkeypatch.setattr(workflow, "UsageStore", FakeUsageStore)
    monkeypatch.setattr(workflow, "QuotaService", FakeQuotaService)

    result = workflow.refresh_daily_quota_status(now=110.0)

    assert result is daily_quota
    assert fetches["count"] == 0


def test_build_ai_session_view_model_uses_cached_quota_without_refresh(monkeypatch):
    daily_quota = type("DailyQuota", (), {"quota_exhausted": False, "plan_tier": "free"})()

    class FakeUsageStore:
        def __init__(self, auth_service):
            self.auth_service = auth_service

        def is_configured(self):
            return True

    monkeypatch.setattr(workflow, "get_openai_session_usage", lambda *args, **kwargs: {
        "request_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "max_calls": 24,
        "max_total_tokens": 120000,
        "remaining_calls": 24,
        "remaining_total_tokens": 120000,
        "last_response_metadata": {},
    })
    monkeypatch.setattr(workflow, "get_daily_quota_status", lambda: daily_quota)
    monkeypatch.setattr(
        workflow,
        "get_app_user_record",
        lambda: type("AppUser", (), {"id": "user-123", "plan_tier": "free"})(),
    )
    monkeypatch.setattr(workflow, "get_auth_tokens", lambda: ("access-token", "refresh-token"))
    monkeypatch.setattr(workflow, "get_auth_service", lambda: object())
    monkeypatch.setattr(workflow, "UsageStore", FakeUsageStore)
    monkeypatch.setattr(
        workflow,
        "refresh_daily_quota_status",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("quota refresh should not run")),
    )

    view_model = workflow.build_ai_session_view_model()

    assert view_model.daily_quota is daily_quota


def test_build_ai_session_view_model_accepts_injected_auth_service(monkeypatch):
    injected_auth_service = object()

    class FakeUsageStore:
        def __init__(self, auth_service):
            self.auth_service = auth_service

        def is_configured(self):
            return False

    monkeypatch.setattr(workflow, "get_openai_session_usage", lambda *args, **kwargs: {
        "request_count": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "max_calls": 24,
        "max_total_tokens": 120000,
        "remaining_calls": 24,
        "remaining_total_tokens": 120000,
        "last_response_metadata": {},
    })
    monkeypatch.setattr(workflow, "get_daily_quota_status", lambda: None)
    monkeypatch.setattr(
        workflow,
        "get_app_user_record",
        lambda: type("AppUser", (), {"id": "user-123", "plan_tier": "free"})(),
    )
    monkeypatch.setattr(workflow, "get_auth_tokens", lambda: ("access-token", "refresh-token"))
    monkeypatch.setattr(
        workflow,
        "get_auth_service",
        lambda: (_ for _ in ()).throw(AssertionError("get_auth_service should not run")),
    )
    monkeypatch.setattr(workflow, "UsageStore", FakeUsageStore)
    monkeypatch.setattr(workflow, "OpenAIService", lambda **kwargs: type("FakeOpenAIService", (), {"is_available": lambda self: False})())
    monkeypatch.setattr(workflow, "refresh_daily_quota_status", lambda *args, **kwargs: None)

    view_model = workflow.build_ai_session_view_model(auth_service=injected_auth_service)

    assert view_model.daily_quota is None


def test_restore_latest_saved_workspace_restores_snapshot(monkeypatch):
    captured = {}
    snapshot = SimpleNamespace(
        candidate_profile=CandidateProfile(full_name="Leander Antony", resume_text="resume text"),
        job_description=JobDescription(
            title="ML Engineer",
            raw_text="raw jd",
            cleaned_text="cleaned jd",
            requirements=JobRequirements(hard_skills=["Python"]),
        ),
        fit_analysis=SimpleNamespace(),
        tailored_draft=SimpleNamespace(),
        agent_result=None,
    )

    class FakeSavedWorkspaceStore:
        def __init__(self, auth_service):
            self.auth_service = auth_service

        def is_configured(self):
            return True

        def load_workspace(self, access_token, refresh_token, user_id):
            return (
                SimpleNamespace(
                    workflow_snapshot_json="snapshot",
                    tailored_resume_payload_json="resume",
                    expires_at="2026-03-16T00:00:00+00:00",
                ),
                "available",
            )

    monkeypatch.setattr(workflow, "get_app_user_record", lambda: SimpleNamespace(id="user-123"))
    monkeypatch.setattr(workflow, "get_auth_tokens", lambda: ("access-token", "refresh-token"))
    monkeypatch.setattr(workflow, "get_auth_service", lambda: object())
    monkeypatch.setattr(workflow, "SavedWorkspaceStore", FakeSavedWorkspaceStore)
    monkeypatch.setattr(workflow, "build_saved_workflow_snapshot_from_payload", lambda raw: snapshot)
    monkeypatch.setattr(workflow, "build_saved_tailored_resume_from_payload", lambda raw: SimpleNamespace(theme="modern_professional"))
    monkeypatch.setattr(workflow, "store_resume_intake", lambda document, profile: captured.update({"resume_intake": (document, profile)}))
    monkeypatch.setattr(workflow, "set_active_candidate_profile", lambda value: captured.update({"candidate_profile": value}))
    monkeypatch.setattr(workflow, "store_job_description_inputs", lambda raw_text, source_label, job_description: captured.update({"job_description": (raw_text, source_label, job_description)}))
    monkeypatch.setattr(workflow, "store_fit_outputs", lambda fit_analysis, tailored_draft: captured.update({"fit_outputs": (fit_analysis, tailored_draft)}))
    monkeypatch.setattr(workflow, "reset_agent_workflow_if_signature_changed", lambda value: captured.update({"workflow_signature": value}))
    monkeypatch.setattr(workflow, "_workflow_signature", lambda *args: "restored-signature")
    monkeypatch.setattr(workflow, "set_agent_workflow_result", lambda value: captured.update({"agent_result": value}))
    monkeypatch.setattr(workflow, "set_tailored_resume_theme", lambda value: captured.update({"theme": value}))
    monkeypatch.setattr(workflow, "request_menu_navigation", lambda menu_name: captured.update({"menu": menu_name}))
    monkeypatch.setattr(workflow, "set_workspace_restore_notice", lambda value: captured.update({"notice": value}))

    result = workflow.restore_latest_saved_workspace()

    assert captured["resume_intake"][0].filetype == "Saved Workspace"
    assert captured["resume_intake"][0].text == "resume text"
    assert captured["resume_intake"][1].full_name == "Leander Antony"
    assert captured["candidate_profile"].full_name == "Leander Antony"
    assert captured["job_description"][0] == "raw jd"
    assert captured["job_description"][1] == "Reloaded saved workspace"
    assert captured["workflow_signature"] == "restored-signature"
    assert captured["theme"] == "modern_professional"
    assert captured["menu"] == "Manual JD Input"
    assert result["level"] == "success"


def test_load_saved_workspace_summary_builds_saved_artifacts(monkeypatch):
    class FakeSavedWorkspaceStore:
        def __init__(self, auth_service):
            self.auth_service = auth_service

        def is_configured(self):
            return True

        def load_workspace(self, access_token, refresh_token, user_id):
            return (
                SimpleNamespace(
                    report_payload_json="report-payload",
                    tailored_resume_payload_json="resume-payload",
                    workflow_snapshot_json="snapshot-payload",
                ),
                "available",
            )

    monkeypatch.setattr(workflow, "get_app_user_record", lambda: SimpleNamespace(id="user-123"))
    monkeypatch.setattr(workflow, "get_auth_tokens", lambda: ("access-token", "refresh-token"))
    monkeypatch.setattr(workflow, "get_auth_service", lambda: object())
    monkeypatch.setattr(workflow, "SavedWorkspaceStore", FakeSavedWorkspaceStore)
    monkeypatch.setattr(workflow, "build_saved_report_from_payload", lambda raw: {"kind": "report", "raw": raw})
    monkeypatch.setattr(workflow, "build_saved_tailored_resume_from_payload", lambda raw: {"kind": "resume", "raw": raw})
    monkeypatch.setattr(workflow, "build_saved_workflow_snapshot_from_payload", lambda raw: {"kind": "snapshot", "raw": raw})

    summary = workflow.load_saved_workspace_summary()

    assert summary["status"] == "available"
    assert summary["report"] == {"kind": "report", "raw": "report-payload"}
    assert summary["resume"] == {"kind": "resume", "raw": "resume-payload"}
    assert summary["snapshot"] == {"kind": "snapshot", "raw": "snapshot-payload"}


def test_restore_latest_saved_workspace_reports_expired_snapshot(monkeypatch):
    captured = {}

    class FakeSavedWorkspaceStore:
        def __init__(self, auth_service):
            self.auth_service = auth_service

        def is_configured(self):
            return True

        def load_workspace(self, access_token, refresh_token, user_id):
            return None, "expired"

    monkeypatch.setattr(workflow, "get_app_user_record", lambda: SimpleNamespace(id="user-123"))
    monkeypatch.setattr(workflow, "get_auth_tokens", lambda: ("access-token", "refresh-token"))
    monkeypatch.setattr(workflow, "get_auth_service", lambda: object())
    monkeypatch.setattr(workflow, "SavedWorkspaceStore", FakeSavedWorkspaceStore)
    monkeypatch.setattr(workflow, "set_workspace_restore_notice", lambda value: captured.update({"notice": value}))

    result = workflow.restore_latest_saved_workspace()

    assert result["level"] == "warning"
    assert "expired" in result["message"].lower()