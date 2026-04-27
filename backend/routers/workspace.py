from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.rate_limit import LIMIT_HEAVY, LIMIT_LLM, LIMIT_PARSE, limiter
from backend.request_auth import get_optional_auth_tokens
from backend.services.resume_builder_persistence_service import (
    clear_resume_builder_session,
    load_latest_resume_builder_session,
    persist_resume_builder_session,
)
from backend.services.workspace_persistence_service import (
    load_saved_workspace_snapshot,
    save_workspace_snapshot,
)
from backend.services.saved_jobs_service import (
    list_saved_jobs,
    remove_saved_job,
    save_saved_job,
)
from backend.services.artifact_export_service import export_workspace_artifact
from backend.services.artifact_export_service import preview_workspace_artifact
from backend.services.resume_builder_service import (
    answer_resume_builder_message,
    commit_resume_builder_session,
    generate_resume_builder_resume,
    start_resume_builder_session,
    update_resume_builder_session,
)
from backend.services.workspace_service import (
    answer_workspace_question,
    parse_job_description_upload,
    parse_resume_upload,
    run_workspace_analysis,
    stream_workspace_question,
)
from backend.services.workspace_run_jobs import (
    get_workspace_analysis_job,
    start_workspace_analysis_job,
)
from backend.workspace_models import (
    ResumeBuilderMessageRequestModel,
    ResumeBuilderSessionRequestModel,
    ResumeBuilderUpdateRequestModel,
    SavedJobRequestModel,
    UploadedFilePayloadModel,
    WorkspaceAnalyzeRequestModel,
    WorkspaceAssistantRequestModel,
    WorkspaceArtifactExportRequestModel,
    WorkspaceArtifactPreviewRequestModel,
    WorkspaceSaveRequestModel,
    WorkspaceAnalyzeJobCreatedResponseModel,
    WorkspaceAnalyzeJobStatusResponseModel,
)
from src.errors import AppError


router = APIRouter(prefix="/workspace", tags=["workspace"])


def _raise_http_error(error: AppError):
    raise HTTPException(status_code=400, detail=error.user_message)


@router.post("/resume/upload")
@limiter.limit(LIMIT_PARSE)
def upload_resume(request: Request, payload: UploadedFilePayloadModel):
    try:
        return parse_resume_upload(
            filename=payload.filename,
            mime_type=payload.mime_type,
            content_base64=payload.content_base64,
        )
    except AppError as error:
        _raise_http_error(error)


@router.post("/job-description/upload")
@limiter.limit(LIMIT_PARSE)
def upload_job_description(request: Request, payload: UploadedFilePayloadModel):
    try:
        return parse_job_description_upload(
            filename=payload.filename,
            mime_type=payload.mime_type,
            content_base64=payload.content_base64,
        )
    except AppError as error:
        _raise_http_error(error)


@router.post("/resume-builder/start")
@limiter.limit(LIMIT_LLM)
def start_resume_builder_route(request: Request, auth_tokens=Depends(get_optional_auth_tokens)):
    access_token, refresh_token = auth_tokens
    try:
        payload = start_resume_builder_session()
        persist_resume_builder_session(
            access_token=access_token or "",
            refresh_token=refresh_token or "",
            session_id=payload["session_id"],
        )
        return payload
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.get("/resume-builder/latest")
def load_resume_builder_route(auth_tokens=Depends(get_optional_auth_tokens)):
    access_token, refresh_token = auth_tokens
    return load_latest_resume_builder_session(
        access_token=access_token or "",
        refresh_token=refresh_token or "",
    )


@router.post("/resume-builder/message")
@limiter.limit(LIMIT_LLM)
def answer_resume_builder_route(
    request: Request,
    payload: ResumeBuilderMessageRequestModel,
    auth_tokens=Depends(get_optional_auth_tokens),
):
    access_token, refresh_token = auth_tokens
    try:
        response = answer_resume_builder_message(
            session_id=payload.session_id,
            message=payload.message,
        )
        persist_resume_builder_session(
            access_token=access_token or "",
            refresh_token=refresh_token or "",
            session_id=payload.session_id,
        )
        return response
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/resume-builder/generate")
@limiter.limit(LIMIT_HEAVY)
def generate_resume_builder_route(
    request: Request,
    payload: ResumeBuilderSessionRequestModel,
    auth_tokens=Depends(get_optional_auth_tokens),
):
    access_token, refresh_token = auth_tokens
    try:
        response = generate_resume_builder_resume(session_id=payload.session_id)
        persist_resume_builder_session(
            access_token=access_token or "",
            refresh_token=refresh_token or "",
            session_id=payload.session_id,
        )
        return response
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/resume-builder/update")
@limiter.limit(LIMIT_LLM)
def update_resume_builder_route(
    request: Request,
    payload: ResumeBuilderUpdateRequestModel,
    auth_tokens=Depends(get_optional_auth_tokens),
):
    access_token, refresh_token = auth_tokens
    try:
        response = update_resume_builder_session(
            session_id=payload.session_id,
            draft_updates=payload.draft_profile,
        )
        persist_resume_builder_session(
            access_token=access_token or "",
            refresh_token=refresh_token or "",
            session_id=payload.session_id,
        )
        return response
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/resume-builder/commit")
@limiter.limit(LIMIT_HEAVY)
def commit_resume_builder_route(
    request: Request,
    payload: ResumeBuilderSessionRequestModel,
    auth_tokens=Depends(get_optional_auth_tokens),
):
    access_token, refresh_token = auth_tokens
    try:
        response = commit_resume_builder_session(session_id=payload.session_id)
        clear_resume_builder_session(
            access_token=access_token or "",
            refresh_token=refresh_token or "",
        )
        return response
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/analyze")
@limiter.limit(LIMIT_HEAVY)
def analyze_workspace(
    request: Request,
    payload: WorkspaceAnalyzeRequestModel,
    auth_tokens=Depends(get_optional_auth_tokens),
):
    access_token, refresh_token = auth_tokens
    try:
        return run_workspace_analysis(
            resume_text=payload.resume_text,
            resume_filetype=payload.resume_filetype,
            resume_source=payload.resume_source,
            job_description_text=payload.job_description_text,
            imported_job_posting=payload.imported_job_posting,
            run_assisted=payload.run_assisted,
            access_token=access_token or "",
            refresh_token=refresh_token or "",
        )
    except AppError as error:
        _raise_http_error(error)


@router.post(
    "/analyze-jobs",
    response_model=WorkspaceAnalyzeJobCreatedResponseModel,
)
@limiter.limit(LIMIT_HEAVY)
def start_workspace_analysis_job_route(
    request: Request,
    payload: WorkspaceAnalyzeRequestModel,
    auth_tokens=Depends(get_optional_auth_tokens),
):
    access_token, refresh_token = auth_tokens
    return start_workspace_analysis_job(
        resume_text=payload.resume_text,
        resume_filetype=payload.resume_filetype,
        resume_source=payload.resume_source,
        job_description_text=payload.job_description_text,
        imported_job_posting=payload.imported_job_posting,
        access_token=access_token or "",
        refresh_token=refresh_token or "",
    )


@router.get(
    "/analyze-jobs/{job_id}",
    response_model=WorkspaceAnalyzeJobStatusResponseModel,
)
def get_workspace_analysis_job_route(job_id: str):
    payload = get_workspace_analysis_job(job_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="Analysis job not found.")
    return payload


@router.post("/assistant/answer")
@limiter.limit(LIMIT_LLM)
def answer_assistant_question(
    request: Request,
    payload: WorkspaceAssistantRequestModel,
    auth_tokens=Depends(get_optional_auth_tokens),
):
    access_token, refresh_token = auth_tokens
    try:
        return answer_workspace_question(
            question=payload.question,
            current_page=payload.current_page,
            workspace_snapshot=payload.workspace_snapshot,
            history=[item.model_dump() for item in payload.history],
            access_token=access_token or "",
            refresh_token=refresh_token or "",
        )
    except AppError as error:
        _raise_http_error(error)


@router.post("/assistant/answer/stream")
@limiter.limit(LIMIT_LLM)
def stream_assistant_answer(
    request: Request,
    payload: WorkspaceAssistantRequestModel,
    auth_tokens=Depends(get_optional_auth_tokens),
):
    """Server-Sent Events sibling of ``/assistant/answer``.

    Same request body, but the response is ``text/event-stream`` and
    emits ``meta`` → ``delta``... → ``followups`` → ``done`` events
    (or ``error`` → ``done`` on failure). See
    ``stream_workspace_question`` for the event contract.

    The ``X-Accel-Buffering: no`` header tells Caddy (and any other
    well-behaved reverse proxy) to flush each frame immediately
    instead of buffering the response. The Caddyfile also sets
    ``flush_interval -1`` for belt-and-braces.
    """
    access_token, refresh_token = auth_tokens
    return StreamingResponse(
        stream_workspace_question(
            question=payload.question,
            current_page=payload.current_page,
            workspace_snapshot=payload.workspace_snapshot,
            history=[item.model_dump() for item in payload.history],
            access_token=access_token or "",
            refresh_token=refresh_token or "",
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/save")
def save_workspace_route(
    payload: WorkspaceSaveRequestModel,
    auth_tokens=Depends(get_optional_auth_tokens),
):
    access_token, refresh_token = auth_tokens
    try:
        return save_workspace_snapshot(
            access_token=access_token or "",
            refresh_token=refresh_token or "",
            workspace_snapshot=payload.workspace_snapshot,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except AppError as error:
        _raise_http_error(error)


@router.get("/saved")
def load_saved_workspace_route(auth_tokens=Depends(get_optional_auth_tokens)):
    access_token, refresh_token = auth_tokens
    try:
        return load_saved_workspace_snapshot(
            access_token=access_token or "",
            refresh_token=refresh_token or "",
        )
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except AppError as error:
        _raise_http_error(error)


@router.get("/saved-jobs")
def list_saved_jobs_route(auth_tokens=Depends(get_optional_auth_tokens)):
    access_token, refresh_token = auth_tokens
    try:
        return list_saved_jobs(
            access_token=access_token or "",
            refresh_token=refresh_token or "",
        )
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except AppError as error:
        _raise_http_error(error)


@router.post("/saved-jobs")
def save_saved_job_route(
    payload: SavedJobRequestModel,
    auth_tokens=Depends(get_optional_auth_tokens),
):
    access_token, refresh_token = auth_tokens
    try:
        return save_saved_job(
            access_token=access_token or "",
            refresh_token=refresh_token or "",
            job_posting=payload.job_posting,
        )
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except AppError as error:
        _raise_http_error(error)


@router.delete("/saved-jobs/{job_id}")
def remove_saved_job_route(job_id: str, auth_tokens=Depends(get_optional_auth_tokens)):
    access_token, refresh_token = auth_tokens
    try:
        return remove_saved_job(
            access_token=access_token or "",
            refresh_token=refresh_token or "",
            job_id=job_id,
        )
    except RuntimeError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except AppError as error:
        _raise_http_error(error)


@router.post("/artifacts/export")
@limiter.limit(LIMIT_PARSE)
def export_workspace_artifact_route(request: Request, payload: WorkspaceArtifactExportRequestModel):
    try:
        return export_workspace_artifact(
            workspace_snapshot=payload.workspace_snapshot,
            artifact_kind=payload.artifact_kind,
            export_format=payload.export_format,
            resume_theme=payload.resume_theme,
        )
    except AppError as error:
        _raise_http_error(error)


@router.post("/artifacts/preview")
@limiter.limit(LIMIT_PARSE)
def preview_workspace_artifact_route(request: Request, payload: WorkspaceArtifactPreviewRequestModel):
    try:
        return preview_workspace_artifact(
            workspace_snapshot=payload.workspace_snapshot,
            artifact_kind=payload.artifact_kind,
            resume_theme=payload.resume_theme,
        )
    except AppError as error:
        _raise_http_error(error)
