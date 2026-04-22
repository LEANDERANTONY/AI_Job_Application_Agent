from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class UploadedFilePayloadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=120)
    content_base64: str = Field(min_length=1)

    @field_validator("filename", "mime_type", "content_base64", mode="before")
    @classmethod
    def _strip_text(cls, value):
        return str(value or "").strip()


class WorkspaceAnalyzeRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resume_text: str = Field(min_length=1)
    resume_filetype: str = Field(default="TXT", max_length=40)
    resume_source: str = Field(default="workspace", max_length=120)
    job_description_text: str = Field(min_length=1)
    imported_job_posting: dict[str, Any] | None = None
    run_assisted: bool = False

    @field_validator(
        "resume_text",
        "resume_filetype",
        "resume_source",
        "job_description_text",
        mode="before",
    )
    @classmethod
    def _strip_required_text(cls, value):
        return str(value or "").strip()


class WorkspaceSaveRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_snapshot: dict[str, Any]


class SavedJobRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_posting: dict[str, Any]


class WorkspaceArtifactExportRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_snapshot: dict[str, Any]
    artifact_kind: Literal["tailored_resume", "cover_letter", "report", "bundle"]
    export_format: Literal["markdown", "pdf", "zip"]
    resume_theme: str = Field(default="classic_ats", max_length=80)

    @field_validator("resume_theme", mode="before")
    @classmethod
    def _strip_resume_theme(cls, value):
        return str(value or "").strip()


class WorkspaceArtifactPreviewRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_snapshot: dict[str, Any]
    artifact_kind: Literal["tailored_resume", "cover_letter", "report"]
    resume_theme: str = Field(default="classic_ats", max_length=80)

    @field_validator("resume_theme", mode="before")
    @classmethod
    def _strip_preview_resume_theme(cls, value):
        return str(value or "").strip()


class AssistantHistoryTurnModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=1000)
    answer: str = Field(min_length=1, max_length=4000)

    @field_validator("question", "answer", mode="before")
    @classmethod
    def _strip_text(cls, value):
        return str(value or "").strip()


class WorkspaceAssistantRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=1000)
    current_page: str = Field(default="Workspace", max_length=120)
    workspace_snapshot: dict[str, Any] | None = None
    history: list[AssistantHistoryTurnModel] = Field(default_factory=list)

    @field_validator("question", "current_page", mode="before")
    @classmethod
    def _strip_text(cls, value):
        return str(value or "").strip()
