import streamlit as st


CURRENT_MENU = "current_menu"
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
TAILORED_RESUME_SIGNATURE = "tailored_resume_signature"
TAILORED_RESUME_PDF_BYTES = "tailored_resume_pdf_bytes"
TAILORED_RESUME_THEME = "tailored_resume_theme"
EXPORT_BUNDLE_BYTES = "export_bundle_bytes"
PRODUCT_HELP_CHAT_HISTORY = "product_help_chat_history"
APPLICATION_QA_CHAT_HISTORY = "application_qa_chat_history"
OPENAI_SESSION_USAGE = "openai_session_usage"


def get_state(key, default=None):
    return st.session_state.get(key, default)


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


def get_openai_session_usage(default_max_calls, default_max_total_tokens):
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


def get_cached_pdf_bytes():
    return get_state(APPLICATION_REPORT_PDF_BYTES)


def set_cached_pdf_bytes(pdf_bytes):
    return set_state(APPLICATION_REPORT_PDF_BYTES, pdf_bytes)


def sync_tailored_resume_signature(signature):
    if get_state(TAILORED_RESUME_SIGNATURE) != signature:
        set_state(TAILORED_RESUME_SIGNATURE, signature)
        pop_state(TAILORED_RESUME_PDF_BYTES, None)
        pop_state(EXPORT_BUNDLE_BYTES, None)


def get_cached_tailored_resume_pdf_bytes():
    return get_state(TAILORED_RESUME_PDF_BYTES)


def set_cached_tailored_resume_pdf_bytes(pdf_bytes):
    return set_state(TAILORED_RESUME_PDF_BYTES, pdf_bytes)


def get_tailored_resume_theme(default_theme="classic_ats"):
    return ensure_state(TAILORED_RESUME_THEME, default_theme)


def set_tailored_resume_theme(theme_name):
    return set_state(TAILORED_RESUME_THEME, theme_name)


def get_cached_export_bundle_bytes():
    return get_state(EXPORT_BUNDLE_BYTES)


def set_cached_export_bundle_bytes(bundle_bytes):
    return set_state(EXPORT_BUNDLE_BYTES, bundle_bytes)


def _assistant_history_key(mode_name):
    return {
        "product_help": PRODUCT_HELP_CHAT_HISTORY,
        "application_qa": APPLICATION_QA_CHAT_HISTORY,
    }.get(mode_name, PRODUCT_HELP_CHAT_HISTORY)


def get_assistant_history(mode_name):
    return ensure_state(_assistant_history_key(mode_name), [])


def append_assistant_turn(mode_name, turn):
    history = list(get_assistant_history(mode_name))
    history.append(turn)
    return set_state(_assistant_history_key(mode_name), history)


def clear_assistant_history(mode_name):
    return set_state(_assistant_history_key(mode_name), [])