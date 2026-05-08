"""Synthetic error-handling scenarios.

Drives the API through ~15 known error states and asserts the response
detail is friendly — no raw Python exception text, no stack frames, no
file paths, no `<class '...'>` repr leak. The frontend's
`humanizeApiError` does final polish; this test pins the backend's
contract so the polish layer doesn't have to clean up after a leak.

Scenarios are parametrized so a regression in any one shows up as a
single failing test, not a wall of asserts in one mega-test.

LLM failures are fully mocked — no real OpenAI calls. The
error-message contract is what's under test, not the LLM behavior.
"""

from __future__ import annotations

import re
from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from src.errors import AgentExecutionError, AppError


client = TestClient(app)


# ---------------------------------------------------------------------------
# Friendliness assertions — what counts as "leaky"?
# ---------------------------------------------------------------------------


_LEAKY_PATTERNS = (
    re.compile(r"\bTraceback \(most recent call last\)"),
    re.compile(r"<class '[A-Za-z_.]+Error'>"),
    re.compile(r"^[A-Z][a-z]+Error\([\"']"),  # "ValueError('foo')" repr
    re.compile(r"^/[a-z/]+\.py"),  # leading file path
    re.compile(r"[A-Z]:\\[A-Z][^']*\.py"),  # Windows file path
    re.compile(r"\bat 0x[0-9A-Fa-f]{6,}"),  # `<object at 0x7fbabbab>`
)


def _detail_text(detail: Any) -> str:
    """Pydantic 422 returns detail as a list of dicts; everything else
    returns a single string. Flatten to one string for substring
    checks."""
    if isinstance(detail, list):
        parts: list[str] = []
        for item in detail:
            if isinstance(item, dict):
                parts.append(str(item.get("msg", "")))
                # Also flatten the loc tuple so `body.session_id` style
                # leakage gets seen by the patterns.
                loc = item.get("loc")
                if isinstance(loc, list):
                    parts.append(".".join(str(p) for p in loc))
        return " | ".join(parts)
    if isinstance(detail, str):
        return detail
    return str(detail or "")


def _assert_friendly_detail(detail: Any, *, status: int):
    """Common friendliness checks across every scenario.

    Pydantic 422 arrays are exempt from the "ends with terminal
    punctuation" rule because they're already structured field-level
    objects; the frontend humanizer translates the whole shape into a
    single sentence."""
    text = _detail_text(detail)
    assert text, f"empty detail on status {status}"
    for pattern in _LEAKY_PATTERNS:
        assert not pattern.search(text), (
            f"leaky pattern {pattern.pattern!r} matched detail on "
            f"status {status}: {text[:200]!r}"
        )
    # detail length sanity: a stack frame would push us well past 1KB.
    assert len(text) < 1500, f"detail unusually long ({len(text)} chars) for status {status}"
    if isinstance(detail, str):
        assert text == text.strip(), "detail has leading/trailing whitespace"


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


def _scenario_resume_builder_message_unknown_session():
    response = client.post(
        "/api/workspace/resume-builder/message",
        json={
            "session_id": "session-that-never-existed",
            "message": "hi",
            "input_mode": "text",
        },
    )
    assert response.status_code == 400
    payload = response.json()
    _assert_friendly_detail(payload["detail"], status=400)
    # Specific contract: the error mentions "session" so the user
    # knows what to look for.
    assert "session" in payload["detail"].lower()


def _scenario_resume_builder_export_unknown_session():
    response = client.post(
        "/api/workspace/resume-builder/export",
        json={
            "session_id": "wrong-id",
            "export_format": "docx",
            "theme": "classic_ats",
        },
    )
    assert response.status_code == 400
    payload = response.json()
    _assert_friendly_detail(payload["detail"], status=400)
    assert "session" in payload["detail"].lower()


def _scenario_resume_builder_export_unsupported_format():
    response = client.post(
        "/api/workspace/resume-builder/export",
        json={
            "session_id": "any-session-id",
            "export_format": "markdown",
            "theme": "classic_ats",
        },
    )
    # Pydantic Literal validator catches unsupported format → 422.
    assert response.status_code == 422
    payload = response.json()
    _assert_friendly_detail(payload["detail"], status=422)


def _scenario_artifact_export_unsupported_format():
    response = client.post(
        "/api/workspace/artifacts/export",
        json={
            "workspace_snapshot": {
                "candidate_profile": {"full_name": "Test"},
                "job_description": {"title": "Engineer"},
                "fit_analysis": {"overall_score": 50},
                "tailored_draft": {"target_role": "Engineer"},
            },
            "artifact_kind": "tailored_resume",
            "export_format": "markdown",
            "resume_theme": "classic_ats",
        },
    )
    assert response.status_code == 422
    payload = response.json()
    _assert_friendly_detail(payload["detail"], status=422)


def _scenario_workspace_analyze_empty_body():
    response = client.post("/api/workspace/analyze", json={})
    assert response.status_code == 422
    payload = response.json()
    _assert_friendly_detail(payload["detail"], status=422)


def _scenario_analyze_jobs_status_missing_job():
    response = client.get("/api/workspace/analyze-jobs/missing-job-id")
    assert response.status_code == 404
    payload = response.json()
    _assert_friendly_detail(payload["detail"], status=404)
    # Phase 5 of the original 14-item punch list specifically rewrote
    # this 404 detail to be actionable. Pin that copy here.
    assert "no longer available" in payload["detail"].lower()


def _scenario_admin_refresh_without_bearer():
    response = client.post("/api/admin/refresh-cache")
    # 401 OR 403 depending on dependency config; both must be friendly.
    assert response.status_code in {401, 403}
    payload = response.json()
    _assert_friendly_detail(payload["detail"], status=response.status_code)


def _scenario_admin_refresh_invalid_bearer():
    response = client.post(
        "/api/admin/refresh-cache",
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert response.status_code == 401
    payload = response.json()
    _assert_friendly_detail(payload["detail"], status=401)


def _scenario_resume_upload_with_invalid_base64(monkeypatch):
    response = client.post(
        "/api/workspace/resume/upload",
        json={
            "filename": "test.txt",
            "mime_type": "text/plain",
            "content_base64": "this is not valid base64 ###",
        },
    )
    # The service should map the decode error to a friendly AppError.
    # Status varies (400 likely), but the detail must NOT leak the
    # base64 library's internal exception text.
    assert response.status_code in {400, 422}
    payload = response.json()
    _assert_friendly_detail(payload["detail"], status=response.status_code)


def _scenario_resume_builder_message_with_llm_error(monkeypatch):
    """Stub the LLM service to raise AgentExecutionError. The route
    catches it via the regex fallback path, so the response is 200
    with the deterministic step's prompt. We verify the response is
    well-formed (no error path leaked at all)."""

    class _BrokenOpenAIService:
        def is_available(self):
            return True

        def run_json_prompt(self, *args, **kwargs):
            raise AgentExecutionError(
                "Mocked LLM failure: the model returned malformed JSON."
            )

    monkeypatch.setattr(
        "backend.routers.workspace._resolve_openai_service",
        lambda access_token, refresh_token: _BrokenOpenAIService(),
    )

    start_response = client.post("/api/workspace/resume-builder/start")
    session_id = start_response.json()["session_id"]

    response = client.post(
        "/api/workspace/resume-builder/message",
        json={
            "session_id": session_id,
            "message": "Hi I'm Test User from Remote",
            "input_mode": "text",
        },
        headers={
            "X-Auth-Access-Token": "x",
            "X-Auth-Refresh-Token": "y",
        },
    )
    # Fallback path keeps it 200 — the user never sees the LLM failure.
    assert response.status_code == 200, (
        f"LLM failure should fall back to 200 (regex path), got "
        f"{response.status_code}: {response.json()}"
    )


def _scenario_resume_builder_export_returns_400_with_real_message():
    """End-to-end check: a generic 400 on this route lands a real,
    user-typed string (not a leaked exception). Even when the lint
    catches the same shape statically, the runtime sees what the
    actual response body looks like."""
    response = client.post(
        "/api/workspace/resume-builder/export",
        json={
            "session_id": "definitely-not-real",
            "export_format": "docx",
            "theme": "classic_ats",
        },
    )
    assert response.status_code == 400
    payload = response.json()
    detail = payload["detail"]
    # Confirm not a Python repr.
    assert not detail.startswith("<")
    assert not detail.startswith("(")
    # Friendly copy ends with a period or sentence terminator.
    assert detail.rstrip().endswith((".", "!"))


def _scenario_save_workspace_unauthenticated():
    """No auth tokens → save service raises a friendly error."""
    response = client.post(
        "/api/workspace/save",
        json={
            "workspace_snapshot": {
                "candidate_profile": {"full_name": "Test"},
                "job_description": {"title": "Engineer"},
                "fit_analysis": {"overall_score": 50},
                "tailored_draft": {"target_role": "Engineer"},
                "artifacts": {"tailored_resume": {"markdown": "# Test"}},
            },
        },
    )
    # Status varies (400 or 422), but the detail must be friendly.
    assert response.status_code in {400, 401, 422}
    payload = response.json()
    _assert_friendly_detail(payload["detail"], status=response.status_code)


def _scenario_assistant_answer_unknown_action():
    response = client.post(
        "/api/workspace/assistant/answer",
        json={
            "question": "",  # empty question after trim → validator fails
            "current_page": "Workspace",
        },
    )
    # Either 422 (validator) or 200 with a graceful fallback. Both
    # are acceptable — assert the detail (when present) is friendly.
    if response.status_code != 200:
        payload = response.json()
        _assert_friendly_detail(payload["detail"], status=response.status_code)


_SCENARIOS: list[tuple[str, Callable]] = [
    ("resume_builder_message_unknown_session", _scenario_resume_builder_message_unknown_session),
    ("resume_builder_export_unknown_session", _scenario_resume_builder_export_unknown_session),
    ("resume_builder_export_unsupported_format", _scenario_resume_builder_export_unsupported_format),
    ("artifact_export_unsupported_format", _scenario_artifact_export_unsupported_format),
    ("workspace_analyze_empty_body", _scenario_workspace_analyze_empty_body),
    ("analyze_jobs_status_missing_job", _scenario_analyze_jobs_status_missing_job),
    # The two admin-refresh bearer scenarios live as separate test
    # functions below — they need a `monkeypatch` to set the
    # REFRESH_CACHE_SECRET. Without it the endpoint returns 503
    # ("Refresh-cache secret not configured") and the bearer-check
    # branches we're trying to exercise never run. (Local dev
    # happens to pass because `.env` populates the secret; CI
    # doesn't ship a `.env`, so the parametrized form failed
    # only in CI.)
    ("resume_builder_export_400_real_message", _scenario_resume_builder_export_returns_400_with_real_message),
    ("save_workspace_unauthenticated", _scenario_save_workspace_unauthenticated),
    ("assistant_answer_unknown_action", _scenario_assistant_answer_unknown_action),
]


@pytest.mark.parametrize("name,scenario_fn", _SCENARIOS, ids=[name for name, _ in _SCENARIOS])
def test_error_scenario(name, scenario_fn):
    scenario_fn()


def test_admin_refresh_without_bearer(monkeypatch):
    """Endpoint must reject an unauthenticated POST with 401/403.

    Patches REFRESH_CACHE_SECRET so the bearer-check branch is
    actually reached (without a configured secret the endpoint
    short-circuits with a 503).
    """
    monkeypatch.setattr("backend.routers.jobs.REFRESH_CACHE_SECRET", "test-secret")
    _scenario_admin_refresh_without_bearer()


def test_admin_refresh_invalid_bearer(monkeypatch):
    """Endpoint must reject a wrong bearer with 401."""
    monkeypatch.setattr("backend.routers.jobs.REFRESH_CACHE_SECRET", "test-secret")
    _scenario_admin_refresh_invalid_bearer()


def test_resume_upload_with_invalid_base64(monkeypatch):
    _scenario_resume_upload_with_invalid_base64(monkeypatch)


def test_resume_builder_message_with_llm_error(monkeypatch):
    _scenario_resume_builder_message_with_llm_error(monkeypatch)


# ---------------------------------------------------------------------------
# AppError -> route mapping invariant
# ---------------------------------------------------------------------------


def test_app_error_user_message_lands_in_detail():
    """When a service raises an AppError, the route's `_raise_http_error`
    helper must surface the `user_message` (not the class repr or the
    `details` field) as the response detail."""
    from backend.routers.workspace import _raise_http_error
    from fastapi import HTTPException

    error = AppError(
        "Friendly message for the user.",
        details="internal trace data that should NOT show up",
    )
    try:
        _raise_http_error(error)
    except HTTPException as raised:
        assert raised.status_code == 400
        assert raised.detail == "Friendly message for the user."
        assert "internal trace" not in raised.detail
    else:
        raise AssertionError("Expected HTTPException")
