"""Quota enforcement at /workspace/assistant/answer and
/workspace/assistant/answer/stream.

Step 4 of the tier-enforcement series. Both the sync answer and the
streaming SSE sibling consume the same ``assistant_turns`` monthly
counter so a user flipping between them shares one budget.

What we verify:

  * 21st sync call on Free → 429 (cap=20).
  * 151st sync call on Pro → 429 (cap=150).
  * Streaming surface returns a plain 429 (NOT an SSE error frame)
    when the user is at cap. A 429 in the middle of an open
    text/event-stream is unsupported by browsers, so the gate must
    run BEFORE StreamingResponse is constructed.
  * Generator failure refunds the credit so a transient OpenAI
    error doesn't burn one of the user's monthly turns.
  * Anonymous chat skips the gate entirely (no user_id to attribute
    the credit to).

Tests reach in past the route when they need to inject a synthetic
authenticated context; HTTP-surface tests use the FastAPI TestClient.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend import quota
from backend.app import app
from backend.quota import current_period_key, reset_in_memory_backend
from backend.services import workspace_service
from backend.services.auth_session_service import AuthenticatedContext
from backend.tiers import TIER_CAPS
from src.auth_service import AuthSession, AuthUser
from src.errors import QuotaExceededError
from src.schemas import AppUserRecord


client = TestClient(app, raise_server_exceptions=False)


# ─── fixtures ───────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _fresh_quota_backend(monkeypatch):
    """Force the in-memory quota backend with empty state — same pattern
    as test_workspace_quota_enforcement so test ordering can't leak
    counter state across modules."""

    class _NeverConfigured:
        def is_configured(self) -> bool:
            return False

    monkeypatch.setattr(quota, "_SUPABASE_BACKEND", _NeverConfigured())
    reset_in_memory_backend()
    yield
    reset_in_memory_backend()


def _build_auth_context(*, user_id: str = "user-test", email: str = "u@example.com"):
    """Construct a minimally-valid AuthenticatedContext for the gate.

    The gate only reads ``auth_context.app_user.id``. Downstream
    dependencies (auth_service, daily_quota) are stubbed elsewhere so
    we leave them as None/None to keep the fixture minimal.
    """
    auth_session = AuthSession(
        access_token="access",
        refresh_token="refresh",
        user=AuthUser(user_id=user_id, email=email),
    )
    app_user = AppUserRecord(id=user_id, email=email)
    return AuthenticatedContext(
        auth_service=None,  # type: ignore[arg-type] - unused in these tests
        auth_session=auth_session,
        app_user=app_user,
        daily_quota=None,
    )


@pytest.fixture
def stub_assistant(monkeypatch):
    """Replace AssistantService with a stub that returns deterministic
    output, so a quota-gate test never depends on the LLM / prompt
    machinery. Both .answer() and .stream_answer() are covered.
    """
    from src.schemas import AssistantResponse

    class _StubAssistant:
        def __init__(self, *_args, **_kwargs):
            pass

        def answer(self, *_args, **_kwargs):
            return AssistantResponse(answer="Hello")

        def stream_answer(self, *_args, **_kwargs):
            yield "Hello"

    monkeypatch.setattr(workspace_service, "AssistantService", _StubAssistant)
    # Don't try to construct a real OpenAIService when the auth context
    # is synthetic. Returning (None, None) routes to the deterministic
    # path the AssistantService already supports.
    monkeypatch.setattr(
        workspace_service,
        "build_openai_service_for_context",
        lambda _ctx: (None, None),
    )


def _answer(*, auth_context=None, question: str = "What now?"):
    """Drive answer_workspace_question with the supplied auth context.

    Mirrors the helper in test_workspace_quota_enforcement so the
    test reads similarly across surfaces.
    """

    def _resolver(*, access_token=None, refresh_token=None):
        return auth_context

    with patch.object(
        workspace_service,
        "resolve_authenticated_context",
        _resolver,
    ):
        return workspace_service.answer_workspace_question(
            question=question,
            current_page="Workspace",
            workspace_state=None,
            workspace_snapshot=None,
            history=[],
            access_token="access" if auth_context else "",
            refresh_token="refresh" if auth_context else "",
        )


def _stream(*, auth_context=None, question: str = "What now?"):
    """Drive prepare + stream_workspace_question, collect all frames.

    The route-level test uses the TestClient. This helper exercises
    the service layer directly so we can assert on per-stage behavior
    (e.g. that refund fires after a generator exception).
    """

    def _resolver(*, access_token=None, refresh_token=None):
        return auth_context

    with patch.object(
        workspace_service,
        "resolve_authenticated_context",
        _resolver,
    ):
        prepared = workspace_service.prepare_stream_workspace_question(
            access_token="access" if auth_context else "",
            refresh_token="refresh" if auth_context else "",
        )
        return list(
            workspace_service.stream_workspace_question(
                question=question,
                current_page="Workspace",
                workspace_state=None,
                workspace_snapshot=None,
                history=[],
                prepared=prepared,
            )
        )


# ─── core enforcement assertions ────────────────────────────────────────


def test_21st_sync_assistant_turn_on_free_returns_429(stub_assistant):
    """Free's assistant_turns cap is 20. Twenty answers must succeed,
    the 21st rejects with cap=20 and current=20."""
    auth_context = _build_auth_context(user_id="user-free-assistant-1")

    for _ in range(TIER_CAPS["free"]["assistant_turns"]):
        result = _answer(auth_context=auth_context)
        assert result["answer"] == "Hello"

    with pytest.raises(QuotaExceededError) as exc_info:
        _answer(auth_context=auth_context)
    err = exc_info.value
    assert err.counter == "assistant_turns"
    assert err.cap == TIER_CAPS["free"]["assistant_turns"] == 20
    assert err.current == 20
    assert err.reset_period == current_period_key()
    assert err.tier == "free"


def test_151st_sync_assistant_turn_on_pro_returns_429(stub_assistant, monkeypatch):
    """Pro's assistant_turns cap is 150. Force the tier resolver to "pro"
    (the production shim still returns "free" until Stripe lands) so we
    can exercise the Pro cap end-to-end.
    """
    monkeypatch.setattr(workspace_service, "resolve_user_tier", lambda _u: "pro")
    auth_context = _build_auth_context(user_id="user-pro-assistant-1")

    for _ in range(TIER_CAPS["pro"]["assistant_turns"]):
        _answer(auth_context=auth_context)

    with pytest.raises(QuotaExceededError) as exc_info:
        _answer(auth_context=auth_context)
    err = exc_info.value
    assert err.counter == "assistant_turns"
    assert err.cap == TIER_CAPS["pro"]["assistant_turns"] == 150
    assert err.current == 150
    assert err.tier == "pro"


def test_streaming_surface_returns_429_not_sse_at_cap(stub_assistant, monkeypatch):
    """When the user is at cap the streaming endpoint must reject with
    a plain 429 (not an SSE error frame). Mixing a 429 status into an
    open text/event-stream is not supported; the gate runs before
    StreamingResponse commits the 200 OK + content-type."""
    auth_context = _build_auth_context(user_id="user-stream-cap-1")
    monkeypatch.setattr(
        workspace_service,
        "resolve_authenticated_context",
        lambda **_kwargs: auth_context,
    )

    # Burn the budget at the service layer so the route call itself
    # is the one that raises.
    for _ in range(TIER_CAPS["free"]["assistant_turns"]):
        _answer(auth_context=auth_context)

    response = client.post(
        "/api/workspace/assistant/answer/stream",
        json={
            "question": "Help",
            "current_page": "Workspace",
            "workspace_snapshot": None,
            "history": [],
        },
        headers={
            "X-Auth-Access-Token": "access",
            "X-Auth-Refresh-Token": "refresh",
        },
    )

    assert response.status_code == 429
    # Crucially: NOT text/event-stream. The global handler returns
    # application/json with the canonical payload.
    content_type = response.headers.get("content-type", "")
    assert "event-stream" not in content_type.lower()
    body = response.json()
    assert body["code"] == "tier_limit_exceeded"
    assert body["counter"] == "assistant_turns"
    assert body["cap"] == TIER_CAPS["free"]["assistant_turns"]


def test_generator_exception_refunds_the_credit(stub_assistant, monkeypatch):
    """A mid-stream exception in stream_answer should refund the credit
    so the user doesn't lose a turn to a transient OpenAI/parser error.
    We verify by burning N-1 credits, raising on the next stream, then
    confirming the next sync answer still succeeds (which would not be
    the case if the failed stream had consumed a real credit)."""
    auth_context = _build_auth_context(user_id="user-stream-refund-1")
    cap = TIER_CAPS["free"]["assistant_turns"]

    # Consume cap-1 turns the happy way.
    for _ in range(cap - 1):
        _answer(auth_context=auth_context)

    # Wire stream_answer to blow up so the generator hits its except
    # branch — which should refund.
    class _BoomAssistant:
        def __init__(self, *_args, **_kwargs):
            pass

        def stream_answer(self, *_args, **_kwargs):
            raise RuntimeError("model timed out")

        def answer(self, *_args, **_kwargs):
            from src.schemas import AssistantResponse

            return AssistantResponse(answer="Hello")

    monkeypatch.setattr(workspace_service, "AssistantService", _BoomAssistant)

    # Drive one streaming call — it should consume the cap-th credit,
    # then refund when the generator raises.
    frames = _stream(auth_context=auth_context)
    # The generator catches the RuntimeError and emits an `error` event
    # before the trailing `done`. We don't care about the exact text;
    # we just need to confirm the error branch fired (and therefore
    # the refund-in-finally path ran).
    assert any("event: error" in frame for frame in frames), frames

    # Restore the happy path. We should still be allowed cap-1 → cap
    # one more time (the refund put us back at cap-1).
    class _OkAssistant:
        def __init__(self, *_args, **_kwargs):
            pass

        def answer(self, *_args, **_kwargs):
            from src.schemas import AssistantResponse

            return AssistantResponse(answer="OK")

        def stream_answer(self, *_args, **_kwargs):
            yield "OK"

    monkeypatch.setattr(workspace_service, "AssistantService", _OkAssistant)
    # One more sync call lands us at cap.
    _answer(auth_context=auth_context)
    # And the next one trips the gate.
    with pytest.raises(QuotaExceededError):
        _answer(auth_context=auth_context)


def test_anonymous_chat_skips_the_gate(stub_assistant):
    """Anonymous sync chat has no user_id and must skip the gate.
    The deterministic fallback path still runs."""
    result = _answer(auth_context=None)
    assert result["answer"] == "Hello"


def test_anonymous_streaming_chat_skips_the_gate(stub_assistant):
    """Same skip semantics on the streaming surface. The anonymous
    request still produces a valid SSE stream (meta -> delta -> done)
    instead of a 429."""
    frames = _stream(auth_context=None)
    joined = "\n".join(frames)
    assert "event: meta" in joined
    assert "event: delta" in joined
    assert "event: done" in joined
