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
    # `premium` opts into the higher-trust model routing (lands in a
    # later step) AND charges against the tier's premium_applications
    # counter instead of tailored_applications. Free tier has a
    # premium cap of 0, so a Free user setting premium=True gets a
    # 429 with a "Pro+ only" message via the global quota handler.
    # Defaults to False so existing callers (and clients on the
    # current frontend) keep landing on the standard tailored path
    # without a wire-protocol change.
    premium: bool = False

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
    # Structured tier-limit envelope (code/counter/current/cap/
    # reset_period/tier) when a quota gate fired inside the worker, so
    # the polling client can render the upgrade CTA (review CRITICAL-2).
    error: dict[str, Any] | None = None


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
    resume_theme: str = Field(default="professional_neutral", max_length=80)
    cover_letter_theme: str = Field(default="professional_neutral", max_length=80)

    @field_validator("resume_theme", "cover_letter_theme", mode="before")
    @classmethod
    def _strip_theme(cls, value):
        return str(value or "").strip()


class WorkspaceArtifactPreviewRequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace_snapshot: dict[str, Any]
    artifact_kind: Literal["tailored_resume", "cover_letter"]
    resume_theme: str = Field(default="professional_neutral", max_length=80)
    cover_letter_theme: str = Field(default="professional_neutral", max_length=80)

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
    # Count of work-experience *entries* on the resume (e.g. 4 jobs
    # held). NOT years of total experience — the earlier name
    # `experience_count` led the LLM to answer "how many years?"
    # with the entry count.
    experience_entries_count: int = Field(default=0, ge=0)
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
    theme: Literal[
        "classic_ats",
        "professional_neutral",
        "modern_blue",
        "creative_warm",
        "architect_mono",
        "noir_cream",
        # ADR-032 — six bespoke two-column designer themes. NON-ATS
        # (sidebar layout) but user-selectable; Pro/Business by the
        # existing by-exclusion gate. They replaced the retired
        # `presentation_twocol` placeholder. DOCX of a two-column theme
        # renders single-column (DOCX two-column deferred per ADR-015).
        "timeline_tech",
        "editorial_minimal",
        "classic_slate",
        "monochrome_black",
        "plum_berry",
        "burgundy_champagne",
    ] = "professional_neutral"

    @field_validator("session_id", mode="before")
    @classmethod
    def _strip_export_session_id(cls, value):
        return str(value or "").strip()


class ResumeBuilderPreviewRequestModel(BaseModel):
    """Body shape for POST /workspace/resume-builder/preview.

    Renders the builder's resume as themed HTML (no download) so the
    user can see it in any theme before deciding. LLM-free — the theme
    only affects rendering, never re-structures."""

    model_config = ConfigDict(extra="forbid")

    session_id: str = Field(min_length=1, max_length=120)
    theme: Literal[
        "classic_ats",
        "professional_neutral",
        "modern_blue",
        "creative_warm",
        "architect_mono",
        "noir_cream",
        # ADR-032 — six bespoke two-column designer themes, same set as
        # the export model. Non-ATS but user-selectable; the preview
        # renders them so the picker can show the two-column look.
        "timeline_tech",
        "editorial_minimal",
        "classic_slate",
        "monochrome_black",
        "plum_berry",
        "burgundy_champagne",
    ] = "professional_neutral"

    @field_validator("session_id", mode="before")
    @classmethod
    def _strip_preview_session_id(cls, value):
        return str(value or "").strip()


class WorkspaceFeedbackRequestModel(BaseModel):
    """Body shape for POST /workspace/feedback.

    Each user 👍 / 👎 on a tailored artifact / cover letter / JD summary
    / assistant turn / resume-builder session writes one row. The
    Literal surface + rating echo the CHECK constraint in the SQL
    migration so a typo in the client fails at the FastAPI parse
    boundary instead of bouncing off Postgres's check.

    trace_id is optional — some surfaces (resume_builder_session) don't
    map to a single LLM call so there's nothing single-trace to point
    at; others (tailored_resume, cover_letter, assistant_turn) DO have
    a trace_id from the OpenAIService cost-trace bridge. The route
    forwards whatever the client sends through to the service layer,
    which normalizes empty strings to NULL.
    """

    model_config = ConfigDict(extra="forbid")

    surface: Literal[
        "tailored_resume",
        "cover_letter",
        "jd_summary",
        "assistant_turn",
        "resume_builder_session",
    ]
    rating: Literal["up", "down"]
    # trace_id is a UUID-shaped string when present; we don't validate
    # the UUID pattern at the model boundary because the table accepts
    # Persistence target (``aijobagent_feedback.trace_id``) is a UUID
    # column — validate the shape at the request boundary so a
    # malformed value produces a clean 422 with a field-specific error
    # rather than falling through to the Supabase write and surfacing
    # as an opaque 502. CodeRabbit Major on PR #3.
    trace_id: str | None = Field(default=None, max_length=120)
    # 4096-char cap mirrors COMMENT_MAX_CHARS in feedback_service.py.
    # Pydantic rejects anything longer at parse time — defense in depth
    # against a malicious client posting megabytes of comment text.
    comment: str = Field(default="", max_length=4096)

    @field_validator("trace_id", mode="before")
    @classmethod
    def _strip_trace_id(cls, value):
        if value is None:
            return None
        stripped = str(value).strip()
        if not stripped:
            return None
        # Reject non-UUID shapes at the request boundary so bad data
        # never reaches the Supabase column. ``uuid.UUID`` accepts
        # both hyphenated and bare 32-char forms; we re-emit the
        # canonical hyphenated string so downstream code doesn't have
        # to handle two representations.
        import uuid as _uuid

        try:
            return str(_uuid.UUID(stripped))
        except (ValueError, AttributeError):
            raise ValueError(
                "trace_id must be a UUID (canonical or 32-char hex form)."
            )

    @field_validator("comment", mode="before")
    @classmethod
    def _strip_comment(cls, value):
        if value is None:
            return ""
        return str(value)
