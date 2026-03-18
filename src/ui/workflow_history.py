from src.cover_letter_builder import build_cover_letter_artifact
from src.report_builder import build_application_report
from src.resume_builder import build_tailored_resume_artifact
from src.saved_workspace_store import SavedWorkspaceStore
from src.ui.auth import get_auth_service
from src.ui.state import (
    get_app_user_record,
    get_auth_tokens,
    get_tailored_resume_theme,
)
from src.ui.workflow_payloads import (
    WORKFLOW_HISTORY_PAYLOAD_KIND_COVER_LETTER,
    WORKFLOW_HISTORY_PAYLOAD_KIND_REPORT,
    WORKFLOW_HISTORY_PAYLOAD_KIND_TAILORED_RESUME,
    json_payload,
    workflow_snapshot_json,
)
from src.ui.workflow_signatures import workflow_signature


def persist_workflow_run(view_model):
    auth_user_record = get_app_user_record()
    access_token, refresh_token = get_auth_tokens()
    if auth_user_record is None or not access_token or not refresh_token:
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
    cover_letter_artifact = build_cover_letter_artifact(
        view_model.candidate_profile,
        view_model.job_description,
        view_model.fit_analysis,
        view_model.tailored_draft,
        agent_result=view_model.agent_result,
    )

    saved_workspace_store = SavedWorkspaceStore(get_auth_service())
    if not saved_workspace_store.is_configured():
        return None

    saved_workspace = saved_workspace_store.save_workspace(
        access_token,
        refresh_token,
        {
            "user_id": auth_user_record.id,
            "job_title": view_model.job_description.title if view_model.job_description else "",
            "workflow_signature": workflow_signature(
                view_model.candidate_profile,
                view_model.job_description,
                view_model.fit_analysis,
                view_model.tailored_draft,
            ),
            "workflow_snapshot_json": workflow_snapshot_json(view_model),
            "report_payload_json": json_payload(WORKFLOW_HISTORY_PAYLOAD_KIND_REPORT, report),
            "cover_letter_payload_json": json_payload(
                WORKFLOW_HISTORY_PAYLOAD_KIND_COVER_LETTER,
                cover_letter_artifact,
            ),
            "tailored_resume_payload_json": json_payload(
                WORKFLOW_HISTORY_PAYLOAD_KIND_TAILORED_RESUME,
                tailored_resume_artifact,
            ),
        },
    )
    return saved_workspace
