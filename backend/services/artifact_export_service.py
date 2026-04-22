from __future__ import annotations

import base64
from typing import Literal

from src.cover_letter_builder import build_cover_letter_artifact
from src.errors import ExportError, InputValidationError
from src.exporters import (
    build_cover_letter_preview_html,
    build_report_preview_html,
    build_resume_preview_html,
    export_markdown_bytes,
    export_pdf_bytes,
    export_zip_bundle_bytes,
)
from src.report_builder import build_application_report
from src.resume_builder import RESUME_THEMES, build_tailored_resume_artifact
from src.ui.workflow_payloads import build_saved_workflow_snapshot_from_data


ArtifactKind = Literal["tailored_resume", "cover_letter", "report", "bundle"]
ExportFormat = Literal["markdown", "pdf", "zip"]


def _encode_bytes(payload: bytes):
    return base64.b64encode(payload).decode("ascii")


def _resolve_resume_theme(theme_name: str):
    normalized = str(theme_name or "").strip() or "classic_ats"
    if normalized not in RESUME_THEMES:
        raise InputValidationError("Choose a supported resume theme before exporting.")
    return normalized


def _hydrate_snapshot(workspace_snapshot: dict):
    snapshot = build_saved_workflow_snapshot_from_data(dict(workspace_snapshot or {}))
    if snapshot is None:
        raise InputValidationError(
            "Run the workspace flow before exporting artifacts."
        )
    return snapshot


def _build_artifact_set(workspace_snapshot: dict, resume_theme: str):
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
    )
    report = build_application_report(
        snapshot.candidate_profile,
        snapshot.job_description,
        snapshot.fit_analysis,
        snapshot.tailored_draft,
        agent_result=snapshot.agent_result,
    )
    return {
        "tailored_resume": tailored_resume,
        "cover_letter": cover_letter,
        "report": report,
    }


def _resume_export_file_name(filename_stem: str, resume_theme: str, extension: str):
    return "{stem}-{theme}.{extension}".format(
        stem=filename_stem or "tailored-resume",
        theme=resume_theme,
        extension=extension,
    )


def export_workspace_artifact(
    *,
    workspace_snapshot: dict | None,
    artifact_kind: ArtifactKind,
    export_format: ExportFormat,
    resume_theme: str = "classic_ats",
):
    theme_name = _resolve_resume_theme(resume_theme)
    artifacts = _build_artifact_set(workspace_snapshot or {}, theme_name)

    if artifact_kind == "bundle":
        if export_format != "zip":
            raise InputValidationError(
                "Application bundles can only be exported as zip packages."
            )

        tailored_resume = artifacts["tailored_resume"]
        cover_letter = artifacts["cover_letter"]
        report = artifacts["report"]
        try:
            bundle_bytes = export_zip_bundle_bytes(
                {
                    report.filename_stem + ".md": export_markdown_bytes(report),
                    report.filename_stem + ".pdf": export_pdf_bytes(report),
                    cover_letter.filename_stem + ".md": export_markdown_bytes(cover_letter),
                    cover_letter.filename_stem + ".pdf": export_pdf_bytes(cover_letter),
                    _resume_export_file_name(tailored_resume.filename_stem, theme_name, "md"): export_markdown_bytes(
                        tailored_resume
                    ),
                    _resume_export_file_name(tailored_resume.filename_stem, theme_name, "pdf"): export_pdf_bytes(
                        tailored_resume
                    ),
                }
            )
        except ExportError:
            raise

        return {
            "status": "ready",
            "artifact_kind": artifact_kind,
            "export_format": export_format,
            "file_name": report.filename_stem + "-bundle.zip",
            "mime_type": "application/zip",
            "content_base64": _encode_bytes(bundle_bytes),
            "resume_theme": theme_name,
            "artifact_title": "Application Package Bundle",
        }

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
        "artifact_title": artifact.title,
    }


def preview_workspace_artifact(
    *,
    workspace_snapshot: dict | None,
    artifact_kind: Literal["tailored_resume", "cover_letter", "report"],
    resume_theme: str = "classic_ats",
):
    theme_name = _resolve_resume_theme(resume_theme)
    artifacts = _build_artifact_set(workspace_snapshot or {}, theme_name)
    artifact = artifacts[artifact_kind]

    if artifact_kind == "tailored_resume":
        html = build_resume_preview_html(artifact)
    elif artifact_kind == "cover_letter":
        html = build_cover_letter_preview_html(artifact)
    else:
        html = build_report_preview_html(artifact)

    return {
        "status": "ready",
        "artifact_kind": artifact_kind,
        "resume_theme": theme_name,
        "artifact_title": artifact.title,
        "html": html,
    }
