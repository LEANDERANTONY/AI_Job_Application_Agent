import streamlit as st


CURRENT_MENU = "current_menu"
PENDING_MENU = "pending_menu"
RESUME_DOCUMENT = "resume_document"
CANDIDATE_PROFILE_RESUME = "candidate_profile_resume"
CANDIDATE_PROFILE = "candidate_profile"
JOB_DESCRIPTION_RAW = "job_description_raw"
JOB_DESCRIPTION_SOURCE = "job_description_source"
JOB_DESCRIPTION = "job_description"
FIT_ANALYSIS = "fit_analysis"
TAILORED_RESUME_DRAFT = "tailored_resume_draft"
AGENT_WORKFLOW_SIGNATURE = "agent_workflow_signature"
AGENT_WORKFLOW_RESULT = "agent_workflow_result"
APPLICATION_REPORT_SIGNATURE = "application_report_signature"
APPLICATION_REPORT_PDF_BYTES = "application_report_pdf_bytes"
COVER_LETTER_SIGNATURE = "cover_letter_signature"
COVER_LETTER_PDF_BYTES = "cover_letter_pdf_bytes"
TAILORED_RESUME_SIGNATURE = "tailored_resume_signature"
TAILORED_RESUME_PDF_BYTES = "tailored_resume_pdf_bytes"
TAILORED_RESUME_THEME = "tailored_resume_theme"
EXPORT_BUNDLE_BYTES = "export_bundle_bytes"
PENDING_BROWSER_DOWNLOAD = "pending_browser_download"
PRODUCT_HELP_CHAT_HISTORY = "product_help_chat_history"
APPLICATION_QA_CHAT_HISTORY = "application_qa_chat_history"
ASSISTANT_CHAT_HISTORY = "assistant_chat_history"
ASSISTANT_PENDING_QUESTION = "assistant_pending_question"
ASSISTANT_IS_RESPONDING = "assistant_is_responding"
ASSISTANT_CLEAR_INPUT = "assistant_clear_input"
OPENAI_SESSION_USAGE = "openai_session_usage"
AUTH_ACCESS_TOKEN = "auth_access_token"
AUTH_REFRESH_TOKEN = "auth_refresh_token"
AUTH_USER = "auth_user"
AUTH_ERROR = "auth_error"
AUTH_PKCE_CODE_VERIFIER = "auth_pkce_code_verifier"
APP_USER_RECORD = "app_user_record"
DAILY_QUOTA_STATUS = "daily_quota_status"
DAILY_QUOTA_STATUS_REFRESHED_AT = "daily_quota_status_refreshed_at"
WORKSPACE_RESTORE_NOTICE = "workspace_restore_notice"
MANUAL_JD_UTILITY_PANEL_OPEN = "manual_jd_utility_panel_open"


def get_state(key, default=None):
    return st.session_state.get(key, default)


def get_request_cookie(key, default=None):
    context = getattr(st, "context", None)
    if context is None:
        return default
    try:
        cookies = context.cookies
    except Exception:
        return default
    if cookies is None:
        return default
    try:
        return cookies.get(key, default)
    except Exception:
        return default


def set_state(key, value):
    st.session_state[key] = value
    return value


def pop_state(key, default=None):
    return st.session_state.pop(key, default)


def ensure_state(key, default):
    if key not in st.session_state:
        st.session_state[key] = default
    return st.session_state[key]


def get_current_menu(default_menu):
    return ensure_state(CURRENT_MENU, default_menu)


def set_current_menu(menu_name):
    return set_state(CURRENT_MENU, menu_name)


def request_menu_navigation(menu_name):
    return set_state(PENDING_MENU, menu_name)


def consume_pending_menu():
    return pop_state(PENDING_MENU, None)


def get_openai_session_usage(default_max_calls=None, default_max_total_tokens=None):
    return ensure_state(
        OPENAI_SESSION_USAGE,
        {
            "request_count": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "max_calls": default_max_calls,
            "max_total_tokens": default_max_total_tokens,
            "remaining_calls": default_max_calls,
            "remaining_total_tokens": default_max_total_tokens,
            "last_response_metadata": {},
        },
    )


def set_openai_session_usage(usage):
    return set_state(OPENAI_SESSION_USAGE, usage)


def get_auth_tokens():
    return get_state(AUTH_ACCESS_TOKEN), get_state(AUTH_REFRESH_TOKEN)


def set_authenticated_session(auth_session):
    set_state(AUTH_ACCESS_TOKEN, auth_session.access_token)
    set_state(AUTH_REFRESH_TOKEN, auth_session.refresh_token)
    set_state(AUTH_USER, auth_session.user)
    pop_state(AUTH_ERROR, None)
    return auth_session.user


def get_authenticated_user():
    return get_state(AUTH_USER)


def is_authenticated():
    return get_authenticated_user() is not None


def clear_authenticated_session():
    pop_state(AUTH_ACCESS_TOKEN, None)
    pop_state(AUTH_REFRESH_TOKEN, None)
    pop_state(APP_USER_RECORD, None)
    pop_state(DAILY_QUOTA_STATUS, None)
    pop_state(DAILY_QUOTA_STATUS_REFRESHED_AT, None)
    pop_state(WORKSPACE_RESTORE_NOTICE, None)
    return pop_state(AUTH_USER, None)


def get_manual_jd_utility_panel_open(default=True):
    return ensure_state(MANUAL_JD_UTILITY_PANEL_OPEN, default)


def set_manual_jd_utility_panel_open(is_open):
    return set_state(MANUAL_JD_UTILITY_PANEL_OPEN, bool(is_open))


def set_auth_error(message):
    if message:
        return set_state(AUTH_ERROR, message)
    return pop_state(AUTH_ERROR, None)


def get_auth_error():
    return get_state(AUTH_ERROR)


def get_auth_pkce_code_verifier():
    return get_state(AUTH_PKCE_CODE_VERIFIER)


def set_auth_pkce_code_verifier(code_verifier):
    if code_verifier:
        return set_state(AUTH_PKCE_CODE_VERIFIER, code_verifier)
    return pop_state(AUTH_PKCE_CODE_VERIFIER, None)


def get_app_user_record():
    return get_state(APP_USER_RECORD)


def set_app_user_record(app_user_record):
    if app_user_record is None:
        return pop_state(APP_USER_RECORD, None)
    return set_state(APP_USER_RECORD, app_user_record)


def get_daily_quota_status():
    return get_state(DAILY_QUOTA_STATUS)


def set_daily_quota_status(daily_quota_status):
    if daily_quota_status is None:
        pop_state(DAILY_QUOTA_STATUS_REFRESHED_AT, None)
        return pop_state(DAILY_QUOTA_STATUS, None)
    return set_state(DAILY_QUOTA_STATUS, daily_quota_status)


def get_daily_quota_status_refreshed_at():
    return get_state(DAILY_QUOTA_STATUS_REFRESHED_AT)


def set_daily_quota_status_refreshed_at(refreshed_at):
    if refreshed_at is None:
        return pop_state(DAILY_QUOTA_STATUS_REFRESHED_AT, None)
    return set_state(DAILY_QUOTA_STATUS_REFRESHED_AT, refreshed_at)


def get_workspace_restore_notice():
    return get_state(WORKSPACE_RESTORE_NOTICE)


def set_workspace_restore_notice(notice):
    if notice is None:
        return pop_state(WORKSPACE_RESTORE_NOTICE, None)
    return set_state(WORKSPACE_RESTORE_NOTICE, notice)


def store_resume_intake(resume_document, candidate_profile_resume):
    set_state(RESUME_DOCUMENT, resume_document)
    set_state(CANDIDATE_PROFILE_RESUME, candidate_profile_resume)


def store_job_description_inputs(raw_text, source_label, job_description):
    set_state(JOB_DESCRIPTION_RAW, raw_text)
    set_state(JOB_DESCRIPTION_SOURCE, source_label)
    set_state(JOB_DESCRIPTION, job_description)


def store_fit_outputs(fit_analysis, tailored_resume_draft):
    set_state(FIT_ANALYSIS, fit_analysis)
    set_state(TAILORED_RESUME_DRAFT, tailored_resume_draft)


def set_active_candidate_profile(candidate_profile):
    return set_state(CANDIDATE_PROFILE, candidate_profile)


def reset_agent_workflow_if_signature_changed(signature):
    if get_state(AGENT_WORKFLOW_SIGNATURE) != signature:
        pop_state(AGENT_WORKFLOW_RESULT, None)
        set_state(AGENT_WORKFLOW_SIGNATURE, signature)


def set_agent_workflow_result(agent_workflow_result):
    return set_state(AGENT_WORKFLOW_RESULT, agent_workflow_result)


def sync_report_signature(signature):
    if get_state(APPLICATION_REPORT_SIGNATURE) != signature:
        set_state(APPLICATION_REPORT_SIGNATURE, signature)
        pop_state(APPLICATION_REPORT_PDF_BYTES, None)
        pop_state(EXPORT_BUNDLE_BYTES, None)


def sync_cover_letter_signature(signature):
    if get_state(COVER_LETTER_SIGNATURE) != signature:
        set_state(COVER_LETTER_SIGNATURE, signature)
        pop_state(COVER_LETTER_PDF_BYTES, None)
        pop_state(EXPORT_BUNDLE_BYTES, None)


def get_cached_pdf_bytes():
    return get_state(APPLICATION_REPORT_PDF_BYTES)


def set_cached_pdf_bytes(pdf_bytes):
    return set_state(APPLICATION_REPORT_PDF_BYTES, pdf_bytes)


def get_cached_cover_letter_pdf_bytes():
    return get_state(COVER_LETTER_PDF_BYTES)


def set_cached_cover_letter_pdf_bytes(pdf_bytes):
    return set_state(COVER_LETTER_PDF_BYTES, pdf_bytes)


def sync_tailored_resume_signature(signature):
    if get_state(TAILORED_RESUME_SIGNATURE) != signature:
        set_state(TAILORED_RESUME_SIGNATURE, signature)
        pop_state(TAILORED_RESUME_PDF_BYTES, None)
        pop_state(EXPORT_BUNDLE_BYTES, None)


def get_cached_tailored_resume_pdf_bytes(theme_name=None):
    cached_value = get_state(TAILORED_RESUME_PDF_BYTES)
    if theme_name is None:
        if isinstance(cached_value, dict):
            active_theme = get_tailored_resume_theme()
            return cached_value.get(active_theme)
        return cached_value

    if isinstance(cached_value, dict):
        return cached_value.get(theme_name)

    active_theme = get_tailored_resume_theme()
    if cached_value is not None and theme_name == active_theme:
        return cached_value
    return None


def set_cached_tailored_resume_pdf_bytes(pdf_bytes, theme_name=None):
    if theme_name is None:
        return set_state(TAILORED_RESUME_PDF_BYTES, pdf_bytes)

    cached_value = get_state(TAILORED_RESUME_PDF_BYTES)
    if isinstance(cached_value, dict):
        next_value = dict(cached_value)
    elif cached_value is None:
        next_value = {}
    else:
        next_value = {get_tailored_resume_theme(): cached_value}
    next_value[theme_name] = pdf_bytes
    return set_state(TAILORED_RESUME_PDF_BYTES, next_value)


def get_tailored_resume_theme(default_theme="classic_ats"):
    return ensure_state(TAILORED_RESUME_THEME, default_theme)


def set_tailored_resume_theme(theme_name):
    return set_state(TAILORED_RESUME_THEME, theme_name)


def get_cached_export_bundle_bytes():
    return get_state(EXPORT_BUNDLE_BYTES)


def set_cached_export_bundle_bytes(bundle_bytes):
    return set_state(EXPORT_BUNDLE_BYTES, bundle_bytes)


def get_pending_browser_download():
    return get_state(PENDING_BROWSER_DOWNLOAD)


def set_pending_browser_download(payload):
    if payload is None:
        return pop_state(PENDING_BROWSER_DOWNLOAD, None)
    return set_state(PENDING_BROWSER_DOWNLOAD, payload)


def consume_pending_browser_download():
    return pop_state(PENDING_BROWSER_DOWNLOAD, None)


def _assistant_history_key(mode_name):
    if mode_name in {"product_help", "application_qa", "assistant", None, ""}:
        return ASSISTANT_CHAT_HISTORY
    return ASSISTANT_CHAT_HISTORY


def get_assistant_history(mode_name):
    return ensure_state(_assistant_history_key(mode_name), [])


def append_assistant_turn(mode_name, turn):
    history = list(get_assistant_history(mode_name))
    history.append(turn)
    return set_state(_assistant_history_key(mode_name), history)


def clear_assistant_history(mode_name):
    return set_state(_assistant_history_key(mode_name), [])


def get_pending_assistant_question():
    return get_state(ASSISTANT_PENDING_QUESTION)


def set_pending_assistant_question(question):
    if question is None:
        return pop_state(ASSISTANT_PENDING_QUESTION, None)
    return set_state(ASSISTANT_PENDING_QUESTION, question)


def is_assistant_responding():
    return bool(get_state(ASSISTANT_IS_RESPONDING, False))


def set_assistant_responding(is_responding):
    if not is_responding:
        return pop_state(ASSISTANT_IS_RESPONDING, None)
    return set_state(ASSISTANT_IS_RESPONDING, True)


def should_clear_assistant_input():
    return bool(get_state(ASSISTANT_CLEAR_INPUT, False))


def set_clear_assistant_input(should_clear):
    if not should_clear:
        return pop_state(ASSISTANT_CLEAR_INPUT, None)
    return set_state(ASSISTANT_CLEAR_INPUT, True)
