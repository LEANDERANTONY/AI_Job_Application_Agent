"""Voice input transcription service backed by OpenAI Whisper.

The Resume Builder chat input is the flagship surface for this — users
speak naturally for 30s and get a rich answer they can review + submit,
instead of typing one-liners because typing is annoying. Workspace
assistant chat is the secondary surface.

Pricing: ~$0.006/min for whisper-1. Cheap enough to give to every tier
without a counter; downstream caps (assistant_turns,
resume_builder_sessions) still bound the value the transcript flows
into. We record a trace row with task_name="transcribe" so the cost
shows up in the nightly tier-margin report alongside the agent calls.

Auth-required: anonymous callers get a 401 at the route layer. Without
auth we have no user_id to attribute the trace to, and the downstream
surfaces (resume builder, assistant) are already auth-gated.

Audio constraints:
  * MIME types accepted: audio/webm, audio/mp4, audio/wav, audio/mpeg,
    audio/m4a, audio/ogg. The MediaRecorder API on Chrome / Firefox
    defaults to webm; Safari to mp4. Anything else is rejected.
  * Size cap: 25 MB. That's also OpenAI's hard limit on a single
    transcription call; rejecting locally with a friendly error beats
    a cryptic OpenAI 413 surfacing through the agent error path.
  * Empty bodies (zero-length audio) are rejected — Whisper would
    happily charge a fractional cent for the call but the user gets
    nothing useful back, so we short-circuit.
"""
from __future__ import annotations

import io
import logging
from typing import Any

from backend import run_traces
from backend.services.auth_session_service import resolve_authenticated_context
from src.config import load_openai_key
from src.errors import AgentExecutionError, AppError, InputValidationError
from src.logging_utils import get_logger, log_event
from src.openai_service import compute_call_cost_usd


LOGGER = get_logger(__name__)


# Whisper-1 hard limit; OpenAI rejects > 25 MB with a 413 of its own.
# We reject locally with a friendlier error message so the user can act
# (re-record shorter / use a quieter format) instead of staring at a
# generic "request failed" toast.
MAX_AUDIO_BYTES = 25 * 1024 * 1024  # 25 MB

# Accept the MIME types MediaRecorder + common in-browser recorders
# actually emit. Tightening this set to a literal whitelist prevents a
# caller from uploading arbitrary binary (a PDF, a zip) that Whisper
# would patiently reject with a $0.006 charge anyway.
ALLOWED_MIME_TYPES = frozenset(
    {
        "audio/webm",
        "audio/webm;codecs=opus",
        "audio/mp4",
        "audio/m4a",
        "audio/x-m4a",
        "audio/mpeg",
        "audio/mp3",
        "audio/wav",
        "audio/x-wav",
        "audio/wave",
        "audio/ogg",
        "audio/ogg;codecs=opus",
    }
)


# Whisper pricing per minute (the only pricing model OpenAI uses for
# audio; differs from the per-token table used for the chat models).
# Source of truth for the trace row's cost_usd field. Update when
# OpenAI revises pricing.
WHISPER_USD_PER_MINUTE = 0.006


# Whisper-1 model id. Constant rather than env-var because the only
# alternative is whisper-large-v3 which is not API-exposed today.
WHISPER_MODEL = "whisper-1"


# Filename Whisper actually inspects to pick the demuxer. The extension
# must match the container; we synthesize one from the MIME type rather
# than trusting whatever the browser sent (Safari blob.name is empty).
_MIME_TO_EXTENSION = {
    "audio/webm": "webm",
    "audio/webm;codecs=opus": "webm",
    "audio/mp4": "mp4",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/ogg": "ogg",
    "audio/ogg;codecs=opus": "ogg",
}


def _normalize_mime(content_type: str) -> str:
    """Trim parameters, lowercase, strip whitespace.

    Browsers send `audio/webm;codecs=opus` and we want to match both
    the bare and the parameterized form. We keep the codecs suffix in
    ALLOWED_MIME_TYPES so the lookup is permissive without losing the
    container hint Whisper needs.
    """
    return str(content_type or "").strip().lower()


def _extension_for_mime(mime: str) -> str:
    """Pick the filename suffix Whisper inspects for demuxing.

    Falls back to ``webm`` for unknown-but-allowed types so Whisper has
    a hint; the allowed-set check has already guaranteed the type is
    valid before we reach this branch.
    """
    return _MIME_TO_EXTENSION.get(mime, "webm")


def _resolve_openai_client():
    """Return the OpenAI SDK client configured with the same API key as
    the chat surface.

    Local import so a unit test can monkeypatch the constructor without
    pulling the SDK into the import graph. Mirrors the lazy pattern in
    ``src.openai_service.OpenAIService.__init__``.
    """
    from openai import OpenAI

    api_key = load_openai_key(required=False)
    if not api_key:
        raise AgentExecutionError(
            "OpenAI is not configured; voice transcription is unavailable."
        )
    return OpenAI(api_key=api_key, timeout=60.0, max_retries=2)


def _record_transcribe_trace(
    *,
    user_id: str,
    duration_seconds: float,
    success: bool,
) -> None:
    """Persist one cost-trace row for this transcription call.

    Best-effort: any persistence failure is logged and swallowed.
    Mirrors ``OpenAIService._record_cost_trace`` so the nightly tier-
    margin report sees Whisper calls alongside the chat-model calls
    in the same table.

    We attribute the row with ``task_name="transcribe"`` and a
    ``model_name`` of ``whisper-1`` so the GROUP BY task_name aggregate
    in the report breaks Whisper out as its own line item. Tokens are
    zeroed because Whisper bills per second of audio, not per token —
    the cost_usd field carries the actual dollar amount.
    """
    cost_usd = round(WHISPER_USD_PER_MINUTE * (max(duration_seconds, 0.0) / 60.0), 6)
    try:
        run_traces.record_trace(
            task_name="transcribe",
            model_name=WHISPER_MODEL,
            prompt_tokens=0,
            completion_tokens=0,
            cost_usd=cost_usd,
            user_id=user_id or None,
            success=success,
        )
    except Exception as exc:  # noqa: BLE001 - best-effort
        log_event(
            LOGGER,
            logging.WARNING,
            "transcribe_cost_trace_persist_failed",
            "Whisper cost trace persistence failed.",
            error_type=type(exc).__name__,
            details=str(exc),
            user_id=user_id,
        )


def transcribe_audio(
    *,
    audio_bytes: bytes,
    content_type: str,
    access_token: str,
    refresh_token: str,
    openai_client: Any | None = None,
) -> dict[str, Any]:
    """Transcribe ``audio_bytes`` via the Whisper API.

    Auth is required: an anonymous caller raises ``InputValidationError``
    which the route turns into a 401. The same exception class is used
    by ``resolve_authenticated_context`` so the route's existing
    handler chain catches both surfaces uniformly.

    ``openai_client`` is the OpenAI SDK client. Tests inject a fake
    that exposes the same ``audio.transcriptions.create`` interface;
    production lets the helper construct one from the env-var key.

    Returns ``{"text": str, "duration_seconds": float}``. The duration
    is what Whisper reports back (response.duration when ``verbose_json``
    is requested) — falling back to 0.0 when the response shape skips
    it. The duration drives the cost trace row and the frontend's
    "transcribed 23 seconds of audio" affordance.
    """
    # ── Auth gate ─────────────────────────────────────────────────────
    if not (access_token and refresh_token):
        # Same exception class the rest of the service layer uses for
        # "you need to sign in" failures. The route translates to 401.
        raise InputValidationError(
            "Sign in with Google before transcribing voice input."
        )

    try:
        auth_context = resolve_authenticated_context(
            access_token=access_token,
            refresh_token=refresh_token,
        )
    except AppError:
        # Token validation failed — surface as auth required.
        raise InputValidationError(
            "Your session has expired. Sign in again before transcribing."
        )

    user_id = str(getattr(auth_context.app_user, "id", "") or "")

    # ── Input validation ──────────────────────────────────────────────
    if not audio_bytes:
        raise InputValidationError(
            "No audio data received. Try recording again."
        )
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise InputValidationError(
            "Audio exceeds the 25 MB limit. Try a shorter recording "
            "or a more compressed format."
        )

    normalized_mime = _normalize_mime(content_type)
    if normalized_mime not in ALLOWED_MIME_TYPES:
        raise InputValidationError(
            "Unsupported audio format. Use webm, mp4, m4a, mp3, wav, or ogg."
        )

    # ── Whisper call ──────────────────────────────────────────────────
    client = openai_client if openai_client is not None else _resolve_openai_client()

    extension = _extension_for_mime(normalized_mime)
    file_tuple = (f"voice.{extension}", io.BytesIO(audio_bytes), normalized_mime)

    log_event(
        LOGGER,
        logging.INFO,
        "transcribe_request_started",
        "Starting Whisper transcription request.",
        user_id=user_id,
        audio_bytes=len(audio_bytes),
        mime_type=normalized_mime,
        model=WHISPER_MODEL,
    )

    try:
        response = client.audio.transcriptions.create(
            model=WHISPER_MODEL,
            file=file_tuple,
            response_format="verbose_json",
        )
    except Exception as exc:  # noqa: BLE001 - boundary translation
        log_event(
            LOGGER,
            logging.ERROR,
            "transcribe_request_failed",
            "Whisper transcription request failed.",
            user_id=user_id,
            error_type=type(exc).__name__,
            details=str(exc),
        )
        # Record a failed trace too so the nightly report sees error
        # rates per task. Duration is unknown on failure so we record 0.
        _record_transcribe_trace(
            user_id=user_id,
            duration_seconds=0.0,
            success=False,
        )
        raise AgentExecutionError(
            "Voice transcription failed. Try recording again.",
            details=str(exc),
        ) from exc

    # The SDK returns either a dict-like (when response_format='json')
    # or an object with .text / .duration attributes (verbose_json).
    # Tolerate both for test injection convenience.
    text = ""
    duration = 0.0
    if isinstance(response, dict):
        text = str(response.get("text", "") or "").strip()
        duration = float(response.get("duration", 0.0) or 0.0)
    else:
        text = str(getattr(response, "text", "") or "").strip()
        duration = float(getattr(response, "duration", 0.0) or 0.0)

    log_event(
        LOGGER,
        logging.INFO,
        "transcribe_request_completed",
        "Whisper transcription request completed.",
        user_id=user_id,
        duration_seconds=duration,
        transcript_chars=len(text),
    )

    _record_transcribe_trace(
        user_id=user_id,
        duration_seconds=duration,
        success=True,
    )

    return {
        "text": text,
        "duration_seconds": round(duration, 3),
    }


__all__ = [
    "ALLOWED_MIME_TYPES",
    "MAX_AUDIO_BYTES",
    "WHISPER_MODEL",
    "WHISPER_USD_PER_MINUTE",
    "transcribe_audio",
]
