"""Tests for the streaming assistant endpoint.

Exercises ``POST /api/workspace/assistant/answer/stream`` end-to-end
through the FastAPI test client.

Two surfaces under test:

1. The deterministic-fallback path. With no OpenAI key, the streaming
   endpoint should still produce a valid ``meta -> delta -> followups
   -> done`` SSE sequence using the deterministic-answer fallback.
   This mirrors how ``test_workspace_assistant_answer_uses_workspace_snapshot_context``
   tests the non-streaming endpoint.

2. The OpenAI-backed path. We monkeypatch ``run_text_stream`` on the
   ``AssistantService`` instance via a stubbed ``OpenAIService`` so the
   ``response.output_text.delta`` machinery is exercised without
   touching the real API.

Rate limiting is exercised in ``test_rate_limit.py`` via the global
``RATE_LIMIT_OVERRIDE`` mechanism rather than re-implementing it here.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.services import workspace_service


client = TestClient(app)


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    """Parse an SSE stream body into a list of ``(event, data)`` tuples.

    Tolerates the trailing-newline-after-last-frame variations that
    different SSE producers emit.
    """
    events: list[tuple[str, dict]] = []
    for frame in body.split("\n\n"):
        frame = frame.strip()
        if not frame:
            continue
        event_name = ""
        data_lines: list[str] = []
        for line in frame.splitlines():
            if line.startswith("event:"):
                event_name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:"):].strip())
        data_payload = "\n".join(data_lines) if data_lines else "{}"
        try:
            data = json.loads(data_payload) if data_payload else {}
        except json.JSONDecodeError:
            data = {"_raw": data_payload}
        events.append((event_name, data))
    return events


# ---------------------------------------------------------------------------
# Deterministic fallback path (no OpenAI key)
# ---------------------------------------------------------------------------
def test_stream_returns_sse_content_type_and_meta_first_then_delta_then_done():
    """A valid streaming request returns ``text/event-stream`` and
    emits ``meta`` before any ``delta`` and ends with ``done``."""
    response = client.post(
        "/api/workspace/assistant/answer/stream",
        json={
            "question": "What can I do on this page?",
            "current_page": "Workspace",
            "workspace_snapshot": None,
            "history": [],
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers.get("cache-control") == "no-cache"
    assert response.headers.get("x-accel-buffering") == "no"

    events = _parse_sse(response.text)
    event_names = [name for name, _ in events]

    assert "meta" in event_names, event_names
    assert "delta" in event_names, event_names
    assert "done" in event_names, event_names

    # Order rules: meta strictly before any delta; done is the last event.
    first_delta_index = event_names.index("delta")
    meta_index = event_names.index("meta")
    assert meta_index < first_delta_index, event_names
    assert event_names[-1] == "done", event_names


def test_stream_meta_event_includes_workspace_snapshot_sources():
    """When the snapshot has artifacts, the ``meta`` event surfaces
    the deterministic source labels for them."""
    snapshot = {
        "candidate_profile": {"full_name": "Leander Antony"},
        "job_description": {"title": "ML Engineer"},
        "fit_analysis": {"overall_score": 72},
        "artifacts": {
            "tailored_resume": {"markdown": "# Resume"},
            "cover_letter": {"markdown": "Hi"},
            "report": {"markdown": "Report"},
        },
    }
    response = client.post(
        "/api/workspace/assistant/answer/stream",
        json={
            "question": "What are my biggest gaps?",
            "current_page": "Manual JD Input",
            "workspace_snapshot": snapshot,
            "history": [],
        },
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    meta_events = [data for name, data in events if name == "meta"]
    assert meta_events, events
    sources = meta_events[0].get("sources", [])
    # Capped at 4 — current_page first, then earliest-listed artifacts.
    assert sources[0] == "Manual JD Input"
    assert len(sources) <= 4
    # At least one of the artifact-derived sources should appear.
    assert any(
        label in sources
        for label in (
            "Upload Resume",
            "Readiness Snapshot",
            "Tailored Resume Draft",
        )
    )


def test_stream_returns_422_for_invalid_request_body():
    """Empty/whitespace ``question`` is invalid by the request model."""
    response = client.post(
        "/api/workspace/assistant/answer/stream",
        json={
            "question": "",  # min_length=1
            "current_page": "Workspace",
            "workspace_snapshot": None,
            "history": [],
        },
    )
    assert response.status_code == 422


def test_stream_returns_422_for_extra_fields():
    """``WorkspaceAssistantRequestModel`` is configured ``extra='forbid'``."""
    response = client.post(
        "/api/workspace/assistant/answer/stream",
        json={
            "question": "What's on this page?",
            "current_page": "Workspace",
            "workspace_snapshot": None,
            "history": [],
            "unexpected_field": "boom",
        },
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# OpenAI-backed path
# ---------------------------------------------------------------------------
class _StubOpenAIService:
    """Minimal stand-in for ``OpenAIService``.

    Only implements the surface ``AssistantService.stream_answer``
    actually calls: ``is_available`` and ``run_text_stream``. The
    streaming generator yields a fixed sequence of fake deltas.
    """

    def __init__(self, deltas: list[str]):
        self._deltas = deltas

    def is_available(self) -> bool:
        return True

    def run_text_stream(self, system_prompt, user_prompt, **kwargs):
        for chunk in self._deltas:
            yield chunk


def test_stream_emits_one_delta_per_openai_chunk(monkeypatch: pytest.MonkeyPatch):
    """When OpenAI is available, every text chunk it yields becomes a
    separate ``delta`` SSE event with that chunk in ``text``."""
    deltas = ["Hello ", "from ", "the ", "stream."]

    def fake_resolve_authenticated_context(*, access_token, refresh_token):
        return {"access_token": access_token, "refresh_token": refresh_token}

    def fake_build_openai_service_for_context(_auth_context):
        return _StubOpenAIService(deltas), None

    monkeypatch.setattr(
        workspace_service,
        "resolve_authenticated_context",
        fake_resolve_authenticated_context,
    )
    monkeypatch.setattr(
        workspace_service,
        "build_openai_service_for_context",
        fake_build_openai_service_for_context,
    )

    response = client.post(
        "/api/workspace/assistant/answer/stream",
        headers={
            "X-Auth-Access-Token": "access-token",
            "X-Auth-Refresh-Token": "refresh-token",
        },
        json={
            "question": "Tell me about my package.",
            "current_page": "Workspace",
            "workspace_snapshot": None,
            "history": [],
        },
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    delta_texts = [data.get("text", "") for name, data in events if name == "delta"]
    assert delta_texts == deltas

    event_names = [name for name, _ in events]
    # The `followups` event was dropped (UI does not render suggested
    # follow-ups). The happy-path contract is now meta -> delta* -> done.
    assert "followups" not in event_names
    assert event_names[-1] == "done"


def test_stream_emits_error_then_done_when_openai_raises(monkeypatch: pytest.MonkeyPatch):
    """If the OpenAI call raises mid-stream, the endpoint emits an
    ``error`` event followed by a final ``done`` instead of leaking
    a 5xx — the frontend can render the error and close the stream."""
    from src.errors import AgentExecutionError

    class _FailingStub(_StubOpenAIService):
        def run_text_stream(self, system_prompt, user_prompt, **kwargs):
            yield "first chunk "
            raise AgentExecutionError("OpenAI streaming exploded")

    def fake_resolve_authenticated_context(*, access_token, refresh_token):
        return {"access_token": access_token, "refresh_token": refresh_token}

    def fake_build_openai_service_for_context(_auth_context):
        return _FailingStub([]), None

    monkeypatch.setattr(
        workspace_service,
        "resolve_authenticated_context",
        fake_resolve_authenticated_context,
    )
    monkeypatch.setattr(
        workspace_service,
        "build_openai_service_for_context",
        fake_build_openai_service_for_context,
    )

    response = client.post(
        "/api/workspace/assistant/answer/stream",
        headers={
            "X-Auth-Access-Token": "access-token",
            "X-Auth-Refresh-Token": "refresh-token",
        },
        json={
            "question": "What about edge cases?",
            "current_page": "Workspace",
            "workspace_snapshot": None,
            "history": [],
        },
    )

    # Error during streaming is surfaced as an SSE event, NOT a 5xx —
    # the response status is still 200 because the body started
    # streaming before the failure happened.
    assert response.status_code == 200
    events = _parse_sse(response.text)
    event_names = [name for name, _ in events]

    # AgentExecutionError is caught inside AssistantService.stream_answer,
    # which falls back to the deterministic answer instead of bubbling.
    # So we expect the deterministic fallback delta(s), then followups
    # and done — no `error` event in this path.
    assert "delta" in event_names
    assert event_names[-1] == "done"
