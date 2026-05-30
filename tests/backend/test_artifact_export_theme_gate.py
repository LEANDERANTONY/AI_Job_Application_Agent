"""Export entitlement is scoped to the exported artifact's theme (FLOW-3).

The export route gated entitlement on BOTH the résumé theme and the
cover-letter theme at once. But the renderer only ever uses
``artifacts[artifact_kind]`` with that artifact's own theme, and theme
previews are ungated and encouraged. So a Free user who previewed a Pro
cover-letter theme, then exported the RÉSUMÉ in the default (allowed)
theme, was rejected with a misleading "Custom export themes is a Pro+
feature" 429 — a core Free export blocked by hidden, unrelated UI state.

These route-level tests pin the fix: the gate considers only the theme
that actually renders the artifact being exported, while still upselling
when THAT artifact's own theme is a paid one. Anonymous callers resolve
to the Free tier (``_resolve_export_tier``), so no auth setup is needed;
the renderer is stubbed so the tests exercise the GATE, not PDF/DOCX
generation.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app import app


client = TestClient(app)

EXPORT_URL = "/api/workspace/artifacts/export"
# Any non-default theme is Pro-only; classic_ats is the canonical
# alternate used across the entitlement tests.
PRO_THEME = "classic_ats"
FREE_THEME = "professional_neutral"


@pytest.fixture
def _stub_renderer(monkeypatch):
    """Stub the renderer so a passed gate doesn't require a fully
    hydrated workspace snapshot — these tests are about the gate."""
    monkeypatch.setattr(
        "backend.routers.workspace.export_workspace_artifact",
        lambda **kwargs: {
            "status": "ready",
            "artifact_kind": kwargs["artifact_kind"],
            "export_format": kwargs["export_format"],
            "file_name": "x.pdf",
            "mime_type": "application/pdf",
            "content_base64": "",
            "resume_theme": kwargs.get("resume_theme"),
            "cover_letter_theme": kwargs.get("cover_letter_theme"),
            "artifact_title": "x",
        },
    )


def _payload(**overrides):
    base = {
        "workspace_snapshot": {},
        "artifact_kind": "tailored_resume",
        "export_format": "pdf",
        "resume_theme": FREE_THEME,
        "cover_letter_theme": FREE_THEME,
    }
    base.update(overrides)
    return base


def test_free_resume_export_not_blocked_by_unrelated_cover_letter_theme(_stub_renderer):
    # The regression case: resume in the allowed default theme, but a Pro
    # cover-letter theme is selected (irrelevant to a resume export).
    response = client.post(
        EXPORT_URL,
        json=_payload(
            artifact_kind="tailored_resume",
            resume_theme=FREE_THEME,
            cover_letter_theme=PRO_THEME,
        ),
    )
    assert response.status_code == 200


def test_free_cover_letter_export_not_blocked_by_unrelated_resume_theme(_stub_renderer):
    # Symmetric: cover letter in the allowed default theme, Pro résumé
    # theme selected (irrelevant to a cover-letter export).
    response = client.post(
        EXPORT_URL,
        json=_payload(
            artifact_kind="cover_letter",
            resume_theme=PRO_THEME,
            cover_letter_theme=FREE_THEME,
        ),
    )
    assert response.status_code == 200


def test_free_resume_export_still_blocked_by_its_own_pro_theme():
    # The gate isn't disabled — only scoped. Exporting the RÉSUMÉ itself
    # in a Pro theme still upsells.
    response = client.post(
        EXPORT_URL,
        json=_payload(artifact_kind="tailored_resume", resume_theme=PRO_THEME),
    )
    assert response.status_code == 429
    assert response.json()["code"] == "tier_limit_exceeded"


def test_free_cover_letter_export_still_blocked_by_its_own_pro_theme():
    response = client.post(
        EXPORT_URL,
        json=_payload(
            artifact_kind="cover_letter",
            resume_theme=FREE_THEME,
            cover_letter_theme=PRO_THEME,
        ),
    )
    assert response.status_code == 429
    assert response.json()["code"] == "tier_limit_exceeded"
