from __future__ import annotations

import base64
from dataclasses import asdict, is_dataclass
from io import BytesIO
from types import SimpleNamespace
from typing import Any

from src.agents.orchestrator import ApplicationOrchestrator
from src.assistant_service import AssistantService
from src.cover_letter_builder import build_cover_letter_artifact
from src.config import assisted_workflow_requires_login
from src.errors import InputValidationError
from src.openai_service import OpenAIService
from src.parsers.jd import parse_jd_text
from src.parsers.resume import parse_resume_document
from src.report_builder import build_application_report
from src.resume_builder import build_tailored_resume_artifact
from src.schemas import AssistantResponse, ResumeDocument
from src.services.fit_service import build_fit_analysis
from src.services.jd_summary_service import generate_job_summary_view
from src.services.job_service import build_job_description_from_text
from src.services.profile_service import build_candidate_profile_from_resume
from src.services.tailoring_service import build_tailored_resume_draft
from backend.services.auth_session_service import (
    build_openai_service_for_context,
    resolve_authenticated_context,
)


class _InMemoryUploadedFile(BytesIO):
    def __init__(self, *, file_bytes: bytes, filename: str, mime_type: str):
        super().__init__(file_bytes)
        self.name = filename
        self.type = mime_type


def _decode_base64_content(content_base64: str) -> bytes:
    try:
        return base64.b64decode(str(content_base64 or "").encode("utf-8"), validate=True)
    except Exception as exc:
        raise InputValidationError("The uploaded file could not be decoded safely.") from exc


def _namespace_value(value: Any):
    if isinstance(value, dict):
        return SimpleNamespace(**{key: _namespace_value(item) for key, item in value.items()})
    if isinstance(value, list):
        return [_namespace_value(item) for item in value]
    return value


def _serialize(value: Any):
    if is_dataclass(value):
        return {key: _serialize(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


def _build_resume_document(*, resume_text: str, resume_filetype: str, resume_source: str):
    normalized_text = str(resume_text or "").strip()
    if not normalized_text:
        raise InputValidationError("Add a resume before running workspace analysis.")
    return ResumeDocument(
        text=normalized_text,
        filetype=str(resume_filetype or "TXT").strip() or "TXT",
        source=str(resume_source or "workspace").strip() or "workspace",
    )


def _enrich_job_description_from_imported_posting(job_description, imported_job_posting: dict[str, Any] | None):
    if not imported_job_posting:
        return job_description

    imported_title = str(imported_job_posting.get("title", "") or "").strip()
    imported_location = str(imported_job_posting.get("location", "") or "").strip()

    if imported_title:
        job_description.title = imported_title

    if imported_location:
        job_description.location = imported_location

    return job_description


def parse_resume_upload(*, filename: str, mime_type: str, content_base64: str):
    uploaded_file = _InMemoryUploadedFile(
        file_bytes=_decode_base64_content(content_base64),
        filename=filename,
        mime_type=mime_type,
    )
    resume_document = parse_resume_document(uploaded_file, source=f"workspace:{filename}")
    candidate_profile = build_candidate_profile_from_resume(resume_document)
    return {
        "resume_document": _serialize(resume_document),
        "candidate_profile": _serialize(candidate_profile),
    }


def parse_job_description_upload(*, filename: str, mime_type: str, content_base64: str):
    uploaded_file = _InMemoryUploadedFile(
        file_bytes=_decode_base64_content(content_base64),
        filename=filename,
        mime_type=mime_type,
    )
    job_description_text = parse_jd_text(uploaded_file)
    job_description = build_job_description_from_text(job_description_text)
    jd_summary_view = generate_job_summary_view(
        openai_service=OpenAIService(),
        job_description=job_description,
        imported_job_posting=None,
    )
    return {
        "job_description_text": job_description_text,
        "job_description": _serialize(job_description),
        "jd_summary_view": _serialize(jd_summary_view),
    }


def run_workspace_analysis(
    *,
    resume_text: str,
    resume_filetype: str,
    resume_source: str,
    job_description_text: str,
    imported_job_posting: dict[str, Any] | None,
    run_assisted: bool,
    access_token: str = "",
    refresh_token: str = "",
):
    resume_document = _build_resume_document(
        resume_text=resume_text,
        resume_filetype=resume_filetype,
        resume_source=resume_source,
    )
    candidate_profile = build_candidate_profile_from_resume(resume_document)
    job_description = _enrich_job_description_from_imported_posting(
        build_job_description_from_text(job_description_text),
        imported_job_posting,
    )
    fit_analysis = build_fit_analysis(candidate_profile, job_description)
    tailored_draft = build_tailored_resume_draft(
        candidate_profile,
        job_description,
        fit_analysis,
    )

    auth_context = None
    if access_token and refresh_token:
        auth_context = resolve_authenticated_context(
            access_token=access_token,
            refresh_token=refresh_token,
        )

    openai_service = None
    if auth_context is not None:
        openai_service, _ = build_openai_service_for_context(auth_context)

    jd_summary_view = generate_job_summary_view(
        openai_service=openai_service,
        job_description=job_description,
        imported_job_posting=imported_job_posting,
    )

    agent_result = None
    workflow_mode = "deterministic_preview"
    fallback_reason = ""

    if run_assisted:
        if auth_context is None and assisted_workflow_requires_login():
            raise InputValidationError(
                "Sign in with Google before running the AI-assisted workflow."
            )
        if openai_service is None:
            openai_service = OpenAIService()
        agent_result = ApplicationOrchestrator(openai_service=openai_service).run(
            candidate_profile,
            job_description,
            fit_analysis=fit_analysis,
            tailored_draft=tailored_draft,
        )
        workflow_mode = agent_result.mode
        fallback_reason = agent_result.fallback_reason

    tailored_resume_artifact = build_tailored_resume_artifact(
        candidate_profile,
        job_description,
        fit_analysis,
        tailored_draft,
        agent_result=agent_result,
    )
    cover_letter_artifact = build_cover_letter_artifact(
        candidate_profile,
        job_description,
        fit_analysis,
        tailored_draft,
        agent_result=agent_result,
    )
    report = build_application_report(
        candidate_profile,
        job_description,
        fit_analysis,
        tailored_draft,
        agent_result=agent_result,
    )

    review = getattr(agent_result, "review", None)

    return {
        "resume_document": _serialize(resume_document),
        "candidate_profile": _serialize(candidate_profile),
        "job_description": _serialize(job_description),
        "jd_summary_view": _serialize(jd_summary_view),
        "fit_analysis": _serialize(fit_analysis),
        "tailored_draft": _serialize(tailored_draft),
        "agent_result": _serialize(agent_result) if agent_result else None,
        "artifacts": {
            "tailored_resume": _serialize(tailored_resume_artifact),
            "cover_letter": _serialize(cover_letter_artifact),
            "report": _serialize(report),
        },
        "workflow": {
            "mode": workflow_mode,
            "assisted_requested": bool(run_assisted),
            "assisted_available": bool(openai_service and openai_service.is_available()),
            "review_approved": bool(review.approved) if review else False,
            "fallback_reason": fallback_reason,
        },
        "imported_job_posting": imported_job_posting,
    }


def answer_workspace_question(
    *,
    question: str,
    current_page: str,
    workspace_snapshot: dict[str, Any] | None,
    history: list[dict[str, str]] | None,
    access_token: str = "",
    refresh_token: str = "",
):
    workflow_view_model = None
    artifact = None
    report = None
    app_context = {
        "is_authenticated": False,
        "assistant_requires_login": False,
        "resume_upload_requires_login": False,
    }

    if workspace_snapshot:
        workflow_view_model = SimpleNamespace(
            candidate_profile=_namespace_value(workspace_snapshot.get("candidate_profile")),
            job_description=_namespace_value(workspace_snapshot.get("job_description")),
            fit_analysis=_namespace_value(workspace_snapshot.get("fit_analysis")),
            tailored_draft=_namespace_value(workspace_snapshot.get("tailored_draft")),
            agent_result=_namespace_value(workspace_snapshot.get("agent_result")),
        )
        artifacts = dict(workspace_snapshot.get("artifacts") or {})
        artifact = _namespace_value(artifacts.get("tailored_resume"))
        report = _namespace_value(artifacts.get("report"))
        app_context.update(
            {
                "has_resume": bool(workspace_snapshot.get("candidate_profile")),
                "has_job_description": bool(workspace_snapshot.get("job_description")),
                "has_tailored_resume": artifact is not None,
                "has_report": report is not None,
                "has_cover_letter": bool(artifacts.get("cover_letter")),
            }
        )

    compact_history = [
        SimpleNamespace(
            question=str(item.get("question", "") or "").strip(),
            response=SimpleNamespace(answer=str(item.get("answer", "") or "").strip()),
        )
        for item in list(history or [])
        if str(item.get("question", "") or "").strip()
        and str(item.get("answer", "") or "").strip()
    ]

    openai_service = None
    if access_token and refresh_token:
        auth_context = resolve_authenticated_context(
            access_token=access_token,
            refresh_token=refresh_token,
        )
        openai_service, _ = build_openai_service_for_context(auth_context)

    response: AssistantResponse = AssistantService(openai_service=openai_service).answer(
        question,
        current_page=current_page,
        workflow_view_model=workflow_view_model,
        report=report,
        artifact=artifact,
        history=compact_history,
        app_context=app_context,
    )
    return _serialize(response)
