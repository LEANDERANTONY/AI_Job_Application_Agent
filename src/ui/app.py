import streamlit as st

from src.errors import AppError, InputValidationError, ParsingError
from src.logging_utils import configure_logging, get_logger, log_event
from src.user_store import AppUserStore
from src.ui.components import (
    render_evolution_note,
    render_footer,
    render_intro,
)
from src.ui.navigation import render_sidebar
from src.ui.pages import (
    render_history_page,
    render_job_description_page,
    render_job_search_page,
    render_resume_page,
)
from src.ui.state import (
    clear_authenticated_session,
    get_auth_tokens,
    get_authenticated_user,
    set_app_user_record,
    set_auth_error,
    set_authenticated_session,
)
from src.ui.auth import get_auth_service
from src.ui.theme import apply_theme


LOGGER = get_logger(__name__)


def _query_param_value(key):
    value = st.query_params.get(key)
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _clear_auth_query_params():
    for key in ("code", "error", "error_code", "error_description"):
        try:
            del st.query_params[key]
        except KeyError:
            continue


def _initialize_auth():
    auth_service = get_auth_service()
    user_store = AppUserStore(auth_service)
    auth_error = _query_param_value("error_description") or _query_param_value("error")
    auth_code = _query_param_value("code")
    auth_flow = _query_param_value("auth_flow")

    if auth_error:
        clear_authenticated_session()
        set_auth_error(str(auth_error))
        _clear_auth_query_params()
        log_event(
            LOGGER,
            30,
            "auth_callback_error",
            "OAuth callback returned an error.",
            error=str(auth_error),
        )

    if auth_code and auth_service.is_configured():
        try:
            session = auth_service.exchange_code_for_session(str(auth_code), auth_flow=str(auth_flow) if auth_flow else None)
            set_authenticated_session(session)
            set_auth_error(None)
            set_app_user_record(None)
            try:
                set_app_user_record(user_store.sync_user_record(session))
            except AppError as sync_error:
                log_event(
                    LOGGER,
                    30,
                    "app_user_sync_failed",
                    "Authenticated user could not be synced to app_users during sign-in.",
                    user_id=session.user.user_id,
                    error=sync_error.user_message,
                    details=sync_error.details,
                )
            log_event(
                LOGGER,
                20,
                "auth_sign_in_success",
                "Google sign-in completed successfully.",
                user_id=session.user.user_id,
                email=session.user.email,
            )
        except AppError as error:
            clear_authenticated_session()
            set_auth_error(error.user_message)
            log_event(
                LOGGER,
                30,
                "auth_sign_in_failed",
                "Google sign-in failed during code exchange.",
                error=error.user_message,
            )
        finally:
            _clear_auth_query_params()
            st.rerun()

    if auth_service.is_configured() and get_authenticated_user() is None:
        access_token, refresh_token = get_auth_tokens()
        if access_token and refresh_token:
            try:
                session = auth_service.restore_session(access_token, refresh_token)
                set_authenticated_session(session)
                set_app_user_record(None)
                try:
                    set_app_user_record(user_store.sync_user_record(session))
                except AppError as sync_error:
                    log_event(
                        LOGGER,
                        30,
                        "app_user_sync_failed",
                        "Authenticated user could not be synced to app_users during session restore.",
                        user_id=session.user.user_id,
                        error=sync_error.user_message,
                        details=sync_error.details,
                    )
            except AppError as error:
                clear_authenticated_session()
                set_auth_error(error.user_message)
                log_event(
                    LOGGER,
                    30,
                    "auth_session_restore_failed",
                    "Stored auth session could not be restored.",
                    error=error.user_message,
                )

    return auth_service


def main():
    configure_logging()
    st.set_page_config(
        page_title="AI Job Application Agent",
        page_icon="AI",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    apply_theme()
    auth_service = _initialize_auth()
    menu = render_sidebar(auth_service=auth_service)
    render_intro()

    render_evolution_note()

    try:
        if menu == "Upload Resume":
            render_resume_page()
        elif menu == "Job Search":
            render_job_search_page()
        elif menu == "Manual JD Input":
            render_job_description_page()
        elif menu == "Saved Workspace":
            render_history_page()
        else:
            raise InputValidationError("Unknown navigation target.")
    except ParsingError as error:
        log_event(
            LOGGER,
            40,
            "ui_parsing_error",
            "Parsing error reached UI boundary.",
            error_type=type(error).__name__,
            details=error.details,
        )
        st.error(error.user_message)
    except AppError as error:
        log_event(
            LOGGER,
            30,
            "ui_app_error",
            "Application error reached UI boundary.",
            error_type=type(error).__name__,
            details=error.details,
        )
        st.warning(error.user_message)
    except Exception as error:
        log_event(
            LOGGER,
            40,
            "ui_unhandled_error",
            "Unhandled exception reached UI boundary.",
            error_type=type(error).__name__,
        )
        st.error(str(error))

    render_footer()
