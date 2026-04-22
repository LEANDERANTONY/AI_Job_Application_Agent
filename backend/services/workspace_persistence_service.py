from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any

from backend.services.auth_session_service import resolve_authenticated_context
from src.cover_letter_builder import build_cover_letter_artifact
from src.report_builder import build_application_report
from src.resume_builder import build_tailored_resume_artifact
from src.saved_workspace_store import SavedWorkspaceStore
from src.services.jd_summary_service import generate_job_summary_view
from src.ui.workflow_payloads import (
    WORKFLOW_HISTORY_PAYLOAD_KIND_COVER_LETTER,
    WORKFLOW_HISTORY_PAYLOAD_KIND_REPORT,
    WORKFLOW_HISTORY_PAYLOAD_KIND_SNAPSHOT,
    WORKFLOW_HISTORY_PAYLOAD_KIND_TAILORED_RESUME,
    build_saved_cover_letter_from_payload,
    build_saved_report_from_payload,
    build_saved_tailored_resume_from_payload,
    build_saved_workflow_snapshot_from_payload,
    versioned_payload,
)


def _serialize(value: Any):
    if is_dataclass(value):
        return {key: _serialize(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


def _workspace_signature(snapshot: dict[str, Any]):
    payload = {
        "candidate_profile": snapshot.get("candidate_profile") or {},
        "job_description": snapshot.get("job_description") or {},
        "fit_analysis": snapshot.get("fit_analysis") or {},
        "tailored_draft": snapshot.get("tailored_draft") or {},
    }
    return json.dumps(payload, sort_keys=True, default=str)


def _validate_workspace_snapshot(snapshot: dict[str, Any] | None):
    payload = dict(snapshot or {})
    required_sections = [
        "candidate_profile",
        "job_description",
        "fit_analysis",
        "tailored_draft",
        "artifacts",
    ]
    for section in required_sections:
        if not isinstance(payload.get(section), dict):
            raise ValueError(section)
    return payload


def save_workspace_snapshot(
    *,
    access_token: str,
    refresh_token: str,
    workspace_snapshot: dict[str, Any] | None,
):
    try:
        snapshot = _validate_workspace_snapshot(workspace_snapshot)
    except ValueError as exc:
        raise ValueError(f"workspace_snapshot.{exc.args[0]}")

    context = resolve_authenticated_context(
        access_token=access_token,
        refresh_token=refresh_token,
    )
    saved_workspace_store = SavedWorkspaceStore(context.auth_service)
    if not saved_workspace_store.is_configured():
        raise RuntimeError("Saved workspace persistence is not configured.")

    artifacts = dict(snapshot.get("artifacts") or {})
    record = saved_workspace_store.save_workspace(
        access_token,
        refresh_token,
        {
            "user_id": context.app_user.id,
            "job_title": str(
                snapshot.get("job_description", {}).get("title", "") or ""
            ),
            "workflow_signature": _workspace_signature(snapshot),
            "workflow_snapshot_json": versioned_payload(
                WORKFLOW_HISTORY_PAYLOAD_KIND_SNAPSHOT,
                {
                    "candidate_profile": snapshot.get("candidate_profile") or {},
                    "job_description": snapshot.get("job_description") or {},
                    "fit_analysis": snapshot.get("fit_analysis") or {},
                    "tailored_draft": snapshot.get("tailored_draft") or {},
                    "agent_result": snapshot.get("agent_result"),
                    "imported_job_posting": snapshot.get("imported_job_posting"),
                },
            ),
            "report_payload_json": versioned_payload(
                WORKFLOW_HISTORY_PAYLOAD_KIND_REPORT,
                artifacts.get("report") or {},
            ),
            "cover_letter_payload_json": versioned_payload(
                WORKFLOW_HISTORY_PAYLOAD_KIND_COVER_LETTER,
                artifacts.get("cover_letter") or {},
            ),
            "tailored_resume_payload_json": versioned_payload(
                WORKFLOW_HISTORY_PAYLOAD_KIND_TAILORED_RESUME,
                artifacts.get("tailored_resume") or {},
            ),
        },
    )
    return {
        "status": "saved",
        "saved_workspace": {
            "job_title": record.job_title,
            "expires_at": record.expires_at,
            "updated_at": record.updated_at,
        },
    }


def load_saved_workspace_snapshot(*, access_token: str, refresh_token: str):
    context = resolve_authenticated_context(
        access_token=access_token,
        refresh_token=refresh_token,
    )
    saved_workspace_store = SavedWorkspaceStore(context.auth_service)
    if not saved_workspace_store.is_configured():
        raise RuntimeError("Saved workspace persistence is not configured.")

    record, status = saved_workspace_store.load_workspace(
        access_token,
        refresh_token,
        context.app_user.id,
    )
    if record is None:
        return {
            "status": status,
            "saved_workspace": None,
        }

    saved_snapshot = build_saved_workflow_snapshot_from_payload(
        record.workflow_snapshot_json
    )
    if saved_snapshot is None:
        raise RuntimeError(
            "The saved workspace could not be restored safely. Re-run the flow to create a fresh save."
        )

    saved_tailored_resume_artifact = build_saved_tailored_resume_from_payload(
        record.tailored_resume_payload_json
    )
    tailored_resume_artifact = build_tailored_resume_artifact(
        saved_snapshot.candidate_profile,
        saved_snapshot.job_description,
        saved_snapshot.fit_analysis,
        saved_snapshot.tailored_draft,
        agent_result=saved_snapshot.agent_result,
        theme=(
            getattr(saved_tailored_resume_artifact, "theme", None)
            or "classic_ats"
        ),
    )
    cover_letter_artifact = build_saved_cover_letter_from_payload(
        record.cover_letter_payload_json
    ) or build_cover_letter_artifact(
        saved_snapshot.candidate_profile,
        saved_snapshot.job_description,
        saved_snapshot.fit_analysis,
        saved_snapshot.tailored_draft,
        agent_result=saved_snapshot.agent_result,
    )
    report = build_saved_report_from_payload(record.report_payload_json) or build_application_report(
        saved_snapshot.candidate_profile,
        saved_snapshot.job_description,
        saved_snapshot.fit_analysis,
        saved_snapshot.tailored_draft,
        agent_result=saved_snapshot.agent_result,
    )

    workspace_snapshot = {
        "resume_document": {
            "text": saved_snapshot.candidate_profile.resume_text,
            "filetype": "Saved Workspace",
            "source": "saved_workspace",
        },
        "candidate_profile": _serialize(saved_snapshot.candidate_profile),
        "job_description": _serialize(saved_snapshot.job_description),
        "jd_summary_view": generate_job_summary_view(
            openai_service=None,
            job_description=saved_snapshot.job_description,
            imported_job_posting=saved_snapshot.imported_job_posting,
        ),
        "fit_analysis": _serialize(saved_snapshot.fit_analysis),
        "tailored_draft": _serialize(saved_snapshot.tailored_draft),
        "agent_result": _serialize(saved_snapshot.agent_result),
        "artifacts": {
            "tailored_resume": _serialize(tailored_resume_artifact),
            "cover_letter": _serialize(cover_letter_artifact),
            "report": _serialize(report),
        },
        "workflow": {
            "mode": getattr(saved_snapshot.agent_result, "mode", "") or "saved_workspace",
            "assisted_requested": bool(saved_snapshot.agent_result),
            "assisted_available": True,
            "review_approved": bool(
                getattr(getattr(saved_snapshot.agent_result, "review", None), "approved", False)
            ),
            "fallback_reason": str(
                getattr(saved_snapshot.agent_result, "fallback_reason", "") or ""
            ),
        },
        "imported_job_posting": _serialize(saved_snapshot.imported_job_posting),
    }

    return {
        "status": "available",
        "saved_workspace": {
            "job_title": record.job_title,
            "expires_at": record.expires_at,
            "updated_at": record.updated_at,
        },
        "workspace_snapshot": workspace_snapshot,
    }
