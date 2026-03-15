import streamlit as st

from src.exporters import export_markdown_bytes, export_pdf_bytes, export_zip_bundle_bytes
from src.ui.components import render_download_button, render_metric_card, render_section_head
from src.ui.state import (
    get_app_user_record,
    get_daily_quota_status,
    is_authenticated,
)
from src.ui.workflow import (
    load_saved_workspace_summary,
    refresh_daily_quota_status,
    restore_latest_saved_workspace,
)


def _format_history_timestamp(raw_timestamp):
    if not raw_timestamp:
        return "Unknown time"
    return str(raw_timestamp).replace("T", " ").replace("+00:00", " UTC")


def _build_saved_workspace_explainer(has_saved_workspace: bool):
    lines = [
        "This page is for inspection and download regeneration of your latest saved workspace.",
        "Use Reload Saved Workspace when you want to push that saved snapshot back into Manual JD Input and continue working from it.",
    ]
    if has_saved_workspace:
        lines.append("Your latest successful workflow run has a saved snapshot available right now.")
    else:
        lines.append("No saved snapshot is available yet, so the page stays informational until you run the supervised workflow while signed in.")
    return lines


def render_history_page(render_daily_quota_status):
    render_section_head(
        "Saved Workspace",
        "Review or download the latest reloadable workspace saved to your account.",
    )

    if not is_authenticated():
        st.info(
            "Sign in with Google from the sidebar to load your latest saved workspace."
        )
        return

    if st.button("Refresh Saved Workspace", key="refresh_saved_workspace_page"):
        daily_quota = refresh_daily_quota_status(force=True)
    else:
        daily_quota = get_daily_quota_status() or refresh_daily_quota_status()

    saved_workspace = load_saved_workspace_summary()

    st.info(
        "\n".join(_build_saved_workspace_explainer(bool(saved_workspace["record"])))
    )
    st.caption(
        "Each new successful workflow run overwrites the previous saved workspace, and the save expires after 24 hours by default."
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
            "Saved Workspace",
            "Available" if saved_workspace["record"] else "Not Saved",
            "Only the latest successful workflow run is kept as a reloadable saved workspace.",
        )
    with cols[3]:
        render_metric_card(
            "Saved Status",
            saved_workspace["status"].replace("_", " ").title(),
            "Expired saves are deleted when the user tries to reload or inspect them after expiry.",
        )

    if saved_workspace["status"] == "expired":
        st.warning(
            "Your saved workspace expired after 24 hours and has been cleared. Re-run the workflow to create a fresh save."
        )
        return
    if saved_workspace["record"] is None:
        st.caption(
            "No saved workspace is available yet. Run the supervised workflow once while signed in, then return here."
        )
        return

    record = saved_workspace["record"]
    snapshot = saved_workspace.get("snapshot")
    saved_report = saved_workspace.get("report")
    saved_resume = saved_workspace.get("resume")

    status_cols = st.columns(4)
    with status_cols[0]:
        render_metric_card(
            "Target Role",
            record.job_title or "Unknown",
            "Latest role saved for explicit reload and download regeneration.",
        )
    with status_cols[1]:
        render_metric_card(
            "Updated",
            _format_history_timestamp(record.updated_at),
            "Each successful workflow run overwrites the prior saved workspace.",
        )
    with status_cols[2]:
        render_metric_card(
            "Expires",
            _format_history_timestamp(record.expires_at),
            "After expiry the saved workspace is no longer reloadable.",
        )
    with status_cols[3]:
        render_metric_card(
            "Reload Action",
            "Page Or Sidebar",
            "Reload from here or from the sidebar to restore this snapshot into Manual JD Input.",
        )

    if st.button("Reload This Saved Workspace", key="reload_saved_workspace_page_action"):
        result = restore_latest_saved_workspace()
        if result.get("level") == "success":
            st.rerun()

    if snapshot and snapshot.fit_analysis:
        fit_score = getattr(snapshot.fit_analysis, "overall_score", 0)
        readiness = getattr(snapshot.fit_analysis, "readiness_label", "Unknown")
        st.caption(
            "Saved fit snapshot: {score}/100 with readiness marked as {label}.".format(
                score=fit_score,
                label=readiness,
            )
        )

    if saved_report or saved_resume:
        st.caption(
            "Downloads below are regenerated from the current saved workspace payloads, not from your current in-session inputs."
        )
    if saved_report:
        render_download_button(
            "Download Saved Report Markdown",
            data=export_markdown_bytes(saved_report),
            file_name=saved_report.filename_stem + ".md",
            mime="text/markdown",
            key="saved_workspace_report_markdown",
        )
        render_download_button(
            "Download Saved Report PDF",
            data=export_pdf_bytes(saved_report),
            file_name=saved_report.filename_stem + ".pdf",
            mime="application/pdf",
            key="saved_workspace_report_pdf",
        )
    if saved_resume:
        render_download_button(
            "Download Saved Tailored Resume Markdown",
            data=export_markdown_bytes(saved_resume),
            file_name=saved_resume.filename_stem + ".md",
            mime="text/markdown",
            key="saved_workspace_resume_markdown",
        )
        render_download_button(
            "Download Saved Tailored Resume PDF",
            data=export_pdf_bytes(saved_resume),
            file_name=saved_resume.filename_stem + ".pdf",
            mime="application/pdf",
            key="saved_workspace_resume_pdf",
        )
    if saved_report and saved_resume:
        render_download_button(
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
            key="saved_workspace_bundle",
        )