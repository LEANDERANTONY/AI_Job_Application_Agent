from typing import Optional

from src.history_store import HistoryStore
from src.report_builder import build_application_report
from src.resume_builder import build_tailored_resume_artifact
from src.ui.auth import get_auth_service
from src.ui.state import (
    get_app_user_record,
    get_artifact_history,
    get_auth_tokens,
    get_active_workflow_run,
    get_tailored_resume_theme,
    get_selected_history_workflow_run_id,
    set_active_workflow_run,
    set_artifact_history,
    set_selected_history_workflow_run_id,
    set_workflow_history,
)
from src.ui.workflow_payloads import (
    WORKFLOW_HISTORY_PAYLOAD_KIND_REPORT,
    WORKFLOW_HISTORY_PAYLOAD_KIND_TAILORED_RESUME,
    build_saved_report_from_payload,
    build_saved_tailored_resume_from_payload,
    json_payload,
    workflow_snapshot_json,
)
from src.ui.workflow_signatures import workflow_signature


def persist_workflow_run(view_model):
    auth_user_record = get_app_user_record()
    access_token, refresh_token = get_auth_tokens()
    if auth_user_record is None or not access_token or not refresh_token:
        return None

    history_store = HistoryStore(get_auth_service())
    if not history_store.is_configured():
        return None

    report = build_application_report(
        view_model.candidate_profile,
        view_model.job_description,
        view_model.fit_analysis,
        view_model.tailored_draft,
        agent_result=view_model.agent_result,
    )
    tailored_resume_artifact = build_tailored_resume_artifact(
        view_model.candidate_profile,
        view_model.job_description,
        view_model.fit_analysis,
        view_model.tailored_draft,
        agent_result=view_model.agent_result,
        theme=get_tailored_resume_theme(),
    )

    workflow_run = history_store.create_workflow_run(
        access_token,
        refresh_token,
        {
            "user_id": auth_user_record.id,
            "job_title": view_model.job_description.title if view_model.job_description else "",
            "fit_score": view_model.fit_analysis.overall_score if view_model.fit_analysis else 0,
            "review_approved": bool(view_model.agent_result and view_model.agent_result.review.approved),
            "model_policy": view_model.agent_result.model if view_model.agent_result else "",
            "workflow_signature": workflow_signature(
                view_model.candidate_profile,
                view_model.job_description,
                view_model.fit_analysis,
                view_model.tailored_draft,
            ),
            "workflow_snapshot_json": workflow_snapshot_json(view_model),
            "report_payload_json": json_payload(WORKFLOW_HISTORY_PAYLOAD_KIND_REPORT, report),
            "tailored_resume_payload_json": json_payload(
                WORKFLOW_HISTORY_PAYLOAD_KIND_TAILORED_RESUME,
                tailored_resume_artifact,
            ),
        },
    )
    set_selected_history_workflow_run_id(workflow_run.id)
    set_active_workflow_run(workflow_run)
    refresh_authenticated_history(str(workflow_run.id))
    return workflow_run


def persist_artifact_record(artifact_type: str, filename_stem: str, storage_path: str = ""):
    active_workflow_run = get_active_workflow_run()
    access_token, refresh_token = get_auth_tokens()
    if active_workflow_run is None or not access_token or not refresh_token:
        return get_artifact_history()

    history_store = HistoryStore(get_auth_service())
    if not history_store.is_configured():
        return get_artifact_history()

    history_store.create_artifact_record(
        access_token,
        refresh_token,
        {
            "workflow_run_id": active_workflow_run.id,
            "artifact_type": artifact_type,
            "filename_stem": filename_stem,
            "storage_path": storage_path,
        },
    )
    artifacts = history_store.list_recent_artifacts(
        access_token,
        refresh_token,
        active_workflow_run.id,
    )
    set_artifact_history(artifacts)
    return artifacts


def refresh_authenticated_history(selected_workflow_run_id: Optional[str] = None):
    auth_user_record = get_app_user_record()
    access_token, refresh_token = get_auth_tokens()
    if auth_user_record is None or not access_token or not refresh_token:
        set_workflow_history([])
        set_artifact_history([])
        set_selected_history_workflow_run_id(None)
        return [], []

    history_store = HistoryStore(get_auth_service())
    if not history_store.is_configured():
        return [], []

    workflow_runs = history_store.list_recent_workflow_runs(
        access_token,
        refresh_token,
        auth_user_record.id,
        limit=10,
    )
    set_workflow_history(workflow_runs)

    selected_id = str(
        selected_workflow_run_id
        or get_selected_history_workflow_run_id()
        or getattr(get_active_workflow_run(), "id", "")
        or ""
    )
    selected_workflow_run = None
    if selected_id:
        selected_workflow_run = next(
            (workflow_run for workflow_run in workflow_runs if str(workflow_run.id) == selected_id),
            None,
        )
    if selected_workflow_run is None and workflow_runs:
        selected_workflow_run = workflow_runs[0]

    if selected_workflow_run is None:
        set_selected_history_workflow_run_id(None)
        set_artifact_history([])
        return workflow_runs, []

    set_selected_history_workflow_run_id(selected_workflow_run.id)
    artifacts = history_store.list_recent_artifacts(
        access_token,
        refresh_token,
        str(selected_workflow_run.id),
        limit=20,
    )
    set_artifact_history(artifacts)
    return workflow_runs, artifacts


def build_saved_report_from_workflow_run(workflow_run: Optional[object]):
    if workflow_run is None or not getattr(workflow_run, "report_payload_json", ""):
        return None
    return build_saved_report_from_payload(workflow_run.report_payload_json)


def build_saved_tailored_resume_from_workflow_run(workflow_run: Optional[object]):
    if workflow_run is None or not getattr(workflow_run, "tailored_resume_payload_json", ""):
        return None
    return build_saved_tailored_resume_from_payload(workflow_run.tailored_resume_payload_json)