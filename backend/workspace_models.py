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


class WorkspaceAnalyzeJobCreatedResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: str
    stage_title: str | None = None
    stage_detail: str | None = None
    progress_percent: int = 0
    result: dict[str, Any] | None = None
    error_message: str | None = None


class WorkspaceAnalyzeJobStatusResponseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    status: str
    stage_title: str | None = None
    stage_detail: str | None = None
    progress_percent: int = 0
    result: dict[str, Any] | None = None
    error_message: str | None = None


class WorkspaceSaveRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_snapshot: dict[str, Any]


class SavedJobRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_posting: dict[str, Any]


class WorkspaceArtifactExportRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_snapshot: dict[str, Any]
    artifact_kind: Literal["tailored_resume", "cover_letter"]
    # DOCX replaced the markdown download in Phase 2 of the DOCX
    # export plan; markdown lives only as the in-app preview content
    # field, not as a download format.
    export_format: Literal["pdf", "docx"]
    resume_theme: str = Field(default="classic_ats", max_length=80)
    cover_letter_theme: str = Field(default="classic_ats", max_length=80)

    @field_validator("resume_theme", "cover_letter_theme", mode="before")
    @classmethod
    def _strip_theme(cls, value):
        return str(value or "").strip()


class WorkspaceArtifactPreviewRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_snapshot: dict[str, Any]
    artifact_kind: Literal["tailored_resume", "cover_letter"]
    resume_theme: str = Field(default="classic_ats", max_length=80)
    cover_letter_theme: str = Field(default="classic_ats", max_length=80)

    @field_validator("resume_theme", "cover_letter_theme", mode="before")
    @classmethod
    def _strip_preview_theme(cls, value):
        return str(value or "").strip()


class AssistantHistoryTurnModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=1000)
    answer: str = Field(min_length=1, max_length=4000)

    @field_validator("question", "answer", mode="before")
    @classmethod
    def _strip_text(cls, value):
        return str(value or "").strip()


class ResumeSummaryModel(BaseModel):
    """Compact projection of a parsed CandidateProfile.

    Counts + identity only — never includes raw resume text. Sent on
    every assistant turn so the LLM can answer "is my resume parsed?"
    style questions without us shipping the full profile blob.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="", max_length=200)
    location: str = Field(default="", max_length=200)
    skills_count: int = Field(default=0, ge=0)
    experience_count: int = Field(default=0, ge=0)
    has_certifications: bool = False


class JdSummaryModel(BaseModel):
    """Compact projection of a parsed JobDescription / review.

    Counts + identity only — never includes the full JD body.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="", max_length=200)
    location: str | None = Field(default=None, max_length=200)
    hard_skills_count: int = Field(default=0, ge=0)
    soft_skills_count: int = Field(default=0, ge=0)
    must_haves_count: int = Field(default=0, ge=0)


class WorkspaceStateContextModel(BaseModel):
    """Live workspace state, sent with every assistant request.

    Replaces the "blind" pre-analysis assistant — the LLM now sees
    which step the user is on, whether they've parsed a resume / JD,
    how many jobs they've saved, etc. The full
    `workspace_snapshot` (analysis result) still rides separately
    when an analysis has run.
    """

    model_config = ConfigDict(extra="forbid")

    current_step: Literal["resume", "jobs", "jd", "analysis"]
    has_resume: bool = False
    resume_summary: ResumeSummaryModel | None = None
    has_jd: bool = False
    jd_summary: JdSummaryModel | None = None
    has_analysis: bool = False
    saved_jobs_count: int = Field(default=0, ge=0)
    last_search_query: str | None = Field(default=None, max_length=200)


class WorkspaceAssistantRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=1000)
    current_page: str = Field(default="Workspace", max_length=120)
    workspace_state: WorkspaceStateContextModel | None = None
    workspace_snapshot: dict[str, Any] | None = None
    history: list[AssistantHistoryTurnModel] = Field(default_factory=list)

    @field_validator("question", "current_page", mode="before")
    @classmethod
    def _strip_text(cls, value):
        return str(value or "").strip()


class ResumeBuilderMessageRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=8000)
    input_mode: Literal["text", "voice"] = "text"

    @field_validator("session_id", "message", mode="before")
    @classmethod
    def _strip_builder_text(cls, value):
        return str(value or "").strip()


class ResumeBuilderSessionRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=120)

    @field_validator("session_id", mode="before")
    @classmethod
    def _strip_session_id(cls, value):
        return str(value or "").strip()


class ResumeBuilderUpdateRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=120)
    draft_profile: dict[str, Any]

    @field_validator("session_id", mode="before")
    @classmethod
    def _strip_update_session_id(cls, value):
        return str(value or "").strip()


class ResumeBuilderExportRequestModel(BaseModel):
    """Phase 5: download the generated base resume as PDF or DOCX.

    The resume builder is a separate intake surface (no JD context),
    so the export bypasses the workspace_snapshot pipeline and
    synthesizes a TailoredResumeArtifact straight from the session's
    draft profile."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=120)
    export_format: Literal["pdf", "docx"]
    theme: Literal["classic_ats", "professional_neutral"] = "classic_ats"

    @field_validator("session_id", mode="before")
    @classmethod
    def _strip_export_session_id(cls, value):
        return str(value or "").strip()
