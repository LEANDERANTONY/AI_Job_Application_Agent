"""Online feedback route + service tests.

Pins the contract the frontend's FeedbackButtons component calls into:

  * Authenticated POST /workspace/feedback with a {surface, rating}
    body writes one row and echoes the persisted shape back.
  * Anonymous callers get 401 — no surreptitious anonymous feedback
    storage; the table's RLS policy requires user_id anyway.
  * The surface CHECK constraint is enforced at the Pydantic
    boundary, so a typo in the client fails as a 422 (not a 500 on
    the Postgres check).
  * trace_id is nullable + cleanup-resilient — the row survives even
    when the corresponding aijobagent_run_traces row is pruned.
  * Comment field is truncated at COMMENT_MAX_CHARS so a malicious
    1 GB body can't bloat the row + index.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers.workspace import router as workspace_router
from backend.services import feedback_service
from backend.services.feedback_service import (
    COMMENT_MAX_CHARS,
    InvalidFeedbackError,
    record_feedback,
)


# ────────────────────────────────────────────────────────────────────
# App + fakes
# ────────────────────────────────────────────────────────────────────


@pytest.fixture
def app_client(monkeypatch):
    """Minimal FastAPI app that mounts the workspace router under /api.

    Same shape as test_transcribe.py — keeps the test failure messages
    local to the route we're testing without pulling in the full
    backend.app stack."""
    app = FastAPI()
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
    """Patch ``resolve_authenticated_context`` in the workspace router
    so the route doesn't need a real Supabase round-trip."""
    context = _FakeAuthContext()
    import backend.routers.workspace as workspace_router_module

    def _resolve(*, access_token, refresh_token):
        if not (access_token and refresh_token):
            raise RuntimeError("test stub: tokens missing")
        return context

    monkeypatch.setattr(
        workspace_router_module,
        "resolve_authenticated_context",
        _resolve,
    )
    return context


@pytest.fixture(autouse=True)
def _fresh_feedback_store(monkeypatch):
    """Each test starts with an empty feedback store so we can assert
    exactly the rows the call under test added."""

    class _NeverConfigured:
        def is_configured(self) -> bool:
            return False

    monkeypatch.setattr(
        feedback_service, "_SUPABASE_BACKEND", _NeverConfigured()
    )
    feedback_service.reset_in_memory_backend()
    yield
    feedback_service.reset_in_memory_backend()


# ────────────────────────────────────────────────────────────────────
# Service layer
# ────────────────────────────────────────────────────────────────────


def test_record_feedback_writes_row_to_in_memory_backend():
    """Happy path: a valid call writes one row with the right shape."""
    response = record_feedback(
        user_id="user-abc",
        surface="tailored_resume",
        rating="up",
        trace_id="trace-uuid-123",
        comment="Nailed it",
    )
    assert response == {
        "status": "recorded",
        "surface": "tailored_resume",
        "rating": "up",
    }
    rows = feedback_service.in_memory_rows()
    assert len(rows) == 1
    row = rows[0]
    assert row["user_id"] == "user-abc"
    assert row["surface"] == "tailored_resume"
    assert row["rating"] == "up"
    assert row["trace_id"] == "trace-uuid-123"
    assert row["comment"] == "Nailed it"


def test_record_feedback_accepts_null_trace_id():
    """trace_id is nullable in the schema — cleanup-resilience means
    feedback survives even when the underlying run_trace row is gone."""
    record_feedback(
        user_id="user-abc",
        surface="resume_builder_session",
        rating="up",
    )
    rows = feedback_service.in_memory_rows()
    assert rows[0]["trace_id"] is None


def test_record_feedback_rejects_unknown_surface():
    """A typo in the surface value should fail fast — the SQL CHECK
    constraint would also catch this but we'd rather not round-trip
    bad data to Postgres."""
    with pytest.raises(InvalidFeedbackError):
        record_feedback(
            user_id="user-abc",
            surface="something_made_up",
            rating="up",
        )


def test_record_feedback_rejects_unknown_rating():
    """Only 'up' / 'down' are valid — the canonical product UX is two
    buttons, not a tri-state."""
    with pytest.raises(InvalidFeedbackError):
        record_feedback(
            user_id="user-abc",
            surface="tailored_resume",
            rating="meh",
        )


def test_record_feedback_truncates_long_comment():
    """A megabyte of comment text should not blow up the row + index.
    The service truncates at COMMENT_MAX_CHARS before insert."""
    long_comment = "x" * (COMMENT_MAX_CHARS + 100)
    record_feedback(
        user_id="user-abc",
        surface="tailored_resume",
        rating="up",
        comment=long_comment,
    )
    rows = feedback_service.in_memory_rows()
    assert len(rows[0]["comment"]) == COMMENT_MAX_CHARS


def test_record_feedback_requires_user_id():
    """Defense in depth: a route bug that passes user_id='' should be
    caught here too."""
    with pytest.raises(InvalidFeedbackError):
        record_feedback(
            user_id="",
            surface="tailored_resume",
            rating="up",
        )


# ────────────────────────────────────────────────────────────────────
# Route behavior
# ────────────────────────────────────────────────────────────────────


def test_feedback_route_writes_row_and_echoes_payload(app_client, fake_auth):
    """End-to-end happy path: authenticated POST writes a row and
    returns the persisted-shape echo so the frontend's optimistic UI
    can verify the surface + rating round-tripped."""
    response = app_client.post(
        "/api/workspace/feedback",
        json={
            "surface": "tailored_resume",
            "rating": "up",
            "trace_id": "trace-uuid-123",
            "comment": "Loved the bullets",
        },
        cookies={
            "ja_access_token": "access-token-value",
            "ja_refresh_token": "refresh-token-value",
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "status": "recorded",
        "surface": "tailored_resume",
        "rating": "up",
    }
    rows = feedback_service.in_memory_rows()
    assert len(rows) == 1
    assert rows[0]["user_id"] == "user-test"
    assert rows[0]["surface"] == "tailored_resume"
    assert rows[0]["rating"] == "up"
    assert rows[0]["comment"] == "Loved the bullets"


def test_feedback_route_requires_auth(app_client):
    """No cookies → 401. Mirrors /workspace/quota."""
    response = app_client.post(
        "/api/workspace/feedback",
        json={"surface": "tailored_resume", "rating": "up"},
    )
    assert response.status_code == 401


def test_feedback_route_rejects_invalid_surface(app_client, fake_auth):
    """Pydantic Literal rejects an unknown surface at the parse boundary
    so the route never hits the service layer. 422 (not 400) because
    that's FastAPI's canonical model-validation status."""
    response = app_client.post(
        "/api/workspace/feedback",
        json={"surface": "something_made_up", "rating": "up"},
        cookies={
            "ja_access_token": "access-token-value",
            "ja_refresh_token": "refresh-token-value",
        },
    )
    assert response.status_code == 422


def test_feedback_route_rejects_invalid_rating(app_client, fake_auth):
    """Same path as surface — Pydantic Literal handles it before the
    service gets a chance."""
    response = app_client.post(
        "/api/workspace/feedback",
        json={"surface": "tailored_resume", "rating": "lukewarm"},
        cookies={
            "ja_access_token": "access-token-value",
            "ja_refresh_token": "refresh-token-value",
        },
    )
    assert response.status_code == 422


def test_feedback_route_normalizes_empty_trace_id_to_null(
    app_client, fake_auth
):
    """An empty-string trace_id should land as NULL in the row, not as
    an empty string the aggregate query has to filter out."""
    response = app_client.post(
        "/api/workspace/feedback",
        json={
            "surface": "assistant_turn",
            "rating": "down",
            "trace_id": "",
        },
        cookies={
            "ja_access_token": "access-token-value",
            "ja_refresh_token": "refresh-token-value",
        },
    )
    assert response.status_code == 200
    rows = feedback_service.in_memory_rows()
    assert rows[0]["trace_id"] is None


def test_feedback_route_accepts_all_five_surfaces(app_client, fake_auth):
    """Defense against accidentally dropping a surface from the
    Literal — every one of the five canonical surfaces should write
    cleanly."""
    surfaces = [
        "tailored_resume",
        "cover_letter",
        "jd_summary",
        "assistant_turn",
        "resume_builder_session",
    ]
    for surface in surfaces:
        response = app_client.post(
            "/api/workspace/feedback",
            json={"surface": surface, "rating": "up"},
            cookies={
                "ja_access_token": "access-token-value",
                "ja_refresh_token": "refresh-token-value",
            },
        )
        assert response.status_code == 200, (
            f"surface {surface!r} should be accepted; got "
            f"{response.status_code}: {response.json()}"
        )
    rows = feedback_service.in_memory_rows()
    assert {row["surface"] for row in rows} == set(surfaces)


def test_feedback_route_handles_backend_outage(app_client, fake_auth, monkeypatch):
    """A Supabase outage should surface as 502 with a generic message —
    NOT leak the underlying error string (which could expose schema
    internals) and NOT silently 200 (which would lie about the
    persistence)."""

    class _ExplodingBackend:
        def is_configured(self) -> bool:
            return True

        def insert(self, _record) -> None:
            raise RuntimeError("simulated supabase outage")

    monkeypatch.setattr(
        feedback_service, "_SUPABASE_BACKEND", _ExplodingBackend()
    )
    response = app_client.post(
        "/api/workspace/feedback",
        json={"surface": "tailored_resume", "rating": "up"},
        cookies={
            "ja_access_token": "access-token-value",
            "ja_refresh_token": "refresh-token-value",
        },
    )
    assert response.status_code == 502
    # Generic detail — no Supabase error string leaks.
    assert "Couldn't record feedback" in response.json()["detail"]


def test_feedback_route_truncates_long_comment_field(app_client, fake_auth):
    """Pydantic max_length=4096 caps the comment at the parse boundary;
    longer payloads return 422 instead of being silently truncated
    server-side."""
    long_comment = "x" * (COMMENT_MAX_CHARS + 100)
    response = app_client.post(
        "/api/workspace/feedback",
        json={
            "surface": "tailored_resume",
            "rating": "down",
            "comment": long_comment,
        },
        cookies={
            "ja_access_token": "access-token-value",
            "ja_refresh_token": "refresh-token-value",
        },
    )
    assert response.status_code == 422
