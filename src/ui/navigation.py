from html import escape

import streamlit as st

from src.errors import AppError
from src.ui import workflow
from src.ui.state import CURRENT_MENU, consume_pending_menu, get_current_menu, set_current_menu
from src.ui.state import (
    JOB_DESCRIPTION_RAW,
    JOB_DESCRIPTION_SOURCE,
    clear_authenticated_session,
    get_app_user_record,
    get_auth_error,
    get_auth_tokens,
    get_authenticated_user,
    get_state,
    get_workspace_restore_notice,
    set_auth_error,
    set_workspace_restore_notice,
)


MENU_OPTIONS = [
    "Upload Resume",
    "Job Search",
    "Manual JD Input",
]

MENU_COPY = {
    "Upload Resume": "Parse a resume and keep it ready for tailoring.",
    "Job Search": "Placeholder for job-source integrations and matching.",
    "Manual JD Input": "Load a target role and extract structured requirements.",
}

MENU_SHORT_LABELS = {
    "Upload Resume": "Resume",
    "Job Search": "Job Application",
    "Manual JD Input": "Job Description",
}


def _format_remaining_capacity(remaining, limit):
    if limit is None or remaining is None:
        return "Unlimited"
    return str(remaining)


def _render_sidebar_usage_stat(kicker, value, detail):
    st.markdown(
        """
        <div class="sidebar-usage-stat">
            <div class="sidebar-usage-kicker">{kicker}</div>
            <div class="sidebar-usage-value">{value}</div>
            <div class="sidebar-usage-copy">{detail}</div>
        </div>
        """.format(
            kicker=escape(kicker),
            value=escape(value),
            detail=escape(detail),
        ),
        unsafe_allow_html=True,
    )


def _render_sidebar_nav_grid(current_menu):
    return st.radio(
        "Go to:",
        MENU_OPTIONS,
        key=CURRENT_MENU,
        horizontal=True,
        label_visibility="collapsed",
        format_func=lambda option: MENU_SHORT_LABELS[option],
    )


def _render_sidebar_assistant_panel(menu):
    workflow_view_model = workflow.build_job_workflow_view_model(
        get_state(JOB_DESCRIPTION_RAW, ""),
        get_state(JOB_DESCRIPTION_SOURCE, ""),
    )
    artifact = workflow.build_tailored_resume_artifact_view_model(workflow_view_model)
    report = workflow.build_application_report_view_model(workflow_view_model)

    st.markdown(
        """
        <div class="sidebar-card sidebar-chat-shell">
            <div class="sidebar-kicker">Assistant</div>
            <div style="font-size:0.92rem; color:#e7eefc; font-weight:700; margin-bottom:0.1rem;">
                Ask about the app, your resume, or the current outputs
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.expander("Open Chat", expanded=True):
        from src.ui.page_assistant import render_assistant_panel

        render_assistant_panel(
            menu,
            workflow_view_model=workflow_view_model,
            artifact=artifact,
            report=report,
            show_divider=False,
            show_header=False,
            compact=True,
        )


def _render_sidebar_usage_panel(menu):
    if menu != "Manual JD Input":
        return

    ai_session = workflow.build_ai_session_view_model()
    daily_quota = ai_session.daily_quota
    usage = ai_session.usage

    st.markdown(
        """
        <div class="sidebar-card sidebar-usage-shell">
            <div class="sidebar-kicker">Usage</div>
            <div style="font-size:0.92rem; color:#e7eefc; font-weight:700; margin-bottom:0.1rem;">
                Assisted workflow budget
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if daily_quota:
        top_row = st.columns(4, gap="small")
        with top_row[0]:
            _render_sidebar_usage_stat(
                "Daily Runs",
                _format_remaining_capacity(daily_quota.remaining_calls, daily_quota.max_calls),
                "UTC-day runs left.",
            )
        with top_row[1]:
            _render_sidebar_usage_stat(
                "Daily Capacity",
                _format_remaining_capacity(
                    daily_quota.remaining_total_tokens,
                    daily_quota.max_total_tokens,
                ),
                "UTC-day token budget left.",
            )
        with top_row[2]:
            _render_sidebar_usage_stat(
                "Session Runs",
                _format_remaining_capacity(usage.get("remaining_calls"), usage.get("max_calls")),
                "Browser-session runs left.",
            )
        with top_row[3]:
            _render_sidebar_usage_stat(
                "Session Capacity",
                _format_remaining_capacity(
                    usage.get("remaining_total_tokens"),
                    usage.get("max_total_tokens"),
                ),
                "Browser-session token budget left.",
            )
        if daily_quota.quota_exhausted:
            st.warning(
                "Your daily assisted quota is exhausted. The backup workflow is still available until the next UTC reset."
            )
    else:
        st.caption("Sign in to see account-level daily quota and keep assisted usage tied to your plan.")

    if not daily_quota:
        session_row = st.columns(2, gap="small")
        with session_row[0]:
            _render_sidebar_usage_stat(
                "Session Runs",
                _format_remaining_capacity(usage.get("remaining_calls"), usage.get("max_calls")),
                "Browser-session runs left.",
            )
        with session_row[1]:
            _render_sidebar_usage_stat(
                "Session Capacity",
                _format_remaining_capacity(
                    usage.get("remaining_total_tokens"),
                    usage.get("max_total_tokens"),
                ),
                "Browser-session token budget left.",
            )

    if ai_session.budget_reached and ai_session.openai_service.is_available():
        st.warning(
            "This browser session has reached its assisted limit. The workflow will continue in backup mode."
        )


def _render_account_panel(auth_service):
    st.markdown("### Account")

    auth_error = get_auth_error()
    if auth_error:
        st.warning(auth_error)

    user = get_authenticated_user()
    app_user = get_app_user_record()
    restore_notice = get_workspace_restore_notice()
    if user is not None:
        account_name = user.display_name or user.email or user.user_id
        account_email = user.email or ""
        plan_tier = app_user.plan_tier if app_user is not None else "Unknown"
        account_status = app_user.account_status if app_user is not None else "Unknown"
        account_identity = account_email or account_name
        st.markdown(
            """
            <div class="sidebar-card sidebar-account-shell">
                <div class="sidebar-account-row">
                    <div class="sidebar-account-summary">Signed in as {identity}</div>
                    <div class="sidebar-account-plan">Plan {plan} | {status}</div>
                </div>
            </div>
            """.format(
                identity=escape(str(account_identity)),
                plan=escape(str(plan_tier)),
                status=escape(str(account_status)),
            ),
            unsafe_allow_html=True,
        )
        account_actions = st.columns(2, gap="small")
        with account_actions[0]:
            sign_out_clicked = st.button("Sign Out", key="sign_out_google", use_container_width=True)
        with account_actions[1]:
            reload_clicked = st.button("Reload Workspace", key="reload_saved_workspace", use_container_width=True)

        if sign_out_clicked:
            access_token, refresh_token = get_auth_tokens()
            try:
                if access_token and refresh_token and auth_service.is_configured():
                    auth_service.sign_out(access_token, refresh_token)
            except AppError as error:
                set_auth_error(error.user_message)
            finally:
                clear_authenticated_session()
                st.rerun()

        if reload_clicked:
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
                <div style="font-size:1.02rem; font-weight:700;">Application Copilot</div>
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
        current_menu = get_current_menu(MENU_OPTIONS[0])
        if current_menu not in MENU_OPTIONS:
            current_menu = set_current_menu(MENU_OPTIONS[0])
        menu = _render_sidebar_nav_grid(current_menu)
        st.caption(MENU_COPY[menu])
        _render_account_panel(auth_service)
        _render_sidebar_usage_panel(menu)
        _render_sidebar_assistant_panel(menu)
        return menu
