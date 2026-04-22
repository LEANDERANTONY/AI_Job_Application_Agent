from fastapi import APIRouter, Depends, HTTPException

from backend.request_auth import get_optional_auth_tokens
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
from backend.services.workspace_service import (
    answer_workspace_question,
    parse_job_description_upload,
    parse_resume_upload,
    run_workspace_analysis,
)
from backend.workspace_models import (
    SavedJobRequestModel,
    UploadedFilePayloadModel,
    WorkspaceAnalyzeRequestModel,
    WorkspaceAssistantRequestModel,
    WorkspaceArtifactExportRequestModel,
    WorkspaceArtifactPreviewRequestModel,
    WorkspaceSaveRequestModel,
)
from src.errors import AppError


router = APIRouter(prefix="/workspace", tags=["workspace"])


def _raise_http_error(error: AppError):
    raise HTTPException(status_code=400, detail=error.user_message)


@router.post("/resume/upload")
def upload_resume(payload: UploadedFilePayloadModel):
    try:
        return parse_resume_upload(
            filename=payload.filename,
            mime_type=payload.mime_type,
            content_base64=payload.content_base64,
        )
    except AppError as error:
        _raise_http_error(error)


@router.post("/job-description/upload")
def upload_job_description(payload: UploadedFilePayloadModel):
    try:
        return parse_job_description_upload(
            filename=payload.filename,
            mime_type=payload.mime_type,
            content_base64=payload.content_base64,
        )
    except AppError as error:
        _raise_http_error(error)


@router.post("/analyze")
def analyze_workspace(
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


@router.post("/assistant/answer")
def answer_assistant_question(
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
def export_workspace_artifact_route(payload: WorkspaceArtifactExportRequestModel):
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
def preview_workspace_artifact_route(payload: WorkspaceArtifactPreviewRequestModel):
    try:
        return preview_workspace_artifact(
            workspace_snapshot=payload.workspace_snapshot,
            artifact_kind=payload.artifact_kind,
            resume_theme=payload.resume_theme,
        )
    except AppError as error:
        _raise_http_error(error)
