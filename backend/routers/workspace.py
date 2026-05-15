from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from backend.rate_limit import LIMIT_HEAVY, LIMIT_LLM, LIMIT_PARSE, limiter
from backend.request_auth import get_optional_auth_tokens
from backend.services.auth_session_service import (
    build_openai_service_for_context,
    resolve_authenticated_context,
)
from backend.services.feedback_service import (
    InvalidFeedbackError,
    record_feedback,
)
from backend.services.transcribe_service import (
    MAX_AUDIO_BYTES,
    transcribe_audio,
)
from backend.services.resume_builder_persistence_service import (
    clear_resume_builder_session,
    hydrate_resume_builder_session_if_needed,
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
    export_resume_builder_artifact,
    generate_resume_builder_resume,
    start_resume_builder_session,
    update_resume_builder_session,
)
from backend.services.workspace_quota_service import (
    WorkspaceQuotaAuthRequired,
    get_workspace_quota_snapshot,
)
from backend.services.workspace_service import (
    answer_workspace_question,
    parse_job_description_upload,
    parse_resume_upload,
    prepare_stream_workspace_question,
    run_workspace_analysis,
    stream_workspace_question,
)
from backend.services.workspace_run_jobs import (
    JOB_RETRY_AFTER_SECONDS,
    WorkspaceRunJobCapacityError,
    get_workspace_analysis_job,
    start_workspace_analysis_job,
)
from backend.workspace_models import (
    ResumeBuilderExportRequestModel,
    ResumeBuilderMessageRequestModel,
    ResumeBuilderSessionRequestModel,
    ResumeBuilderUpdateRequestModel,
    SavedJobRequestModel,
    UploadedFilePayloadModel,
    WorkspaceAnalyzeRequestModel,
    WorkspaceAssistantRequestModel,
    WorkspaceArtifactExportRequestModel,
    WorkspaceArtifactPreviewRequestModel,
    WorkspaceFeedbackRequestModel,
    WorkspaceSaveRequestModel,
    WorkspaceAnalyzeJobCreatedResponseModel,
    WorkspaceAnalyzeJobStatusResponseModel,
)
from src.errors import (
    AppError,
    AuthRequiredError,
    InputValidationError,
    QuotaExceededError,
)


router = APIRouter(prefix="/workspace", tags=["workspace"])


def _raise_http_error(error: AppError):
    # QuotaExceededError is an AppError subclass but it needs to
    # propagate out of the route so the global FastAPI handler can
    # build the canonical 429 payload. Re-raise so the exception
    # handler chain wins over the generic 400-on-AppError fallback.
    if isinstance(error, QuotaExceededError):
        raise error
    raise HTTPException(status_code=400, detail=error.user_message)


def _resolve_openai_service(access_token: str, refresh_token: str):
    """Best-effort OpenAIService for an authenticated request.

    Returns None when tokens are missing OR the auth/openai construction
    fails — caller (resume builder, etc.) treats None as "no LLM
    available" and falls back to the deterministic path."""
    if not (access_token and refresh_token):
        return None
    try:
        auth_context = resolve_authenticated_context(
            access_token=access_token,
            refresh_token=refresh_token,
        )
    except Exception:
        return None
    if auth_context is None:
        return None
    try:
        openai_service, _ = build_openai_service_for_context(auth_context)
    except Exception:
        return None
    return openai_service


def _attach_persistence_status(
    response: dict,
    persist_result: dict | None,
    *,
    access_token: str,
    refresh_token: str,
) -> dict:
    """Tag a resume-builder route response with the persistence outcome.

    Tri-state so the UI can communicate clearly:
      - "saved":         signed in + Supabase upsert succeeded
      - "skipped":       signed in but persistence failed (Supabase
                         unreachable, RLS reject, payload export error).
                         The user's draft is in-memory only and at risk
                         from a container restart.
      - "unauthenticated": no auth tokens; persistence was never
                           attempted. Surface a "sign in to save" prompt
                           in the UI instead of a generic skip.

    Also forwards `expires_at` (ISO timestamp from the saved row) when
    available so the UI can render a "refreshes through X" hint next
    to the indicator. The TTL refreshes on every save, so the value
    represents the latest write's expiry.

    `persist_result` is the dict returned by
    persist_resume_builder_session; treat None as a missing call.
    """
    if not (access_token and refresh_token):
        response["persistence_status"] = "unauthenticated"
        return response
    raw_status = (persist_result or {}).get("status", "skipped")
    response["persistence_status"] = (
        "saved" if raw_status == "saved" else "skipped"
    )
    expires_at = (persist_result or {}).get("expires_at") or ""
    if expires_at:
        response["expires_at"] = expires_at
    return response


@router.post("/resume/upload")
@limiter.limit(LIMIT_PARSE)
def upload_resume(
    request: Request,
    payload: UploadedFilePayloadModel,
    auth_tokens=Depends(get_optional_auth_tokens),
):
    """Parse an uploaded resume into a CandidateProfile.

    Auth tokens are optional (anonymous users can still preview a
    parse) but are threaded through to ``parse_resume_upload`` so the
    resume_parses quota gate can attribute the credit. The gate
    short-circuits cleanly when tokens are empty.
    """
    access_token, refresh_token = auth_tokens
    try:
        return parse_resume_upload(
            filename=payload.filename,
            mime_type=payload.mime_type,
            content_base64=payload.content_base64,
            access_token=access_token or "",
            refresh_token=refresh_token or "",
        )
    except AppError as error:
        _raise_http_error(error)


@router.post("/transcribe")
@limiter.limit(LIMIT_LLM)
async def transcribe_voice_route(
    request: Request,
    file: UploadFile = File(...),
    auth_tokens=Depends(get_optional_auth_tokens),
):
    """Whisper-backed voice transcription for the Resume Builder chat
    input (primary surface) and the Workspace assistant chat
    (secondary).

    Multipart audio blob in; ``{"text": str, "duration_seconds":
    float}`` out. Auth required — anonymous callers get a 401. Cost is
    recorded as a trace row with ``task_name="transcribe"`` so the
    nightly tier-margin report breaks Whisper out as its own line item
    next to the chat-model calls.

    The 25 MB upper bound (``MAX_AUDIO_BYTES``) matches OpenAI's
    Whisper API limit; we reject locally with a friendly message
    instead of letting OpenAI surface a generic 413 through the agent
    error path.

    Quota: free for all tiers (Whisper is cheap enough). Downstream
    caps still apply — the transcribed text flows into the resume
    builder (``resume_builder_sessions``) or the assistant
    (``assistant_turns``) which gate as usual. The dedicated rate
    limit (``LIMIT_LLM`` = 30/minute) keeps a recorder loop from
    nuking the budget.
    """
    access_token, refresh_token = auth_tokens
    if not (access_token and refresh_token):
        # Mirror the 401 the resume builder + quota endpoints use. We
        # don't fall through to the service layer here because the
        # service raises an InputValidationError that the catch-all
        # converts to 400 — we want a clean 401 for the frontend's
        # re-auth nudge.
        raise HTTPException(
            status_code=401,
            detail="Sign in with Google before transcribing voice input.",
        )

    # Read the upload into memory. UploadFile.read() loads the whole
    # body — fine for a 25 MB cap; FastAPI's spooled file would still
    # buffer through memory at that size anyway. Reading once into
    # bytes keeps the request-time error path simple.
    audio_bytes = await file.read()
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        # Same threshold the service layer checks, but we catch here
        # too so an oversize body doesn't even reach the OpenAI key
        # resolution path. Returning 413 mirrors the HTTP-spec status
        # for "request entity too large" — friendlier for a generic
        # HTTP client than the 400 the service path would surface.
        raise HTTPException(
            status_code=413,
            detail=(
                "Audio exceeds the 25 MB limit. Try a shorter recording "
                "or a more compressed format."
            ),
        )

    try:
        return transcribe_audio(
            audio_bytes=audio_bytes,
            content_type=file.content_type or "",
            access_token=access_token or "",
            refresh_token=refresh_token or "",
        )
    except AuthRequiredError as error:
        # 401, not 400 — the frontend's interceptor needs the 401 to
        # trigger the re-auth flow. Previously both auth + payload
        # failures collapsed onto InputValidationError → 400, which
        # confused expired sessions with malformed bodies and broke
        # re-auth. Codex P2 + CodeRabbit Major on PR #3.
        raise HTTPException(status_code=401, detail=error.user_message)
    except InputValidationError as error:
        # 400-by-default at the global handler doesn't carry the
        # right semantic; an empty / oversize / wrong-type audio
        # body is a client problem we want surfaced clearly. The
        # detail copy is already user-facing.
        raise HTTPException(status_code=400, detail=error.user_message)
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
        # The resume_builder_sessions quota gate fires inside
        # start_resume_builder_session -- we pass the auth tokens so it
        # can attribute the credit. Free tier consumes a LIFETIME slot
        # (cap 1, one onboarding ever); Pro and Business consume from
        # a MONTHLY slot pool (3 / 15). The lifetime/monthly switch
        # lives inside the service so the route stays tier-agnostic.
        payload = start_resume_builder_session(
            access_token=access_token or "",
            refresh_token=refresh_token or "",
        )
        persist_result = persist_resume_builder_session(
            access_token=access_token or "",
            refresh_token=refresh_token or "",
            session_id=payload["session_id"],
        )
        return _attach_persistence_status(
            payload,
            persist_result,
            access_token=access_token or "",
            refresh_token=refresh_token or "",
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except AppError as error:
        _raise_http_error(error)


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
        hydrate_resume_builder_session_if_needed(
            access_token=access_token or "",
            refresh_token=refresh_token or "",
            session_id=payload.session_id,
        )
        openai_service = _resolve_openai_service(
            access_token or "",
            refresh_token or "",
        )
        response = answer_resume_builder_message(
            session_id=payload.session_id,
            message=payload.message,
            openai_service=openai_service,
        )
        persist_result = persist_resume_builder_session(
            access_token=access_token or "",
            refresh_token=refresh_token or "",
            session_id=payload.session_id,
        )
        return _attach_persistence_status(
            response,
            persist_result,
            access_token=access_token or "",
            refresh_token=refresh_token or "",
        )
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
        hydrate_resume_builder_session_if_needed(
            access_token=access_token or "",
            refresh_token=refresh_token or "",
            session_id=payload.session_id,
        )
        # LLM-first structuring at generate time — falls back to regex
        # parser inside the service when the service is None or errors.
        openai_service = _resolve_openai_service(
            access_token or "",
            refresh_token or "",
        )
        response = generate_resume_builder_resume(
            session_id=payload.session_id,
            openai_service=openai_service,
        )
        persist_result = persist_resume_builder_session(
            access_token=access_token or "",
            refresh_token=refresh_token or "",
            session_id=payload.session_id,
        )
        return _attach_persistence_status(
            response,
            persist_result,
            access_token=access_token or "",
            refresh_token=refresh_token or "",
        )
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
        hydrate_resume_builder_session_if_needed(
            access_token=access_token or "",
            refresh_token=refresh_token or "",
            session_id=payload.session_id,
        )
        response = update_resume_builder_session(
            session_id=payload.session_id,
            draft_updates=payload.draft_profile,
        )
        persist_result = persist_resume_builder_session(
            access_token=access_token or "",
            refresh_token=refresh_token or "",
            session_id=payload.session_id,
        )
        return _attach_persistence_status(
            response,
            persist_result,
            access_token=access_token or "",
            refresh_token=refresh_token or "",
        )
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
        hydrate_resume_builder_session_if_needed(
            access_token=access_token or "",
            refresh_token=refresh_token or "",
            session_id=payload.session_id,
        )
        openai_service = _resolve_openai_service(
            access_token or "",
            refresh_token or "",
        )
        response = commit_resume_builder_session(
            session_id=payload.session_id,
            openai_service=openai_service,
        )
        clear_resume_builder_session(
            access_token=access_token or "",
            refresh_token=refresh_token or "",
        )
        return response
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))


@router.post("/resume-builder/export")
@limiter.limit(LIMIT_HEAVY)
def export_resume_builder_route(
    request: Request,
    payload: ResumeBuilderExportRequestModel,
    auth_tokens=Depends(get_optional_auth_tokens),
):
    """Phase 5: download the builder's generated base resume.

    Auth-gated like the other resume-builder routes — same hydrate +
    persistence story so a container restart between Generate and
    Download doesn't leave the user staring at a 400. Reuses
    `export_pdf_bytes` / `export_docx_bytes` via the service-layer
    `export_resume_builder_artifact()` helper.
    """
    access_token, refresh_token = auth_tokens
    try:
        hydrate_resume_builder_session_if_needed(
            access_token=access_token or "",
            refresh_token=refresh_token or "",
            session_id=payload.session_id,
        )
        openai_service = _resolve_openai_service(
            access_token or "",
            refresh_token or "",
        )
        return export_resume_builder_artifact(
            session_id=payload.session_id,
            export_format=payload.export_format,
            theme=payload.theme,
            openai_service=openai_service,
        )
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
            premium=payload.premium,
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
    try:
        return start_workspace_analysis_job(
            resume_text=payload.resume_text,
            resume_filetype=payload.resume_filetype,
            resume_source=payload.resume_source,
            job_description_text=payload.job_description_text,
            imported_job_posting=payload.imported_job_posting,
            premium=payload.premium,
            access_token=access_token or "",
            refresh_token=refresh_token or "",
        )
    except WorkspaceRunJobCapacityError:
        raise HTTPException(
            status_code=503,
            detail=(
                "The workspace is busy running other agentic workflows right "
                "now. Please try again in a few seconds."
            ),
            headers={"Retry-After": str(JOB_RETRY_AFTER_SECONDS)},
        )
    except QuotaExceededError:
        # Let the global handler build the structured 429. Without
        # this re-raise the surrounding `except WorkspaceRunJobCapacityError`
        # path would still allow QuotaExceededError to propagate, but
        # being explicit here documents that quota rejection is the
        # second supported failure mode on this surface.
        raise


@router.post("/feedback")
@limiter.limit(LIMIT_LLM)
def record_workspace_feedback_route(
    request: Request,
    payload: WorkspaceFeedbackRequestModel,
    auth_tokens=Depends(get_optional_auth_tokens),
):
    """Record a single 👍 / 👎 feedback row.

    Wired into every artifact surface (tailored resume, cover letter,
    JD summary, assistant turn, resume-builder session). Validates
    surface + rating at the Pydantic boundary so a typo in the
    frontend fails fast with a 422 instead of bouncing off the
    Postgres CHECK constraint.

    Auth required: an anonymous caller has no user_id to attribute the
    feedback to and the table's RLS policy + the service-role write
    path would both reject the insert. Returns 401 for clean re-auth
    plumbing — mirrors /workspace/quota.

    Rate limit: LIMIT_LLM (30/min) is plenty for a real user (one
    rating per artifact, < 10 surfaces per session) and high enough
    not to interfere with rapid-clicking test runs.
    """
    access_token, refresh_token = auth_tokens
    if not (access_token and refresh_token):
        raise HTTPException(
            status_code=401,
            detail="Sign in with Google to record feedback.",
        )
    try:
        auth_context = resolve_authenticated_context(
            access_token=access_token,
            refresh_token=refresh_token,
        )
    except AppError:
        # Token validation failed -- surface as auth required.
        raise HTTPException(
            status_code=401,
            detail="Your session has expired. Sign in again to record feedback.",
        )

    user_id = str(getattr(auth_context.app_user, "id", "") or "")
    if not user_id:
        # Defense in depth: a malformed JWT shouldn't get through
        # resolve_authenticated_context but if it does, refusing the
        # write with 401 is the right call.
        raise HTTPException(
            status_code=401,
            detail="No user identity available for this session.",
        )

    try:
        return record_feedback(
            user_id=user_id,
            surface=payload.surface,
            rating=payload.rating,
            trace_id=payload.trace_id,
            comment=payload.comment,
        )
    except InvalidFeedbackError as error:
        raise HTTPException(status_code=400, detail=str(error))
    except Exception as error:  # noqa: BLE001 - boundary translation
        # The service layer re-raises any backend error; we convert to
        # 502 so the frontend's optimistic UI can show "couldn't save"
        # without confusing a real validation error with a Supabase
        # outage. The detail copy is intentionally generic — surfacing
        # the underlying Supabase error string would leak schema
        # internals.
        raise HTTPException(
            status_code=502,
            detail="Couldn't record feedback right now. Try again in a moment.",
        ) from error


@router.get("/quota")
def get_workspace_quota_route(auth_tokens=Depends(get_optional_auth_tokens)):
    """Per-user quota snapshot for the workspace UI (Step 7b).

    Drives the Premium toggle's enabled / disabled state, the
    per-counter "X of Y remaining this month" indicators, and the
    upgrade CTA URL. Read-only — calling this endpoint never
    increments a counter, never writes to Supabase, never burns
    quota credit. Safe to call on every workspace mount and after
    every workflow run, which the frontend does to keep the
    indicators in sync with the actual backend state.

    Anonymous callers get a 401 — the snapshot only makes sense for
    an authenticated user and we don't want to leak per-tier cap
    numbers on an unauthenticated probe. The frontend's API client
    handles 401 by prompting re-auth and skipping the quota render.
    """
    access_token, refresh_token = auth_tokens
    try:
        return get_workspace_quota_snapshot(
            access_token=access_token or "",
            refresh_token=refresh_token or "",
        )
    except WorkspaceQuotaAuthRequired:
        # The exception's message is already user-facing, but the
        # error_messages lint specifically forbids `str(exc)` as a
        # detail source (it allows an exception's raw repr to leak
        # if a future refactor changes the type). Use a fixed string
        # literal so the lint stays clean. Matches the message text
        # WorkspaceQuotaAuthRequired itself uses at both raise sites.
        raise HTTPException(
            status_code=401,
            detail="Sign in to view your workspace quota.",
        )
    except AppError as error:
        _raise_http_error(error)


@router.get(
    "/analyze-jobs/{job_id}",
    response_model=WorkspaceAnalyzeJobStatusResponseModel,
)
def get_workspace_analysis_job_route(job_id: str):
    payload = get_workspace_analysis_job(job_id)
    if payload is None:
        # `_JOBS` is process-local, so a container restart mid-run drops
        # the job state permanently. The frontend polling hook surfaces
        # `detail` directly to the user, so spell out the cause + the
        # recovery action instead of a bare "not found".
        raise HTTPException(
            status_code=404,
            detail=(
                "This workflow run is no longer available — the server may "
                "have restarted while it was running. Please run the workflow "
                "again."
            ),
        )
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
            workspace_state=(
                payload.workspace_state.model_dump()
                if payload.workspace_state
                else None
            ),
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

    The quota gate (assistant_turns) runs in
    ``prepare_stream_workspace_question`` BEFORE StreamingResponse is
    constructed. That keeps a quota rejection out of the SSE channel
    entirely — the global QuotaExceededError handler in backend.app
    converts it to the canonical 429 JSON the same way the sync
    surface does. Mixing a 429 into an open ``text/event-stream`` is
    not supported by the HTTP spec or by browsers, so the gate has to
    win the race against StreamingResponse's status-line commit.

    The ``X-Accel-Buffering: no`` header tells Caddy (and any other
    well-behaved reverse proxy) to flush each frame immediately
    instead of buffering the response. The Caddyfile also sets
    ``flush_interval -1`` for belt-and-braces.
    """
    access_token, refresh_token = auth_tokens
    prepared = prepare_stream_workspace_question(
        access_token=access_token or "",
        refresh_token=refresh_token or "",
    )
    return StreamingResponse(
        stream_workspace_question(
            question=payload.question,
            current_page=payload.current_page,
            workspace_state=(
                payload.workspace_state.model_dump()
                if payload.workspace_state
                else None
            ),
            workspace_snapshot=payload.workspace_snapshot,
            history=[item.model_dump() for item in payload.history],
            prepared=prepared,
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
            cover_letter_theme=payload.cover_letter_theme,
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
            cover_letter_theme=payload.cover_letter_theme,
        )
    except AppError as error:
        _raise_http_error(error)
