import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Optional

from src.agents.orchestrator import ApplicationOrchestrator
from src.config import (
    AUTH_REQUIRED_FOR_ASSISTED_WORKFLOW,
    DEMO_JOB_DESCRIPTION_DIR,
    DEMO_RESUME_DIR,
    OPENAI_MAX_CALLS_PER_SESSION,
    OPENAI_MAX_TOKENS_PER_SESSION,
)
from src.errors import AgentExecutionError, AppError, InputValidationError
from src.exporters import export_markdown_bytes, export_pdf_bytes, export_zip_bundle_bytes
from src.openai_service import OpenAIService
from src.parsers.jd import parse_jd_text
from src.parsers.resume import parse_resume_document
from src.report_builder import build_application_report
from src.resume_builder import build_tailored_resume_artifact
from src.auth_service import AuthService
from src.history_store import HistoryStore
from src.quota_service import QuotaService
from src.schemas import (
    AgentWorkflowResult,
    DailyQuotaStatus,
    ApplicationReport,
    CandidateProfile,
    FitAnalysis,
    JobDescription,
    TailoredResumeArtifact,
    TailoredResumeDraft,
)
from src.services.fit_service import build_fit_analysis
from src.services.job_service import build_job_description_from_text
from src.services.profile_service import build_candidate_profile_from_resume
from src.services.tailoring_service import build_tailored_resume_draft
from src.usage_store import UsageStore
from src.ui.state import (
    AGENT_WORKFLOW_RESULT,
    CANDIDATE_PROFILE_RESUME,
    JOB_DESCRIPTION_RAW,
    JOB_DESCRIPTION_SOURCE,
    RESUME_DOCUMENT,
    get_app_user_record,
    get_artifact_history,
    get_auth_tokens,
    get_active_workflow_run,
    get_cached_pdf_bytes,
    get_cached_export_bundle_bytes,
    get_cached_tailored_resume_pdf_bytes,
    get_daily_quota_status,
    get_openai_session_usage,
    get_selected_history_workflow_run_id,
    get_state,
    get_tailored_resume_theme,
    reset_agent_workflow_if_signature_changed,
    set_active_candidate_profile,
    set_active_workflow_run,
    set_agent_workflow_result,
    set_artifact_history,
    set_cached_pdf_bytes,
    set_cached_export_bundle_bytes,
    set_cached_tailored_resume_pdf_bytes,
    set_daily_quota_status,
    set_selected_history_workflow_run_id,
    set_openai_session_usage,
    set_workflow_history,
    store_fit_outputs,
    store_job_description_inputs,
    store_resume_intake,
    sync_report_signature,
    sync_tailored_resume_signature,
)
from src.ui.state import is_authenticated


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
    with (DEMO_RESUME_DIR / filename).open("rb") as file_handle:
        return parse_resume_document(file_handle, source=f"sample:{filename}")


def _load_sample_jd(filename):
    with (DEMO_JOB_DESCRIPTION_DIR / filename).open("rb") as file_handle:
        return parse_jd_text(file_handle)


def _workflow_signature(candidate_profile, job_description, fit_analysis, tailored_draft):
    payload = {
        "candidate_profile": asdict(candidate_profile),
        "job_description": asdict(job_description),
        "fit_analysis": asdict(fit_analysis),
        "tailored_draft": asdict(tailored_draft),
    }
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _report_signature(report):
    raw = json.dumps(
        {
            "title": report.title,
            "summary": report.summary,
            "markdown": report.markdown,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _json_payload(value):
    return json.dumps(asdict(value), sort_keys=True, default=str)


def _workflow_snapshot_json(view_model: "JobWorkflowViewModel"):
    payload = {
        "candidate_profile": asdict(view_model.candidate_profile),
        "job_description": asdict(view_model.job_description),
        "fit_analysis": asdict(view_model.fit_analysis),
        "tailored_draft": asdict(view_model.tailored_draft),
        "agent_result": asdict(view_model.agent_result) if view_model.agent_result else None,
    }
    return json.dumps(payload, sort_keys=True, default=str)


def get_resume_page_state():
    return get_state(RESUME_DOCUMENT), get_state(CANDIDATE_PROFILE_RESUME)


def use_sample_resume(filename):
    resume_document = _load_sample_resume(filename)
    candidate_profile_resume = build_candidate_profile_from_resume(resume_document)
    store_resume_intake(resume_document, candidate_profile_resume)
    return resume_document, candidate_profile_resume


def use_uploaded_resume(uploaded_file):
    resume_document = parse_resume_document(uploaded_file)
    candidate_profile_resume = build_candidate_profile_from_resume(resume_document)
    store_resume_intake(resume_document, candidate_profile_resume)
    return resume_document, candidate_profile_resume


def get_active_candidate_profile():
    candidate_profile = get_state(CANDIDATE_PROFILE_RESUME)
    if candidate_profile:
        set_active_candidate_profile(candidate_profile)
    return candidate_profile


def resolve_job_description_input(uploaded_jd=None, selected_sample="None", pasted_text=""):
    jd_text = get_state(JOB_DESCRIPTION_RAW, "")
    jd_source = get_state(JOB_DESCRIPTION_SOURCE, "Session cache")

    if uploaded_jd is not None:
        jd_text = parse_jd_text(uploaded_jd)
        jd_source = "Uploaded file"
    elif selected_sample != "None":
        jd_text = _load_sample_jd(selected_sample)
        jd_source = f"Sample file: {selected_sample}"

    if pasted_text.strip():
        jd_text = pasted_text
        jd_source = "Pasted text"

    return jd_text, jd_source


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
        auth_service = AuthService()
        usage_store = UsageStore(auth_service)
        if usage_store.is_configured():
            quota_service = QuotaService(auth_service, usage_store)
            try:
                daily_quota = quota_service.get_daily_quota_status(
                    access_token,
                    refresh_token,
                    auth_user_record.id,
                    auth_user_record.plan_tier,
                )
                set_daily_quota_status(daily_quota)
                if daily_quota.quota_exhausted:
                    def quota_checker():
                        raise AgentExecutionError(
                            "Your daily assisted usage limit has been reached. Try again tomorrow or upgrade your plan tier."
                        )
                else:
                    def quota_checker():
                        refreshed_quota = quota_service.get_daily_quota_status(
                            access_token,
                            refresh_token,
                            auth_user_record.id,
                            auth_user_record.plan_tier,
                        )
                        set_daily_quota_status(refreshed_quota)
                        if refreshed_quota.quota_exhausted:
                            raise AgentExecutionError(
                                "Your daily assisted usage limit has been reached. Try again tomorrow or upgrade your plan tier."
                            )
            except AppError:
                daily_quota = get_daily_quota_status()
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
    selected_theme = get_tailored_resume_theme()
    view_model.tailored_resume_artifact = build_tailored_resume_artifact(
        candidate_profile,
        job_description,
        fit_analysis,
        tailored_draft,
        agent_result=view_model.agent_result,
        theme=selected_theme,
    )
    view_model.ai_session = build_ai_session_view_model()
    return view_model


def _persist_workflow_run(view_model: JobWorkflowViewModel):
    auth_user_record = get_app_user_record()
    access_token, refresh_token = get_auth_tokens()
    if auth_user_record is None or not access_token or not refresh_token:
        return None

    history_store = HistoryStore(AuthService())
    if not history_store.is_configured():
        return None

    report = build_application_report(
        view_model.candidate_profile,
        view_model.job_description,
        view_model.fit_analysis,
        view_model.tailored_draft,
        agent_result=view_model.agent_result,
    )
    tailored_resume_artifact = build_tailored_resume_artifact(
        view_model.candidate_profile,
        view_model.job_description,
        view_model.fit_analysis,
        view_model.tailored_draft,
        agent_result=view_model.agent_result,
        theme=get_tailored_resume_theme(),
    )

    workflow_run = history_store.create_workflow_run(
        access_token,
        refresh_token,
        {
            "user_id": auth_user_record.id,
            "job_title": view_model.job_description.title if view_model.job_description else "",
            "fit_score": view_model.fit_analysis.overall_score if view_model.fit_analysis else 0,
            "review_approved": bool(view_model.agent_result and view_model.agent_result.review.approved),
            "model_policy": view_model.agent_result.model if view_model.agent_result else "",
            "workflow_signature": _workflow_signature(
                view_model.candidate_profile,
                view_model.job_description,
                view_model.fit_analysis,
                view_model.tailored_draft,
            ),
            "workflow_snapshot_json": _workflow_snapshot_json(view_model),
            "report_payload_json": _json_payload(report),
            "tailored_resume_payload_json": _json_payload(tailored_resume_artifact),
        },
    )
    set_selected_history_workflow_run_id(workflow_run.id)
    set_active_workflow_run(workflow_run)
    refresh_authenticated_history(str(workflow_run.id))
    return workflow_run


def _persist_artifact_record(artifact_type: str, filename_stem: str, storage_path: str = ""):
    active_workflow_run = get_active_workflow_run()
    access_token, refresh_token = get_auth_tokens()
    if active_workflow_run is None or not access_token or not refresh_token:
        return get_artifact_history()

    history_store = HistoryStore(AuthService())
    if not history_store.is_configured():
        return get_artifact_history()

    history_store.create_artifact_record(
        access_token,
        refresh_token,
        {
            "workflow_run_id": active_workflow_run.id,
            "artifact_type": artifact_type,
            "filename_stem": filename_stem,
            "storage_path": storage_path,
        },
    )
    artifacts = history_store.list_recent_artifacts(
        access_token,
        refresh_token,
        active_workflow_run.id,
    )
    set_artifact_history(artifacts)
    return artifacts


def refresh_authenticated_history(selected_workflow_run_id: Optional[str] = None):
    auth_user_record = get_app_user_record()
    access_token, refresh_token = get_auth_tokens()
    if auth_user_record is None or not access_token or not refresh_token:
        set_workflow_history([])
        set_artifact_history([])
        set_selected_history_workflow_run_id(None)
        return [], []

    history_store = HistoryStore(AuthService())
    if not history_store.is_configured():
        return [], []

    workflow_runs = history_store.list_recent_workflow_runs(
        access_token,
        refresh_token,
        auth_user_record.id,
        limit=10,
    )
    set_workflow_history(workflow_runs)

    selected_id = str(
        selected_workflow_run_id
        or get_selected_history_workflow_run_id()
        or getattr(get_active_workflow_run(), "id", "")
        or ""
    )
    selected_workflow_run = None
    if selected_id:
        selected_workflow_run = next(
            (workflow_run for workflow_run in workflow_runs if str(workflow_run.id) == selected_id),
            None,
        )
    if selected_workflow_run is None and workflow_runs:
        selected_workflow_run = workflow_runs[0]

    if selected_workflow_run is None:
        set_selected_history_workflow_run_id(None)
        set_artifact_history([])
        return workflow_runs, []

    set_selected_history_workflow_run_id(selected_workflow_run.id)
    artifacts = history_store.list_recent_artifacts(
        access_token,
        refresh_token,
        str(selected_workflow_run.id),
        limit=20,
    )
    set_artifact_history(artifacts)
    return workflow_runs, artifacts


def build_saved_report_from_workflow_run(workflow_run: Optional[object]):
    if workflow_run is None or not getattr(workflow_run, "report_payload_json", ""):
        return None
    payload = json.loads(workflow_run.report_payload_json)
    return ApplicationReport(
        title=str(payload.get("title", "Saved Application Report") or "Saved Application Report"),
        filename_stem=str(payload.get("filename_stem", "saved-application-report") or "saved-application-report"),
        summary=str(payload.get("summary", "") or ""),
        markdown=str(payload.get("markdown", "") or ""),
        plain_text=str(payload.get("plain_text", "") or ""),
    )


def build_saved_tailored_resume_from_workflow_run(workflow_run: Optional[object]):
    if workflow_run is None or not getattr(workflow_run, "tailored_resume_payload_json", ""):
        return None
    payload = json.loads(workflow_run.tailored_resume_payload_json)
    return TailoredResumeArtifact(
        title=str(payload.get("title", "Saved Tailored Resume") or "Saved Tailored Resume"),
        filename_stem=str(payload.get("filename_stem", "saved-tailored-resume") or "saved-tailored-resume"),
        summary=str(payload.get("summary", "") or ""),
        markdown=str(payload.get("markdown", "") or ""),
        plain_text=str(payload.get("plain_text", "") or ""),
        theme=str(payload.get("theme", "classic_ats") or "classic_ats"),
    )


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
    pdf_bytes = export_pdf_bytes(report)
    set_cached_pdf_bytes(pdf_bytes)
    _persist_artifact_record(
        "application_report_pdf",
        report.filename_stem,
        report.filename_stem + ".pdf",
    )
    return pdf_bytes


def get_cached_pdf_package():
    return get_cached_pdf_bytes()


def prepare_tailored_resume_pdf_package(artifact: TailoredResumeArtifact):
    pdf_bytes = export_pdf_bytes(artifact)
    set_cached_tailored_resume_pdf_bytes(pdf_bytes)
    _persist_artifact_record(
        "tailored_resume_pdf",
        artifact.filename_stem,
        artifact.filename_stem + ".pdf",
    )
    return pdf_bytes


def get_cached_tailored_resume_pdf_package():
    return get_cached_tailored_resume_pdf_bytes()


def prepare_export_bundle_package(
    report: ApplicationReport,
    artifact: TailoredResumeArtifact,
):
    report_pdf_bytes = export_pdf_bytes(report)
    tailored_resume_pdf_bytes = export_pdf_bytes(artifact)
    set_cached_pdf_bytes(report_pdf_bytes)
    set_cached_tailored_resume_pdf_bytes(tailored_resume_pdf_bytes)

    bundle_bytes = export_zip_bundle_bytes(
        {
            report.filename_stem + ".md": export_markdown_bytes(report),
            report.filename_stem + ".pdf": report_pdf_bytes,
            artifact.filename_stem + ".md": export_markdown_bytes(artifact),
            artifact.filename_stem + ".pdf": tailored_resume_pdf_bytes,
        }
    )
    set_cached_export_bundle_bytes(bundle_bytes)
    bundle_stem = artifact.filename_stem.replace("-tailored-resume", "-application-bundle")
    _persist_artifact_record(
        "application_bundle_zip",
        bundle_stem,
        bundle_stem + ".zip",
    )
    return bundle_bytes


def get_cached_export_bundle_package():
    return get_cached_export_bundle_bytes()