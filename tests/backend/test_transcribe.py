"""Voice input transcription route + service tests.

Pins the contract the frontend's VoiceInputButton calls into:

  * Authenticated POST /workspace/transcribe with a webm/mp4/wav blob
    returns ``{"text": str, "duration_seconds": float}``.
  * Anonymous callers get a 401 — no synthetic transcript fallback so
    the frontend can prompt re-auth uniformly with the rest of the
    workspace surfaces.
  * Cost trace row written to ``aijobagent_run_traces`` with
    ``task_name="transcribe"`` so the nightly tier-margin report can
    break Whisper out as its own line item alongside the chat models.
  * Empty audio + oversize audio are rejected with clean 400/413 — the
    frontend renders the detail message verbatim, so the copy has to
    stay user-facing.
  * Wrong MIME type rejected — locking the allowed set keeps random
    binaries (PDFs, zips) from costing $0.006/MB through the Whisper
    bridge.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import run_traces
from backend.routers.workspace import router as workspace_router
from backend.services import transcribe_service


# ────────────────────────────────────────────────────────────────────
# App + fakes
# ────────────────────────────────────────────────────────────────────


@pytest.fixture
def app_client(monkeypatch):
    """Minimal FastAPI app that mounts the workspace router under /api.

    The full backend.app would pull in CORS, the global QuotaExceededError
    handler, the rate-limit middleware, etc. None of that is needed to
    exercise this single route — and keeping it minimal makes the test
    failure messages local to the route we're testing."""
    app = FastAPI()
    # Mount under /api so the route shape matches what the frontend
    # actually calls (`/api/workspace/transcribe`).
    app.include_router(workspace_router, prefix="/api")
    return TestClient(app)


class _FakeAppUser:
    def __init__(self, user_id: str = "user-test"):
        self.id = user_id


class _FakeAuthContext:
    def __init__(self, user_id: str = "user-test"):
        self.app_user = _FakeAppUser(user_id)


@pytest.fixture
def fake_auth(monkeypatch):
    """Patch ``resolve_authenticated_context`` so the route doesn't
    need a real Supabase round-trip. Returns the context so individual
    tests can read ``app_user.id``."""
    context = _FakeAuthContext()

    def _resolve(*, access_token, refresh_token):
        if not (access_token and refresh_token):
            raise RuntimeError("test stub: tokens missing")
        return context

    monkeypatch.setattr(
        transcribe_service,
        "resolve_authenticated_context",
        _resolve,
    )
    return context


@pytest.fixture
def fake_openai_transcription(monkeypatch):
    """Return a fake OpenAI SDK client so we never call the real API.

    The returned ``captured`` list collects each call's kwargs so the
    test can assert the file tuple shape / model id we sent."""
    captured: list[dict] = []

    class _FakeTranscriptions:
        @staticmethod
        def create(**kwargs):
            captured.append(dict(kwargs))
            return SimpleNamespace(
                text="Hello, this is a sample transcription.",
                duration=12.34,
            )

    class _FakeAudio:
        transcriptions = _FakeTranscriptions

    class _FakeClient:
        audio = _FakeAudio()

    monkeypatch.setattr(
        transcribe_service,
        "_resolve_openai_client",
        lambda: _FakeClient(),
    )
    return captured


@pytest.fixture(autouse=True)
def _fresh_traces_store(monkeypatch):
    """Each test starts with an empty trace store so we can assert
    exactly one row was added by the call under test."""

    class _NeverConfigured:
        def is_configured(self) -> bool:
            return False

    monkeypatch.setattr(run_traces, "_SUPABASE_BACKEND", _NeverConfigured())
    run_traces.reset_in_memory_backend()
    yield
    run_traces.reset_in_memory_backend()


# ────────────────────────────────────────────────────────────────────
# Route behavior
# ────────────────────────────────────────────────────────────────────


def test_transcribe_route_returns_text_and_duration(
    app_client, fake_auth, fake_openai_transcription
):
    """The happy path: authenticated POST with a webm blob returns
    the transcript + duration."""
    response = app_client.post(
        "/api/workspace/transcribe",
        files={"file": ("voice.webm", b"\x00\x01\x02fake-audio", "audio/webm")},
        cookies={
            "ja_access_token": "access-token-value",
            "ja_refresh_token": "refresh-token-value",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["text"] == "Hello, this is a sample transcription."
    assert payload["duration_seconds"] == pytest.approx(12.34, rel=1e-3)
    # Whisper got the file with the right model id and MIME type.
    assert len(fake_openai_transcription) == 1
    call_kwargs = fake_openai_transcription[0]
    assert call_kwargs["model"] == "whisper-1"
    file_name, _stream, file_mime = call_kwargs["file"]
    assert file_name.endswith(".webm")
    assert file_mime == "audio/webm"


def test_transcribe_route_requires_auth(app_client):
    """No cookies → 401. We never call Whisper for an anonymous user
    because there's no user_id to attribute the trace to."""
    response = app_client.post(
        "/api/workspace/transcribe",
        files={"file": ("voice.webm", b"\x00fake", "audio/webm")},
    )
    assert response.status_code == 401
    assert "Sign in" in response.json()["detail"]


def test_transcribe_route_records_cost_trace(
    app_client, fake_auth, fake_openai_transcription
):
    """Each successful call writes one row to aijobagent_run_traces.

    Validates the row has:
      * task_name="transcribe" so the nightly report's GROUP BY breaks
        Whisper out as its own line item
      * cost_usd computed from $0.006/min × duration / 60
      * user_id attribution from the auth context
    """
    response = app_client.post(
        "/api/workspace/transcribe",
        files={"file": ("voice.webm", b"\x00fake", "audio/webm")},
        cookies={
            "ja_access_token": "access-token-value",
            "ja_refresh_token": "refresh-token-value",
        },
    )
    assert response.status_code == 200
    rows = run_traces.in_memory_rows()
    assert len(rows) == 1
    row = rows[0]
    assert row["task_name"] == "transcribe"
    assert row["model_name"] == "whisper-1"
    assert row["user_id"] == "user-test"
    # 12.34s × $0.006/60 = $0.001234, rounded to 6 decimals.
    expected_cost = round(0.006 * (12.34 / 60.0), 6)
    assert row["cost_usd"] == pytest.approx(expected_cost, rel=1e-3)
    assert row["success"] is True


def test_transcribe_route_rejects_empty_audio(
    app_client, fake_auth, fake_openai_transcription
):
    """A zero-byte upload is a client bug (no mic permission, or the
    recorder fired stop with nothing buffered). Reject early so we
    don't burn a Whisper call on silence."""
    response = app_client.post(
        "/api/workspace/transcribe",
        files={"file": ("voice.webm", b"", "audio/webm")},
        cookies={
            "ja_access_token": "access-token-value",
            "ja_refresh_token": "refresh-token-value",
        },
    )
    assert response.status_code == 400
    assert "No audio" in response.json()["detail"]
    # And no Whisper call should have happened.
    assert len(fake_openai_transcription) == 0


def test_transcribe_route_rejects_oversize_audio(
    app_client, fake_auth, fake_openai_transcription
):
    """OpenAI's hard limit is 25 MB. We reject locally with 413 so the
    user gets a friendly message instead of OpenAI's generic error
    surfaced through the agent path."""
    oversize_payload = b"\x00" * (transcribe_service.MAX_AUDIO_BYTES + 1)
    response = app_client.post(
        "/api/workspace/transcribe",
        files={"file": ("voice.webm", oversize_payload, "audio/webm")},
        cookies={
            "ja_access_token": "access-token-value",
            "ja_refresh_token": "refresh-token-value",
        },
    )
    assert response.status_code == 413
    assert "25 MB" in response.json()["detail"]
    assert len(fake_openai_transcription) == 0


def test_transcribe_route_rejects_unsupported_mime_type(
    app_client, fake_auth, fake_openai_transcription
):
    """An arbitrary binary (a PDF or zip) shouldn't make it through to
    Whisper. The allowed-set check keeps the surface tight."""
    response = app_client.post(
        "/api/workspace/transcribe",
        files={"file": ("file.pdf", b"%PDF-1.4 fake", "application/pdf")},
        cookies={
            "ja_access_token": "access-token-value",
            "ja_refresh_token": "refresh-token-value",
        },
    )
    assert response.status_code == 400
    assert "Unsupported" in response.json()["detail"]
    assert len(fake_openai_transcription) == 0


def test_transcribe_service_accepts_mp4_blob(fake_auth, fake_openai_transcription):
    """Safari's MediaRecorder defaults to audio/mp4 — make sure that
    container is in the allowed set, not just Chrome's webm."""
    response = transcribe_service.transcribe_audio(
        audio_bytes=b"\x00\x01fake-mp4-payload",
        content_type="audio/mp4",
        access_token="access-token-value",
        refresh_token="refresh-token-value",
    )
    assert response["text"]  # non-empty
    # Filename suffix mirrors the MIME container — Whisper needs the
    # hint to pick the right demuxer.
    file_tuple = fake_openai_transcription[0]["file"]
    assert file_tuple[0].endswith(".mp4")


def test_transcribe_records_failed_trace_when_whisper_raises(
    app_client, fake_auth, monkeypatch
):
    """A Whisper outage shouldn't lose the trace — we still want
    error-rate visibility in the nightly report. The cost on a failed
    call is 0 (no duration), success=False, and the route surfaces
    400 via the AgentExecutionError → AppError chain."""
    def _explode(**_kwargs):
        raise RuntimeError("simulated Whisper outage")

    class _ExplodingTranscriptions:
        create = staticmethod(_explode)

    class _ExplodingAudio:
        transcriptions = _ExplodingTranscriptions

    class _ExplodingClient:
        audio = _ExplodingAudio()

    monkeypatch.setattr(
        transcribe_service,
        "_resolve_openai_client",
        lambda: _ExplodingClient(),
    )

    response = app_client.post(
        "/api/workspace/transcribe",
        files={"file": ("voice.webm", b"\x00fake", "audio/webm")},
        cookies={
            "ja_access_token": "access-token-value",
            "ja_refresh_token": "refresh-token-value",
        },
    )
    assert response.status_code == 400
    rows = run_traces.in_memory_rows()
    assert len(rows) == 1
    assert rows[0]["success"] is False
    assert rows[0]["task_name"] == "transcribe"
    assert rows[0]["cost_usd"] == 0.0
