import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Optional

from src.agents.orchestrator import ApplicationOrchestrator
from src.config import (
    DEMO_JOB_DESCRIPTION_DIR,
    DEMO_RESUME_DIR,
    OPENAI_MAX_CALLS_PER_SESSION,
    OPENAI_MAX_TOKENS_PER_SESSION,
)
from src.exporters import export_pdf_bytes
from src.openai_service import OpenAIService
from src.parsers.jd import parse_jd_text
from src.parsers.resume import parse_resume_document
from src.report_builder import build_application_report
from src.schemas import (
    AgentWorkflowResult,
    ApplicationReport,
    CandidateProfile,
    FitAnalysis,
    JobDescription,
    TailoredResumeDraft,
)
from src.services.fit_service import build_fit_analysis
from src.services.job_service import build_job_description_from_text
from src.services.profile_service import build_candidate_profile_from_resume
from src.services.tailoring_service import build_tailored_resume_draft
from src.ui.state import (
    AGENT_WORKFLOW_RESULT,
    CANDIDATE_PROFILE_RESUME,
    JOB_DESCRIPTION_RAW,
    JOB_DESCRIPTION_SOURCE,
    RESUME_DOCUMENT,
    get_cached_pdf_bytes,
    get_openai_session_usage,
    get_state,
    reset_agent_workflow_if_signature_changed,
    set_active_candidate_profile,
    set_agent_workflow_result,
    set_cached_pdf_bytes,
    set_openai_session_usage,
    store_fit_outputs,
    store_job_description_inputs,
    store_resume_intake,
    sync_report_signature,
)


@dataclass
class AISessionViewModel:
    usage: dict
    mode_label: str
    budget_reached: bool
    openai_service: OpenAIService


@dataclass
class JobWorkflowViewModel:
    jd_text: str
    jd_source: str
    job_description: Optional[JobDescription] = None
    candidate_profile: Optional[CandidateProfile] = None
    fit_analysis: Optional[FitAnalysis] = None
    tailored_draft: Optional[TailoredResumeDraft] = None
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
    openai_service = OpenAIService(
        usage_budget={
            "max_calls": usage.get("max_calls"),
            "max_total_tokens": usage.get("max_total_tokens"),
        },
        starting_usage=usage,
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
    view_model.ai_session = build_ai_session_view_model()
    return view_model


def run_supervised_workflow(view_model: JobWorkflowViewModel):
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


def prepare_pdf_package(report: ApplicationReport):
    pdf_bytes = export_pdf_bytes(report)
    set_cached_pdf_bytes(pdf_bytes)
    return pdf_bytes


def get_cached_pdf_package():
    return get_cached_pdf_bytes()