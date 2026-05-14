from __future__ import annotations

import base64
import json
import logging
from dataclasses import asdict, is_dataclass
from io import BytesIO
from types import SimpleNamespace
from typing import Any, Iterable

from src.agents.orchestrator import ApplicationOrchestrator
from src.assistant_service import AssistantService
from src.errors import AppError
from src.logging_utils import get_logger, log_event
from src.cover_letter_builder import build_cover_letter_artifact
from src.config import assisted_workflow_requires_login
from src.errors import InputValidationError
from src.openai_service import OpenAIService
from src.parsers.jd import parse_jd_text
from src.parsers.resume import parse_resume_document
from src.resume_builder import build_tailored_resume_artifact
from src.schemas import AssistantResponse, ResumeDocument
from src.services.fit_service import build_fit_analysis
from src.services.jd_summary_service import generate_job_summary_view
from src.services.job_service import (
    build_job_description_from_text,
    build_job_description_from_text_auto,
)
from src.services.profile_service import (
    build_candidate_profile_from_resume_auto,
)
from src.services.tailoring_service import build_tailored_resume_draft
from backend import quota
from backend.services.auth_session_service import (
    build_openai_service_for_context,
    resolve_authenticated_context,
)
from backend.tiers import resolve_user_tier


_QUOTA_LOGGER = get_logger("backend.services.workspace_service.quota")


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
    candidate_profile = build_candidate_profile_from_resume_auto(resume_document)
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
    # Production parsing path: LLM source-of-truth with deterministic
    # fallback. Same architecture we use for resume parsing.
    job_description = build_job_description_from_text_auto(job_description_text)
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
    premium: bool = False,
    access_token: str = "",
    refresh_token: str = "",
    progress_callback=None,
):
    """Build a tailored application bundle for a single (resume, JD) pair.

    Quota gate (Step 3 of tier-enforcement):
      * For authenticated users, the gate resolves the user's tier via
        `resolve_user_tier` and atomically increments either
        `tailored_applications` (premium=False) or
        `premium_applications` (premium=True) BEFORE the workflow runs.
        Burning the credit up-front means concurrent /workspace/analyze
        calls from the same user can't both squeeze past the cap.
      * If the workflow then raises, we refund the increment so a
        transient orchestrator failure doesn't cost the user a credit.
        Refunding only after a successful increment is critical -- if
        the increment itself raised QuotaExceededError, no row was
        written and the refund must be skipped (the brief calls this
        out explicitly).
      * For anonymous users the gate is bypassed because there's no
        stable user_id to attribute the increment to. The Free-tier
        guard against premium=True still fires (we resolve the tier
        as "free" for the synthetic anonymous context, and the
        QuotaExceededError carries the "Pro+ only" copy) so anonymous
        callers can't slip through the premium model surface.

    Anonymous + premium=True is rejected by raising a QuotaExceededError
    with cap=0; the FastAPI handler converts it to the standard 429
    payload so the frontend renders the same upgrade nudge.
    """
    resume_document = _build_resume_document(
        resume_text=resume_text,
        resume_filetype=resume_filetype,
        resume_source=resume_source,
    )

    auth_context = None
    if access_token and refresh_token:
        auth_context = resolve_authenticated_context(
            access_token=access_token,
            refresh_token=refresh_token,
        )

    # Quota gate. Runs BEFORE expensive work (orchestrator, OpenAI
    # calls, artifact rendering) so a rejection is cheap. The gate is
    # the ONLY place that decides per-tier limits -- per the brief,
    # no scattered `if tier == "free"` checks live downstream.
    counter_name = "premium_applications" if premium else "tailored_applications"
    tier = resolve_user_tier(
        auth_context.app_user if auth_context is not None else None
    )
    quota_user_id = (
        auth_context.app_user.id if auth_context is not None else ""
    )
    quota_consumed = False
    if quota_user_id:
        # Authenticated path: real user_id, real Supabase row. Raises
        # QuotaExceededError on cap breach; the route's global handler
        # converts that to 429 with the canonical payload.
        quota.check_and_increment(counter_name, quota_user_id, tier)
        quota_consumed = True
    elif premium:
        # Anonymous + premium=True: resolve tier as free (already
        # done) and surface the same Pro+ rejection message a
        # signed-in free user would see. We construct the error
        # directly rather than calling check_and_increment because
        # the helper requires a user_id; the user-facing 429 looks
        # identical either way.
        from backend.tiers import TIER_CAPS
        from src.errors import QuotaExceededError

        raise QuotaExceededError(
            "Premium applications are a Pro+ feature. Sign in and upgrade "
            "to run premium tailoring for this job.",
            counter=counter_name,
            current=0,
            cap=TIER_CAPS[tier][counter_name],
            reset_period=quota.current_period_key(),
            tier=tier,
        )

    try:
        candidate_profile = build_candidate_profile_from_resume_auto(resume_document)
        job_description = _enrich_job_description_from_imported_posting(
            build_job_description_from_text_auto(job_description_text),
            imported_job_posting,
        )
        fit_analysis = build_fit_analysis(candidate_profile, job_description)
        tailored_draft = build_tailored_resume_draft(
            candidate_profile,
            job_description,
            fit_analysis,
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
                progress_callback=progress_callback,
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
    except BaseException:
        # Refund on failure. Only runs when the increment actually
        # consumed a credit -- if the quota gate above raised
        # QuotaExceededError, no row was written and `quota_consumed`
        # is still False, so we don't accidentally decrement somebody
        # else's count.
        #
        # Use BaseException so SystemExit / KeyboardInterrupt in tests
        # also refund cleanly. The refund itself is best-effort and
        # logs on its own internal failure, so the original exception
        # is always the one that surfaces.
        if quota_consumed:
            try:
                quota.refund(counter_name, quota_user_id, tier)
            except Exception:  # noqa: BLE001 - refund is best-effort
                log_event(
                    _QUOTA_LOGGER,
                    logging.WARNING,
                    "workspace_quota_refund_failed",
                    "Refund after workflow failure raised; the user's quota "
                    "credit was not restored. The original workflow error is "
                    "the one that will surface to the client.",
                    counter=counter_name,
                    user_id=quota_user_id,
                    tier=tier,
                )
        raise


def answer_workspace_question(
    *,
    question: str,
    current_page: str,
    workspace_state: dict[str, Any] | None = None,
    workspace_snapshot: dict[str, Any] | None,
    history: list[dict[str, str]] | None,
    access_token: str = "",
    refresh_token: str = "",
):
    workflow_view_model = None
    artifact = None
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
        app_context.update(
            {
                "has_resume": bool(workspace_snapshot.get("candidate_profile")),
                "has_job_description": bool(workspace_snapshot.get("job_description")),
                "has_tailored_resume": artifact is not None,
                "has_cover_letter": bool(artifacts.get("cover_letter")),
            }
        )

    # Merge the live workspace-state projection (small, sent every
    # turn) so the LLM sees pre-analysis context too. workspace_state
    # is authoritative for has_resume/has_jd flags — the snapshot
    # block above only fires when an analysis has run, but the user
    # might have a parsed resume + JD without having run analysis.
    if workspace_state:
        app_context["workspace_state"] = workspace_state
        app_context.setdefault("has_resume", bool(workspace_state.get("has_resume")))
        app_context.setdefault(
            "has_job_description", bool(workspace_state.get("has_jd"))
        )
        # If snapshot didn't fire above but workspace_state says so,
        # still expose the flags (overriding the False defaults).
        if workspace_state.get("has_resume"):
            app_context["has_resume"] = True
        if workspace_state.get("has_jd"):
            app_context["has_job_description"] = True

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
        artifact=artifact,
        history=compact_history,
        app_context=app_context,
    )
    return _serialize(response)


_STREAM_LOGGER = get_logger("backend.services.workspace_service.stream")


def _sse_event(event: str, data: dict[str, Any]) -> str:
    """Format a Server-Sent Events frame.

    SSE expects event/data lines terminated by ``\\n`` and the frame
    delimited by a blank line (``\\n\\n``). The frontend splits on the
    blank-line delimiter, so emitting it consistently here matters.
    """
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _compute_assistant_sources(
    *,
    current_page: str | None,
    workspace_snapshot: dict[str, Any] | None,
) -> list[str]:
    """Pick the page/artifact labels that this answer can plausibly
    reference, based on the snapshot alone.

    Streaming pushes a ``meta`` event with sources before the LLM has
    produced any text, so sources have to be deterministic — the
    non-streaming path used to ask the LLM to choose them. The list
    here mirrors the labels the deterministic fallback responses use
    in ``AssistantService._fallback_*``, capped at 4 to match the
    non-streaming response shape.
    """
    sources: list[str] = []
    page_label = str(current_page or "").strip()
    if page_label:
        sources.append(page_label)
    snapshot = workspace_snapshot or {}
    artifacts = (snapshot.get("artifacts") or {}) if isinstance(snapshot, dict) else {}
    if isinstance(snapshot, dict):
        if snapshot.get("candidate_profile"):
            sources.append("Upload Resume")
        if snapshot.get("job_description"):
            sources.append("Manual JD Input")
        if snapshot.get("fit_analysis"):
            sources.append("Readiness Snapshot")
    if isinstance(artifacts, dict):
        if artifacts.get("tailored_resume"):
            sources.append("Tailored Resume Draft")
        if artifacts.get("cover_letter"):
            sources.append("Cover Letter")
    seen: set[str] = set()
    deduped: list[str] = []
    for label in sources:
        if label in seen:
            continue
        seen.add(label)
        deduped.append(label)
    return deduped[:4]


def stream_workspace_question(
    *,
    question: str,
    current_page: str,
    workspace_state: dict[str, Any] | None = None,
    workspace_snapshot: dict[str, Any] | None,
    history: list[dict[str, str]] | None,
    access_token: str = "",
    refresh_token: str = "",
) -> Iterable[str]:
    """Generator yielding SSE frames for the assistant streaming
    endpoint.

    Event order on the happy path: ``meta`` → ``delta``... → ``done``.

    On error after ``meta`` has been emitted: ``error`` → ``done``. The
    frontend is expected to close the stream on either ``done`` or
    ``error``.

    A ``followups`` event used to sit between the last ``delta`` and
    ``done``, but the suggested-follow-up panel was removed from the
    UI as a deliberate product call (commit 9138ead) and the wire
    event was dead code in both directions, so it was dropped here.
    Re-add it alongside any UI re-introduction.
    """
    workflow_view_model = None
    artifact = None
    app_context: dict[str, Any] = {
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
        app_context.update(
            {
                "has_resume": bool(workspace_snapshot.get("candidate_profile")),
                "has_job_description": bool(workspace_snapshot.get("job_description")),
                "has_tailored_resume": artifact is not None,
                "has_cover_letter": bool(artifacts.get("cover_letter")),
            }
        )

    # Same merge as in answer_workspace_question — fold the live
    # workspace-state projection into app_context so the LLM's
    # system prompt sees pre-analysis state too.
    if workspace_state:
        app_context["workspace_state"] = workspace_state
        if workspace_state.get("has_resume"):
            app_context["has_resume"] = True
        if workspace_state.get("has_jd"):
            app_context["has_job_description"] = True

    compact_history = [
        SimpleNamespace(
            question=str(item.get("question", "") or "").strip(),
            response=SimpleNamespace(answer=str(item.get("answer", "") or "").strip()),
        )
        for item in list(history or [])
        if str(item.get("question", "") or "").strip()
        and str(item.get("answer", "") or "").strip()
    ]

    sources = _compute_assistant_sources(
        current_page=current_page,
        workspace_snapshot=workspace_snapshot,
    )

    # Emit `meta` first so the UI can render the source chip row
    # before any answer text starts arriving.
    yield _sse_event("meta", {"sources": sources})

    openai_service = None
    if access_token and refresh_token:
        try:
            auth_context = resolve_authenticated_context(
                access_token=access_token,
                refresh_token=refresh_token,
            )
            openai_service, _ = build_openai_service_for_context(auth_context)
        except AppError as auth_exc:
            log_event(
                _STREAM_LOGGER,
                logging.WARNING,
                "assistant_stream_auth_failed",
                "Auth resolution failed for streaming assistant — falling back to anonymous deterministic path.",
                error_message=auth_exc.user_message,
                details=auth_exc.details,
            )
            openai_service = None

    assistant = AssistantService(openai_service=openai_service)
    try:
        produced_any = False
        for chunk in assistant.stream_answer(
            question,
            current_page=current_page,
            workflow_view_model=workflow_view_model,
            artifact=artifact,
            history=compact_history,
            app_context=app_context,
        ):
            text = str(chunk or "")
            if not text:
                continue
            produced_any = True
            yield _sse_event("delta", {"text": text})
        if not produced_any:
            # Even the deterministic fallback produced nothing — emit a
            # safe note so the UI doesn't render an empty bubble.
            yield _sse_event(
                "delta",
                {
                    "text": (
                        "The assistant could not produce a response just now. "
                        "Please try again or rephrase the question."
                    )
                },
            )
    except AppError as exc:
        log_event(
            _STREAM_LOGGER,
            logging.WARNING,
            "assistant_stream_app_error",
            "Streaming assistant raised an AppError.",
            error_message=exc.user_message,
            details=exc.details,
        )
        yield _sse_event("error", {"detail": exc.user_message})
    except Exception as exc:  # noqa: BLE001 - boundary for streaming surface
        log_event(
            _STREAM_LOGGER,
            logging.ERROR,
            "assistant_stream_unexpected_error",
            "Streaming assistant raised an unexpected error.",
            error_type=type(exc).__name__,
            details=str(exc),
        )
        yield _sse_event(
            "error",
            {"detail": "The assistant stream failed. Please try again."},
        )
    finally:
        yield _sse_event("done", {})
