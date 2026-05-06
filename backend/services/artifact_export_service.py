from __future__ import annotations

import base64
from typing import Literal

from src.cover_letter_builder import build_cover_letter_artifact
from src.errors import InputValidationError
from src.exporters import (
    build_cover_letter_preview_html,
    build_resume_preview_html,
    export_markdown_bytes,
    export_pdf_bytes,
)
from src.resume_builder import build_tailored_resume_artifact
from src.workflow_payloads import build_saved_workflow_snapshot_from_data


ArtifactKind = Literal["tailored_resume", "cover_letter"]
ExportFormat = Literal["markdown", "pdf"]


def _encode_bytes(payload: bytes):
    return base64.b64encode(payload).decode("ascii")


_SUPPORTED_THEMES = {"classic_ats", "professional_neutral"}


def _resolve_theme(theme_name: str | None):
    return theme_name if theme_name in _SUPPORTED_THEMES else "classic_ats"


# Back-compat alias — older callers may still import this name.
def _resolve_resume_theme(theme_name: str):
    return _resolve_theme(theme_name)


def _hydrate_snapshot(workspace_snapshot: dict):
    snapshot = build_saved_workflow_snapshot_from_data(dict(workspace_snapshot or {}))
    if snapshot is None:
        raise InputValidationError(
            "Run the workspace flow before exporting artifacts."
        )
    return snapshot


def _build_artifact_set(workspace_snapshot: dict, resume_theme: str, cover_letter_theme: str):
    snapshot = _hydrate_snapshot(workspace_snapshot)
    tailored_resume = build_tailored_resume_artifact(
        snapshot.candidate_profile,
        snapshot.job_description,
        snapshot.fit_analysis,
        snapshot.tailored_draft,
        agent_result=snapshot.agent_result,
        theme=resume_theme,
    )
    cover_letter = build_cover_letter_artifact(
        snapshot.candidate_profile,
        snapshot.job_description,
        snapshot.fit_analysis,
        snapshot.tailored_draft,
        agent_result=snapshot.agent_result,
        theme=cover_letter_theme,
    )
    return {
        "tailored_resume": tailored_resume,
        "cover_letter": cover_letter,
    }


def _resume_export_file_name(filename_stem: str, resume_theme: str, extension: str):
    return "{stem}.{extension}".format(
        stem=filename_stem or "tailored-resume",
        extension=extension,
    )


def export_workspace_artifact(
    *,
    workspace_snapshot: dict | None,
    artifact_kind: ArtifactKind,
    export_format: ExportFormat,
    resume_theme: str = "classic_ats",
    cover_letter_theme: str = "classic_ats",
):
    theme_name = _resolve_theme(resume_theme)
    cover_theme_name = _resolve_theme(cover_letter_theme)
    artifacts = _build_artifact_set(workspace_snapshot or {}, theme_name, cover_theme_name)

    artifact = artifacts[artifact_kind]
    if export_format == "markdown":
        payload = export_markdown_bytes(artifact)
        mime_type = "text/markdown"
        file_name = (
            _resume_export_file_name(artifact.filename_stem, theme_name, "md")
            if artifact_kind == "tailored_resume"
            else artifact.filename_stem + ".md"
        )
    elif export_format == "pdf":
        payload = export_pdf_bytes(artifact)
        mime_type = "application/pdf"
        file_name = (
            _resume_export_file_name(artifact.filename_stem, theme_name, "pdf")
            if artifact_kind == "tailored_resume"
            else artifact.filename_stem + ".pdf"
        )
    else:
        raise InputValidationError("Choose a supported export format.")

    return {
        "status": "ready",
        "artifact_kind": artifact_kind,
        "export_format": export_format,
        "file_name": file_name,
        "mime_type": mime_type,
        "content_base64": _encode_bytes(payload),
        "resume_theme": theme_name,
        "cover_letter_theme": cover_theme_name,
        "artifact_title": artifact.title,
    }


def preview_workspace_artifact(
    *,
    workspace_snapshot: dict | None,
    artifact_kind: Literal["tailored_resume", "cover_letter"],
    resume_theme: str = "classic_ats",
    cover_letter_theme: str = "classic_ats",
):
    theme_name = _resolve_theme(resume_theme)
    cover_theme_name = _resolve_theme(cover_letter_theme)
    artifacts = _build_artifact_set(workspace_snapshot or {}, theme_name, cover_theme_name)
    artifact = artifacts[artifact_kind]

    if artifact_kind == "tailored_resume":
        html = build_resume_preview_html(artifact)
    else:
        html = build_cover_letter_preview_html(artifact)

    return {
        "status": "ready",
        "artifact_kind": artifact_kind,
        "resume_theme": theme_name,
        "cover_letter_theme": cover_theme_name,
        "artifact_title": artifact.title,
        "html": html,
    }
