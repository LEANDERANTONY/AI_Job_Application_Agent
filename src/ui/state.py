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


def get_cached_pdf_bytes():
    return get_state(APPLICATION_REPORT_PDF_BYTES)


def set_cached_pdf_bytes(pdf_bytes):
    return set_state(APPLICATION_REPORT_PDF_BYTES, pdf_bytes)