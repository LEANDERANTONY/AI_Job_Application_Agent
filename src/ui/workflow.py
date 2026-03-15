import time
from dataclasses import dataclass
from typing import Optional

from src.agents.orchestrator import ApplicationOrchestrator
from src.config import (
    AUTH_REQUIRED_FOR_ASSISTED_WORKFLOW,
    DAILY_QUOTA_CACHE_TTL_SECONDS,
    OPENAI_MAX_CALLS_PER_SESSION,
    OPENAI_MAX_TOKENS_PER_SESSION,
)
from src.errors import AgentExecutionError, AppError, InputValidationError
from src.openai_service import OpenAIService
from src.quota_service import QuotaService
from src.report_builder import build_application_report
from src.resume_builder import build_tailored_resume_artifact
from src.saved_workspace_store import SavedWorkspaceStore
from src.schemas import (
    AgentWorkflowResult,
    ApplicationReport,
    CandidateProfile,
    DailyQuotaStatus,
    FitAnalysis,
    JobDescription,
    ResumeDocument,
    TailoredResumeArtifact,
    TailoredResumeDraft,
)
from src.services.fit_service import build_fit_analysis
from src.services.job_service import build_job_description_from_text
from src.services.tailoring_service import build_tailored_resume_draft
from src.usage_store import UsageStore
from src.ui import workflow_exports, workflow_history, workflow_intake
from src.ui.auth import get_auth_service
from src.ui.state import (
    AGENT_WORKFLOW_RESULT,
    get_app_user_record,
    get_auth_tokens,
    get_daily_quota_status,
    get_daily_quota_status_refreshed_at,
    get_openai_session_usage,
    get_state,
    get_tailored_resume_theme,
    request_menu_navigation,
    reset_agent_workflow_if_signature_changed,
    set_active_candidate_profile,
    set_agent_workflow_result,
    set_daily_quota_status,
    set_daily_quota_status_refreshed_at,
    set_openai_session_usage,
    set_tailored_resume_theme,
    set_workspace_restore_notice,
    store_resume_intake,
    store_fit_outputs,
    store_job_description_inputs,
    sync_report_signature,
    sync_tailored_resume_signature,
)
from src.ui.state import is_authenticated
from src.ui.workflow_payloads import (
    WORKFLOW_HISTORY_PAYLOAD_KIND_REPORT,
    WORKFLOW_HISTORY_PAYLOAD_KIND_SNAPSHOT,
    WORKFLOW_HISTORY_PAYLOAD_KIND_TAILORED_RESUME,
    WORKFLOW_HISTORY_PAYLOAD_VERSION,
    build_saved_report_from_payload,
    build_saved_tailored_resume_from_payload,
    build_saved_workflow_snapshot_from_payload,
    get_saved_workflow_payload_status,
)
from src.ui.workflow_signatures import report_signature as _report_signature
from src.ui.workflow_signatures import workflow_signature as _workflow_signature


@dataclass
class AISessionViewModel:
    usage: dict
    mode_label: str
    budget_reached: bool
    openai_service: OpenAIService
    daily_quota: Optional[DailyQuotaStatus] = None


@dataclass
class JobWorkflowViewModel:
    jd_text: str
    jd_source: str
    job_description: Optional[JobDescription] = None
    candidate_profile: Optional[CandidateProfile] = None
    fit_analysis: Optional[FitAnalysis] = None
    tailored_draft: Optional[TailoredResumeDraft] = None
    tailored_resume_artifact: Optional[TailoredResumeArtifact] = None
    agent_result: Optional[AgentWorkflowResult] = None
    ai_session: Optional[AISessionViewModel] = None


def _load_sample_resume(filename):
    return workflow_intake._load_sample_resume(filename)


def _load_sample_jd(filename):
    return workflow_intake._load_sample_jd(filename)


def refresh_daily_quota_status(force=False, now=None):
    daily_quota = get_daily_quota_status()
    cached_at = get_daily_quota_status_refreshed_at()
    current_time = time.time() if now is None else now
    auth_user_record = get_app_user_record()
    access_token, refresh_token = get_auth_tokens()
    if auth_user_record is None or not access_token or not refresh_token:
        set_daily_quota_status(None)
        set_daily_quota_status_refreshed_at(None)
        return None

    if (
        not force
        and daily_quota is not None
        and cached_at is not None
        and (current_time - cached_at) < DAILY_QUOTA_CACHE_TTL_SECONDS
    ):
        return daily_quota

    auth_service = get_auth_service()
    usage_store = UsageStore(auth_service)
    if not usage_store.is_configured():
        return daily_quota

    quota_service = QuotaService(auth_service, usage_store)
    try:
        daily_quota = quota_service.get_daily_quota_status(
            access_token,
            refresh_token,
            auth_user_record.id,
            auth_user_record.plan_tier,
        )
    except AppError:
        return get_daily_quota_status()
    set_daily_quota_status(daily_quota)
    set_daily_quota_status_refreshed_at(current_time)
    return daily_quota


def get_resume_page_state():
    return workflow_intake.get_resume_page_state()


def use_sample_resume(filename):
    return workflow_intake.use_sample_resume(filename)


def use_uploaded_resume(uploaded_file):
    return workflow_intake.use_uploaded_resume(uploaded_file)


def get_active_candidate_profile():
    return workflow_intake.get_active_candidate_profile()


def resolve_job_description_input(uploaded_jd=None, selected_sample="None", pasted_text=""):
    return workflow_intake.resolve_job_description_input(
        uploaded_jd=uploaded_jd,
        selected_sample=selected_sample,
        pasted_text=pasted_text,
    )


def build_ai_session_view_model():
    usage = get_openai_session_usage(
        OPENAI_MAX_CALLS_PER_SESSION,
        OPENAI_MAX_TOKENS_PER_SESSION,
    )
    usage_event_recorder = None
    quota_checker = None
    daily_quota = get_daily_quota_status()
    auth_user_record = get_app_user_record()
    access_token, refresh_token = get_auth_tokens()
    if auth_user_record is not None and access_token and refresh_token:
        if daily_quota is None:
            daily_quota = refresh_daily_quota_status()
        auth_service = get_auth_service()
        usage_store = UsageStore(auth_service)
        if usage_store.is_configured():
            if daily_quota and daily_quota.quota_exhausted:

                def quota_checker():
                    raise AgentExecutionError(
                        "Your daily assisted usage limit has been reached. Try again tomorrow or upgrade your plan tier."
                    )

            else:

                def quota_checker():
                    refreshed_quota = refresh_daily_quota_status(force=True)
                    if refreshed_quota and refreshed_quota.quota_exhausted:
                        raise AgentExecutionError(
                            "Your daily assisted usage limit has been reached. Try again tomorrow or upgrade your plan tier."
                        )

            def usage_event_recorder(event_payload):
                usage_store.record_usage_event(
                    access_token,
                    refresh_token,
                    {
                        **event_payload,
                        "user_id": auth_user_record.id,
                    },
                )

    openai_service = OpenAIService(
        usage_budget={
            "max_calls": usage.get("max_calls"),
            "max_total_tokens": usage.get("max_total_tokens"),
        },
        starting_usage=usage,
        usage_event_recorder=usage_event_recorder,
        quota_checker=quota_checker,
    )
    budget_reached = (
        usage.get("remaining_calls") == 0
        or usage.get("remaining_total_tokens") == 0
    )
    mode_label = "AI-assisted" if openai_service.is_available() else "Fallback-ready"
    return AISessionViewModel(
        usage=usage,
        mode_label=mode_label,
        budget_reached=budget_reached,
        openai_service=openai_service,
        daily_quota=daily_quota,
    )


def build_job_workflow_view_model(jd_text, jd_source):
    view_model = JobWorkflowViewModel(jd_text=jd_text, jd_source=jd_source)
    if not jd_text:
        return view_model

    job_description = build_job_description_from_text(jd_text)
    store_job_description_inputs(jd_text, jd_source, job_description)
    candidate_profile = get_active_candidate_profile()

    view_model.job_description = job_description
    view_model.candidate_profile = candidate_profile
    if not candidate_profile:
        return view_model

    fit_analysis = build_fit_analysis(candidate_profile, job_description)
    tailored_draft = build_tailored_resume_draft(
        candidate_profile,
        job_description,
        fit_analysis,
    )
    store_fit_outputs(fit_analysis, tailored_draft)
    reset_agent_workflow_if_signature_changed(
        _workflow_signature(candidate_profile, job_description, fit_analysis, tailored_draft)
    )

    view_model.fit_analysis = fit_analysis
    view_model.tailored_draft = tailored_draft
    view_model.agent_result = get_state(AGENT_WORKFLOW_RESULT)
    view_model.tailored_resume_artifact = build_tailored_resume_artifact(
        candidate_profile,
        job_description,
        fit_analysis,
        tailored_draft,
        agent_result=view_model.agent_result,
        theme=get_tailored_resume_theme(),
    )
    view_model.ai_session = build_ai_session_view_model()
    return view_model


def _persist_workflow_run(view_model: JobWorkflowViewModel):
    return workflow_history.persist_workflow_run(view_model)


def refresh_authenticated_history(selected_workflow_run_id: Optional[str] = None):
    return workflow_history.refresh_authenticated_history(selected_workflow_run_id)


def load_saved_workspace_summary():
    auth_user_record = get_app_user_record()
    access_token, refresh_token = get_auth_tokens()
    if auth_user_record is None or not access_token or not refresh_token:
        return {"status": "unauthenticated", "record": None, "report": None, "resume": None}

    saved_workspace_store = SavedWorkspaceStore(get_auth_service())
    if not saved_workspace_store.is_configured():
        return {"status": "unconfigured", "record": None, "report": None, "resume": None}

    saved_workspace, status = saved_workspace_store.load_workspace(
        access_token,
        refresh_token,
        auth_user_record.id,
    )
    if saved_workspace is None:
        return {"status": status, "record": None, "report": None, "resume": None}

    return {
        "status": status,
        "record": saved_workspace,
        "report": build_saved_report_from_payload(saved_workspace.report_payload_json),
        "resume": build_saved_tailored_resume_from_payload(saved_workspace.tailored_resume_payload_json),
        "snapshot": build_saved_workflow_snapshot_from_payload(saved_workspace.workflow_snapshot_json),
    }


def restore_latest_saved_workspace():
    auth_user_record = get_app_user_record()
    access_token, refresh_token = get_auth_tokens()
    if auth_user_record is None or not access_token or not refresh_token:
        result = {
            "level": "warning",
            "message": "Sign in with Google before reloading a saved workspace.",
        }
        set_workspace_restore_notice(result)
        return result

    saved_workspace_store = SavedWorkspaceStore(get_auth_service())
    if not saved_workspace_store.is_configured():
        result = {
            "level": "warning",
            "message": "Saved workspace reload is not configured.",
        }
        set_workspace_restore_notice(result)
        return result

    saved_workspace, status = saved_workspace_store.load_workspace(
        access_token,
        refresh_token,
        auth_user_record.id,
    )
    if status == "expired":
        result = {
            "level": "warning",
            "message": "Your saved workspace expired after 24 hours. Re-run the flow to save a fresh one.",
        }
        set_workspace_restore_notice(result)
        return result
    if saved_workspace is None:
        result = {
            "level": "info",
            "message": "No saved workspace is available to reload yet.",
        }
        set_workspace_restore_notice(result)
        return result

    saved_snapshot = build_saved_workflow_snapshot_from_payload(saved_workspace.workflow_snapshot_json)
    if saved_snapshot is None:
        result = {
            "level": "warning",
            "message": "The saved workspace could not be restored safely. Re-run the flow to create a fresh save.",
        }
        set_workspace_restore_notice(result)
        return result

    store_resume_intake(
        ResumeDocument(
            text=saved_snapshot.candidate_profile.resume_text or "",
            filetype="Saved Workspace",
            source="saved_workspace",
        ),
        saved_snapshot.candidate_profile,
    )
    set_active_candidate_profile(saved_snapshot.candidate_profile)
    store_job_description_inputs(
        saved_snapshot.job_description.raw_text or saved_snapshot.job_description.cleaned_text,
        "Reloaded saved workspace",
        saved_snapshot.job_description,
    )
    store_fit_outputs(saved_snapshot.fit_analysis, saved_snapshot.tailored_draft)
    reset_agent_workflow_if_signature_changed(
        _workflow_signature(
            saved_snapshot.candidate_profile,
            saved_snapshot.job_description,
            saved_snapshot.fit_analysis,
            saved_snapshot.tailored_draft,
        )
    )
    set_agent_workflow_result(saved_snapshot.agent_result)
    saved_resume = build_saved_tailored_resume_from_payload(saved_workspace.tailored_resume_payload_json)
    if saved_resume is not None and saved_resume.theme:
        set_tailored_resume_theme(saved_resume.theme)
    request_menu_navigation("Manual JD Input")
    result = {
        "level": "success",
        "message": "Reloaded your latest saved workspace. This save expires at {expires_at}.".format(
            expires_at=saved_workspace.expires_at.replace("T", " ").replace("+00:00", " UTC")
        ),
    }
    set_workspace_restore_notice(result)
    return result


def build_saved_report_from_workflow_run(workflow_run: Optional[object]):
    return workflow_history.build_saved_report_from_workflow_run(workflow_run)


def build_saved_tailored_resume_from_workflow_run(workflow_run: Optional[object]):
    return workflow_history.build_saved_tailored_resume_from_workflow_run(workflow_run)


def run_supervised_workflow(view_model: JobWorkflowViewModel):
    if AUTH_REQUIRED_FOR_ASSISTED_WORKFLOW and not is_authenticated():
        raise InputValidationError(
            "Sign in with Google before running the AI-assisted workflow."
        )
    if view_model.ai_session and view_model.ai_session.daily_quota and view_model.ai_session.daily_quota.quota_exhausted:
        raise InputValidationError(
            "Your daily assisted usage limit has been reached. Try again tomorrow or upgrade your plan tier."
        )

    orchestrator = ApplicationOrchestrator(openai_service=view_model.ai_session.openai_service)
    try:
        agent_result = orchestrator.run(
            view_model.candidate_profile,
            view_model.job_description,
            view_model.fit_analysis,
            view_model.tailored_draft,
        )
        set_agent_workflow_result(agent_result)
    finally:
        set_openai_session_usage(view_model.ai_session.openai_service.get_usage_snapshot())

    refreshed_view_model = build_job_workflow_view_model(view_model.jd_text, view_model.jd_source)
    refreshed_view_model.agent_result = get_state(AGENT_WORKFLOW_RESULT)
    _persist_workflow_run(refreshed_view_model)
    return refreshed_view_model


def build_application_report_view_model(view_model: JobWorkflowViewModel):
    if not (
        view_model.candidate_profile
        and view_model.job_description
        and view_model.fit_analysis
        and view_model.tailored_draft
    ):
        return None
    report = build_application_report(
        view_model.candidate_profile,
        view_model.job_description,
        view_model.fit_analysis,
        view_model.tailored_draft,
        agent_result=view_model.agent_result,
    )
    sync_report_signature(_report_signature(report))
    return report


def build_tailored_resume_artifact_view_model(view_model: JobWorkflowViewModel):
    if not (
        view_model.candidate_profile
        and view_model.job_description
        and view_model.fit_analysis
        and view_model.tailored_draft
    ):
        return None
    artifact = build_tailored_resume_artifact(
        view_model.candidate_profile,
        view_model.job_description,
        view_model.fit_analysis,
        view_model.tailored_draft,
        agent_result=view_model.agent_result,
        theme=get_tailored_resume_theme(),
    )
    sync_tailored_resume_signature(_report_signature(artifact))
    return artifact


def prepare_pdf_package(report: ApplicationReport):
    return workflow_exports.prepare_pdf_package(report)


def get_cached_pdf_package():
    return workflow_exports.get_cached_pdf_package()


def prepare_tailored_resume_pdf_package(artifact: TailoredResumeArtifact):
    return workflow_exports.prepare_tailored_resume_pdf_package(artifact)


def get_cached_tailored_resume_pdf_package():
    return workflow_exports.get_cached_tailored_resume_pdf_package()


def prepare_export_bundle_package(
    report: ApplicationReport,
    artifact: TailoredResumeArtifact,
):
    return workflow_exports.prepare_export_bundle_package(report, artifact)


def get_cached_export_bundle_package():
    return workflow_exports.get_cached_export_bundle_package()