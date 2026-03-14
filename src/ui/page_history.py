import streamlit as st

from src.exporters import export_markdown_bytes, export_pdf_bytes, export_zip_bundle_bytes
from src.ui.components import render_metric_card, render_section_head
from src.ui.state import (
    get_active_workflow_run,
    get_app_user_record,
    get_artifact_history,
    get_daily_quota_status,
    get_selected_history_workflow_run_id,
    get_workflow_history,
    is_authenticated,
)
from src.ui.workflow import (
    build_saved_report_from_workflow_run,
    build_saved_tailored_resume_from_workflow_run,
    get_saved_workflow_payload_status,
    refresh_authenticated_history,
    refresh_daily_quota_status,
)


def _format_history_timestamp(raw_timestamp):
    if not raw_timestamp:
        return "Unknown time"
    return str(raw_timestamp).replace("T", " ").replace("+00:00", " UTC")


def _format_artifact_label(artifact_type):
    return str(artifact_type or "artifact").replace("_", " ").title()


def render_history_page(render_daily_quota_status):
    render_section_head(
        "History",
        "Review authenticated workflow runs and the export metadata saved to your account.",
    )

    if not is_authenticated():
        st.info(
            "Sign in with Google from the sidebar to load your saved workflow runs and export history."
        )
        return

    if st.button("Refresh Saved History", key="refresh_saved_history"):
        workflow_history, artifact_history = refresh_authenticated_history()
        daily_quota = refresh_daily_quota_status()
    else:
        workflow_history = get_workflow_history()
        artifact_history = get_artifact_history()
        daily_quota = get_daily_quota_status() or refresh_daily_quota_status()
        if workflow_history and not get_selected_history_workflow_run_id():
            workflow_history, artifact_history = refresh_authenticated_history()

    st.info(
        "Browsing saved history is read-only. It does not replace your current resume, current JD, or the active workflow run used for new exports."
    )

    if daily_quota:
        st.markdown("### Account Quota")
        render_daily_quota_status(daily_quota)
        st.caption(
            "This quota is tied to your signed-in account. Browser-session usage safeguards appear on the active job-description workflow page."
        )

    app_user = get_app_user_record()
    cols = st.columns(4)
    with cols[0]:
        render_metric_card(
            "Plan Tier",
            app_user.plan_tier if app_user else "Unknown",
            "Authenticated account plan used for daily assisted quota enforcement.",
        )
    with cols[1]:
        render_metric_card(
            "Account Status",
            app_user.account_status if app_user else "Unknown",
            "Current persisted app account status from Supabase.",
        )
    with cols[2]:
        render_metric_card(
            "Saved Runs",
            str(len(workflow_history)),
            "Recent assisted workflow runs persisted for this authenticated user.",
        )
    with cols[3]:
        render_metric_card(
            "Visible Artifacts",
            str(len(artifact_history)),
            "Artifacts linked to the currently selected workflow run.",
        )

    if not workflow_history:
        st.caption(
            "No saved workflow runs are available yet. Run the assisted workflow once while signed in, then return here."
        )
        return

    selected_run_id = str(get_selected_history_workflow_run_id() or workflow_history[0].id)
    selected_workflow_run = next(
        (
            workflow_run
            for workflow_run in workflow_history
            if str(workflow_run.id) == selected_run_id
        ),
        workflow_history[0],
    )

    left_col, right_col = st.columns([0.95, 1.25])
    with left_col:
        st.subheader("Workflow Runs")
        for workflow_run in workflow_history:
            is_selected = str(workflow_run.id) == str(selected_workflow_run.id)
            st.markdown(
                "**{job}**".format(job=workflow_run.job_title or "Target Role")
            )
            st.caption(
                "Fit {score}/100 | {status} | {created}".format(
                    score=workflow_run.fit_score,
                    status="Approved" if workflow_run.review_approved else "Review Pending",
                    created=_format_history_timestamp(workflow_run.created_at),
                )
            )
            if st.button(
                "Selected Run" if is_selected else "Open Run",
                key="history_run_{run_id}".format(run_id=workflow_run.id),
            ):
                workflow_history, artifact_history = refresh_authenticated_history(
                    str(workflow_run.id)
                )
                selected_workflow_run = next(
                    (
                        run
                        for run in workflow_history
                        if str(run.id) == str(workflow_run.id)
                    ),
                    workflow_run,
                )
            st.markdown("---")

    with right_col:
        st.subheader("Selected Run")
        render_metric_card(
            "Fit Score",
            "{score}/100".format(score=selected_workflow_run.fit_score),
            "Stored fit score at the time this workflow run completed.",
        )
        payload_status = get_saved_workflow_payload_status(selected_workflow_run)
        status_cols = st.columns(3)
        with status_cols[0]:
            render_metric_card(
                "Review Status",
                "Approved" if selected_workflow_run.review_approved else "Pending",
                "Final review outcome recorded for this run.",
            )
        with status_cols[1]:
            render_metric_card(
                "Model Policy",
                selected_workflow_run.model_policy or "Deterministic",
                "Model tier recorded for the workflow result.",
            )
        with status_cols[2]:
            render_metric_card(
                "Payload Format",
                payload_status["label"],
                "Saved historical downloads are rebuilt only when the payload format is supported.",
            )

        st.caption(
            "Created: {created}".format(
                created=_format_history_timestamp(selected_workflow_run.created_at)
            )
        )
        st.caption(payload_status["message"])

        active_workflow_run = get_active_workflow_run()
        if active_workflow_run and str(active_workflow_run.id) == str(selected_workflow_run.id):
            st.caption(
                "This selected historical run is also the current active run for new export tracking."
            )
        else:
            st.caption(
                "New exports still attach to the current active workflow run, not to this historical selection."
            )
        saved_report = build_saved_report_from_workflow_run(selected_workflow_run)
        saved_resume = build_saved_tailored_resume_from_workflow_run(selected_workflow_run)
        if not payload_status["supported"]:
            st.warning(
                "Historical downloads are unavailable for this run because the saved payload format is not currently compatible."
            )
        if saved_report or saved_resume:
            st.caption(
                "Historical downloads below are regenerated from the saved run content, not from your current resume or current JD inputs."
            )
        if saved_report and payload_status["supported"]:
            st.download_button(
                "Download Saved Report Markdown",
                data=export_markdown_bytes(saved_report),
                file_name=saved_report.filename_stem + ".md",
                mime="text/markdown",
                key="history_saved_report_markdown_{run_id}".format(run_id=selected_workflow_run.id),
            )
            st.download_button(
                "Download Saved Report PDF",
                data=export_pdf_bytes(saved_report),
                file_name=saved_report.filename_stem + ".pdf",
                mime="application/pdf",
                key="history_saved_report_pdf_{run_id}".format(run_id=selected_workflow_run.id),
            )
        if saved_resume and payload_status["supported"]:
            st.download_button(
                "Download Saved Tailored Resume Markdown",
                data=export_markdown_bytes(saved_resume),
                file_name=saved_resume.filename_stem + ".md",
                mime="text/markdown",
                key="history_saved_resume_markdown_{run_id}".format(run_id=selected_workflow_run.id),
            )
            st.download_button(
                "Download Saved Tailored Resume PDF",
                data=export_pdf_bytes(saved_resume),
                file_name=saved_resume.filename_stem + ".pdf",
                mime="application/pdf",
                key="history_saved_resume_pdf_{run_id}".format(run_id=selected_workflow_run.id),
            )
        if saved_report and saved_resume and payload_status["supported"]:
            st.download_button(
                "Download Saved Export Bundle",
                data=export_zip_bundle_bytes(
                    {
                        saved_report.filename_stem + ".md": export_markdown_bytes(saved_report),
                        saved_report.filename_stem + ".pdf": export_pdf_bytes(saved_report),
                        saved_resume.filename_stem + ".md": export_markdown_bytes(saved_resume),
                        saved_resume.filename_stem + ".pdf": export_pdf_bytes(saved_resume),
                    }
                ),
                file_name=saved_resume.filename_stem.replace("-tailored-resume", "-application-bundle") + ".zip",
                mime="application/zip",
                key="history_saved_bundle_{run_id}".format(run_id=selected_workflow_run.id),
            )
        st.markdown("### Artifacts")
        if artifact_history:
            for artifact in artifact_history:
                st.markdown(
                    "**{label}**".format(
                        label=_format_artifact_label(artifact.artifact_type)
                    )
                )
                st.caption(
                    "{name} | {created}".format(
                        name=artifact.filename_stem or "unnamed-artifact",
                        created=_format_history_timestamp(artifact.created_at),
                    )
                )
                if artifact.storage_path:
                    st.text(artifact.storage_path)
        else:
            st.caption(
                "No artifacts have been recorded for this run yet. Prepare a PDF or ZIP export to populate this list."
            )