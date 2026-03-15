import streamlit as st

from src.errors import AppError
from src.ui import workflow
from src.ui.state import CURRENT_MENU, consume_pending_menu, get_current_menu, set_current_menu
from src.ui.state import (
    clear_authenticated_session,
    get_app_user_record,
    get_auth_error,
    get_auth_tokens,
    get_authenticated_user,
    get_workspace_restore_notice,
    set_auth_error,
    set_workspace_restore_notice,
)


MENU_OPTIONS = [
    "Upload Resume",
    "Job Search",
    "Manual JD Input",
    "Saved Workspace",
]

MENU_COPY = {
    "Upload Resume": "Parse a resume and keep it ready for tailoring.",
    "Job Search": "Placeholder for job-source integrations and matching.",
    "Manual JD Input": "Load a target role and extract structured requirements.",
    "Saved Workspace": "Review or download your latest 24-hour saved workspace.",
}


def _render_account_panel(auth_service):
    st.markdown("### Account")

    auth_error = get_auth_error()
    if auth_error:
        st.warning(auth_error)

    user = get_authenticated_user()
    app_user = get_app_user_record()
    restore_notice = get_workspace_restore_notice()
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
        if st.button("Reload Saved Workspace", key="reload_saved_workspace"):
            result = workflow.restore_latest_saved_workspace()
            if result.get("level") == "success":
                st.rerun()
        if restore_notice:
            level = str(restore_notice.get("level", "info") or "info").lower()
            message = str(restore_notice.get("message", "") or "")
            if message:
                if level == "success":
                    st.success(message)
                elif level == "warning":
                    st.warning(message)
                else:
                    st.info(message)
        return

    if restore_notice:
        set_workspace_restore_notice(None)

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
        pending_menu = consume_pending_menu()
        if pending_menu is not None:
            set_current_menu(pending_menu)
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
                    Deployment hardening, expiring saved workspaces, and reliable export regeneration.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return menu
