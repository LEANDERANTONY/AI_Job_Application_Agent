"""Login-required gate on the LLM routes (token-meter migration, T5).

Every route that spends model tokens must be attributable to a
``user_id`` for the unified weekly token meter — an anonymous call has
nothing to meter and would be an un-capped abuse vector. These tests
pin that each such route rejects an anonymous request with **401**
(not 200, not 422). The routes' FUNCTIONALITY is tested elsewhere
(``test_backend_workspace.py`` etc.) under an auth-override fixture;
here we deliberately send NO auth so the gate itself fires.
"""
from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.request_auth import get_required_auth_tokens


client = TestClient(app)


@pytest.fixture(autouse=True)
def _no_auth_override():
    """Defensively clear any leaked ``get_required_auth_tokens``
    dependency override before each test. Sibling test modules
    (test_backend_workspace.py, test_backend_assistant_stream.py)
    install that override to run their functional tests anonymously;
    pop it here so a test-ordering surprise can't mask the 401."""
    app.dependency_overrides.pop(get_required_auth_tokens, None)
    yield
    app.dependency_overrides.pop(get_required_auth_tokens, None)


def _file_payload() -> dict:
    return {
        "filename": "x.txt",
        "mime_type": "text/plain",
        "content_base64": base64.b64encode(b"hello").decode("ascii"),
    }


_ANALYZE_BODY = {
    "resume_text": "Resume body",
    "resume_filetype": "TXT",
    "resume_source": "workspace",
    "job_description_text": "JD body",
    "run_assisted": False,
}

# (path, json body) — each body is minimally VALID so the ONLY thing
# that can fail is the auth gate (no spurious 422 masking the 401).
_GATED_LLM_ROUTES = [
    ("/api/workspace/resume/upload", _file_payload()),
    ("/api/workspace/job-description/upload", _file_payload()),
    ("/api/workspace/analyze", _ANALYZE_BODY),
    ("/api/workspace/analyze-jobs", _ANALYZE_BODY),
    ("/api/workspace/assistant/answer", {"question": "What now?"}),
    ("/api/workspace/assistant/answer/stream", {"question": "What now?"}),
    ("/api/workspace/resume-builder/start", None),
    (
        "/api/workspace/resume-builder/message",
        {"session_id": "any", "message": "hi", "input_mode": "text"},
    ),
    ("/api/workspace/resume-builder/generate", {"session_id": "any"}),
]


@pytest.mark.parametrize("path,body", _GATED_LLM_ROUTES)
def test_llm_route_rejects_anonymous_with_401(path, body):
    """An anonymous POST (no auth cookies / headers) to a token-spending
    route is rejected with 401 before any LLM work runs."""
    response = (
        client.post(path, json=body) if body is not None else client.post(path)
    )
    assert response.status_code == 401, (
        f"{path} must 401 for anonymous, got {response.status_code}"
    )
    assert "sign in" in response.json()["detail"].lower()


def test_non_llm_route_still_allows_anonymous():
    """Counter-check that the gate is targeted, not blanket: a NON-LLM
    workspace route — the LLM-free résumé-builder preview — is not
    caught by the T5 gate. Anonymous reaches the handler (it 400s on
    the missing session) and crucially is NOT 401'd."""
    response = client.post(
        "/api/workspace/resume-builder/preview",
        json={"session_id": "does-not-exist", "theme": "professional_neutral"},
    )
    assert response.status_code != 401
