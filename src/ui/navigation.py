import streamlit as st

from src.errors import AppError
from src.ui.state import CURRENT_MENU, get_current_menu
from src.ui.state import (
    clear_authenticated_session,
    get_app_user_record,
    get_artifact_history,
    get_auth_error,
    get_auth_tokens,
    get_authenticated_user,
    get_workflow_history,
    set_auth_error,
)


MENU_OPTIONS = [
    "Upload Resume",
    "Job Search",
    "Manual JD Input",
    "History",
]

MENU_COPY = {
    "Upload Resume": "Parse a resume and keep it ready for tailoring.",
    "Job Search": "Placeholder for job-source integrations and matching.",
    "Manual JD Input": "Load a target role and extract structured requirements.",
    "History": "Review authenticated workflow runs and export history.",
}


def _render_account_panel(auth_service):
    st.markdown("### Account")

    auth_error = get_auth_error()
    if auth_error:
        st.warning(auth_error)

    user = get_authenticated_user()
    app_user = get_app_user_record()
    if user is not None:
        st.markdown("**Signed in**")
        st.write(user.display_name or user.email or user.user_id)
        if user.email and user.display_name:
            st.caption(user.email)
        if app_user is not None:
            st.caption(
                "Plan: {plan} | Status: {status}".format(
                    plan=app_user.plan_tier,
                    status=app_user.account_status,
                )
            )
        if st.button("Sign Out", key="sign_out_google"):
            access_token, refresh_token = get_auth_tokens()
            try:
                if access_token and refresh_token and auth_service.is_configured():
                    auth_service.sign_out(access_token, refresh_token)
            except AppError as error:
                set_auth_error(error.user_message)
            finally:
                clear_authenticated_session()
                st.rerun()
        workflow_history = get_workflow_history()
        if workflow_history:
            with st.expander("Recent Workflow Runs", expanded=False):
                for workflow_run in workflow_history[:5]:
                    status = "Approved" if workflow_run.review_approved else "Review Pending"
                    st.markdown(
                        "**{job}**".format(job=workflow_run.job_title or "Target Role")
                    )
                    st.caption(
                        "Fit {score}/100 | {status} | {created}".format(
                            score=workflow_run.fit_score,
                            status=status,
                            created=workflow_run.created_at or "unknown time",
                        )
                    )
        artifact_history = get_artifact_history()
        if artifact_history:
            with st.expander("Recent Artifacts", expanded=False):
                for artifact in artifact_history[:5]:
                    st.markdown("**{kind}**".format(kind=artifact.artifact_type or "artifact"))
                    st.caption(
                        "{name} | {created}".format(
                            name=artifact.filename_stem or "unnamed-artifact",
                            created=artifact.created_at or "unknown time",
                        )
                    )
        return

    st.caption(
        "Sign in with Google to unlock the assisted workflow and persistent account state."
    )
    if not auth_service.is_configured():
        st.info(
            "Set SUPABASE_URL, SUPABASE_ANON_KEY, and SUPABASE_AUTH_REDIRECT_URL to enable Google sign-in."
        )
        return

    try:
        sign_in_url = auth_service.get_google_sign_in_url()
    except AppError as error:
        st.warning(error.user_message)
        return

    st.link_button("Continue With Google", sign_in_url, use_container_width=True)


def render_sidebar(auth_service):
    with st.sidebar:
        st.markdown(
            """
            <div class="sidebar-card">
                <div class="sidebar-kicker">Workspace</div>
                <div style="font-size:1.02rem; font-weight:700;">AI Job Application Agent</div>
                <div style="font-size:0.92rem; color:#cbd5e1; margin-top:0.35rem;">
                    Streamlit-first, backend-ready application workflow.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.title("Navigation")
        get_current_menu(MENU_OPTIONS[0])
        menu = st.radio(
            "Go to:",
            MENU_OPTIONS,
            key=CURRENT_MENU,
            label_visibility="collapsed",
        )
        _render_account_panel(auth_service)
        st.caption(MENU_COPY[menu])
        st.markdown(
            """
            <div class="sidebar-card">
                <div class="sidebar-kicker">Current Focus</div>
                <div style="font-size:0.92rem; color:#cbd5e1;">
                    Deployment hardening, authenticated history, and reliable export regeneration.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return menu
