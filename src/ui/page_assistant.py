import streamlit as st
from streamlit.errors import StreamlitAPIException

from src.assistant_service import AssistantService
from src.product_knowledge import retrieve_product_knowledge
from src.schemas import AssistantTurn
from src.ui.components import render_section_head
from src.ui.state import (
    append_assistant_turn,
    clear_assistant_session_memory,
    clear_assistant_history,
    get_assistant_history,
    get_pending_assistant_question,
    get_assistant_session_response_id,
    get_assistant_session_signature,
    is_authenticated,
    is_assistant_responding,
    set_assistant_responding,
    set_assistant_session_response_id,
    set_assistant_session_signature,
    set_clear_assistant_input,
    set_openai_session_usage,
    set_pending_assistant_question,
    set_state,
    should_clear_assistant_input,
)
from src.ui.workflow import build_ai_session_view_model


def _resolve_assistant_ai_session(workflow_view_model=None):
    if workflow_view_model and workflow_view_model.ai_session:
        return workflow_view_model.ai_session
    return build_ai_session_view_model()


def _build_product_help_context(workflow_view_model=None, artifact=None, report=None, ai_session=None):
    daily_quota = getattr(ai_session, "daily_quota", None)
    agent_result = getattr(workflow_view_model, "agent_result", None) if workflow_view_model else None
    signed_in = is_authenticated()
    return {
        "available_pages": [
            "Upload Resume",
            "Job Search",
            "Manual JD Input",
        ],
        "signed_in_actions": ["Reload Workspace"] if signed_in else [],
        "is_authenticated": signed_in,
        "resume_upload_requires_login": True,
        "resume_upload_available": signed_in,
        "has_resume": bool(workflow_view_model and workflow_view_model.candidate_profile),
        "has_job_description": bool(workflow_view_model and workflow_view_model.job_description),
        "has_tailored_resume": bool(artifact),
        "has_report": bool(report),
        "has_cover_letter": bool(agent_result and getattr(agent_result, "cover_letter", None)),
        "assistant_requires_login": True,
        "daily_quota": {
            "plan_tier": None if not daily_quota else daily_quota.plan_tier,
            "remaining_calls": None if not daily_quota else daily_quota.remaining_calls,
            "remaining_total_tokens": None if not daily_quota else daily_quota.remaining_total_tokens,
            "quota_exhausted": bool(daily_quota and daily_quota.quota_exhausted),
        },
    }


def _build_product_help_context_for_question(
    question,
    *,
    current_page,
    workflow_view_model=None,
    artifact=None,
    report=None,
    ai_session=None,
):
    return {
        "current_page": current_page,
        **_build_product_help_context(
            workflow_view_model=workflow_view_model,
            artifact=artifact,
            report=report,
            ai_session=ai_session,
        ),
        "knowledge_hits": retrieve_product_knowledge(question, current_page=current_page),
    }


def _build_assistant_context_for_question(
    question,
    *,
    current_page,
    workflow_view_model=None,
    artifact=None,
    report=None,
    ai_session=None,
):
    return _build_product_help_context_for_question(
        question,
        current_page=current_page,
        workflow_view_model=workflow_view_model,
        artifact=artifact,
        report=report,
        ai_session=ai_session,
    )


def _submit_assistant_question(
    *,
    current_page,
    question,
    history,
    workflow_view_model=None,
    artifact=None,
    report=None,
):
    normalized_question = str(question or "").strip()
    if not normalized_question:
        return False
    if not is_authenticated():
        return False

    ai_session = _resolve_assistant_ai_session(workflow_view_model)
    openai_service = ai_session.openai_service if ai_session else None
    assistant = AssistantService(openai_service=openai_service)
    current_session_context = AssistantService.build_session_context(
        current_page=current_page,
        workflow_view_model=workflow_view_model,
        report=report,
        artifact=artifact,
        app_context=_build_product_help_context(
            workflow_view_model=workflow_view_model,
            artifact=artifact,
            report=report,
            ai_session=ai_session,
        ),
    )
    current_session_signature = AssistantService.build_session_signature(current_session_context)
    if get_assistant_session_signature() != current_session_signature:
        clear_assistant_session_memory()
        set_assistant_session_signature(current_session_signature)
    response = assistant.answer(
        normalized_question,
        current_page=current_page,
        workflow_view_model=workflow_view_model,
        report=report,
        artifact=artifact,
        history=history,
        app_context=_build_assistant_context_for_question(
            normalized_question,
            current_page=current_page,
            workflow_view_model=workflow_view_model,
            artifact=artifact,
            report=report,
            ai_session=ai_session,
        ),
        previous_response_id=get_assistant_session_response_id(),
    )
    if ai_session and ai_session.openai_service:
        set_openai_session_usage(ai_session.openai_service.get_usage_snapshot())
        response_id = (
            ai_session.openai_service.get_usage_snapshot()
            .get("last_response_metadata", {})
            .get("response_id")
        )
        if response_id:
            set_assistant_session_response_id(response_id)
    append_assistant_turn(
        "assistant",
        AssistantTurn(mode="assistant", question=normalized_question, response=response),
    )
    return True


def _assistant_question_key(page_slug):
    return "assistant_question_{page}".format(page=page_slug)


def _queue_assistant_question(*, page_slug, question=None):
    normalized_question = str(question or "").strip()
    if not normalized_question:
        return False
    set_pending_assistant_question(normalized_question)
    set_assistant_responding(True)
    return True


def _handle_assistant_enter_submit(page_slug):
    _queue_assistant_question(
        page_slug=page_slug,
        question=st.session_state.get(_assistant_question_key(page_slug), ""),
    )


def _render_assistant_loading_indicator(compact=False):
    size = "0.78rem" if compact else "0.9rem"
    st.markdown(
        """
        <div style="display:flex; align-items:center; gap:0.45rem; min-height:1.6rem; margin:0.25rem 0 0.6rem; color:#93c5fd; font-size:0.88rem;">
            <div style="width:{size}; height:{size}; border-radius:999px; border:2px solid rgba(37,99,235,0.22); border-top-color:#2563eb; animation: assistant-spin 0.85s linear infinite;"></div>
            <span>Generating response...</span>
        </div>
        <style>
        @keyframes assistant-spin {{
            from {{ transform: rotate(0deg); }}
            to {{ transform: rotate(360deg); }}
        }}
        </style>
        """.format(size=size),
        unsafe_allow_html=True,
    )


def _rerun_assistant_panel(*, compact=False):
    if compact:
        try:
            st.rerun(scope="fragment")
            return
        except StreamlitAPIException:
            pass
    st.rerun()


def _ensure_assistant_session_ready(
    *,
    current_page,
    workflow_view_model=None,
    artifact=None,
    report=None,
    compact=False,
):
    ai_session = _resolve_assistant_ai_session(workflow_view_model)
    openai_service = ai_session.openai_service if ai_session else None
    if openai_service is None or not openai_service.is_available():
        return

    base_context = _build_product_help_context(
        workflow_view_model=workflow_view_model,
        artifact=artifact,
        report=report,
        ai_session=ai_session,
    )
    session_context = AssistantService.build_session_context(
        current_page=current_page,
        workflow_view_model=workflow_view_model,
        report=report,
        artifact=artifact,
        app_context=base_context,
    )
    session_signature = AssistantService.build_session_signature(session_context)
    existing_signature = get_assistant_session_signature()
    existing_response_id = get_assistant_session_response_id()

    if existing_signature != session_signature:
        clear_assistant_session_memory()
        set_assistant_session_signature(session_signature)
        existing_response_id = None

    if existing_response_id:
        return

    assistant = AssistantService(openai_service=openai_service)
    with st.spinner("Preparing assistant context..."):
        response_id = assistant.prepare_session(
            current_page=current_page,
            workflow_view_model=workflow_view_model,
            report=report,
            artifact=artifact,
            app_context=base_context,
        )
    if response_id:
        set_assistant_session_response_id(response_id)
        set_openai_session_usage(openai_service.get_usage_snapshot())
        _rerun_assistant_panel(compact=compact)


def _render_assistant_panel_contents(
    current_page,
    workflow_view_model=None,
    artifact=None,
    report=None,
    *,
    show_divider=True,
    show_header=True,
    compact=False,
):
    if show_divider:
        st.markdown("---")
    if show_header:
        render_section_head(
            "Ask The Assistant",
            "Ask about the app, your current fit analysis, tailored resume, cover letter, or application package.",
        )
    if not is_authenticated():
        st.info("This feature can only be used after logging in.")
        return

    _ensure_assistant_session_ready(
        current_page=current_page,
        workflow_view_model=workflow_view_model,
        artifact=artifact,
        report=report,
        compact=compact,
    )

    page_slug = current_page.lower().replace(" ", "_")
    question_key = _assistant_question_key(page_slug)

    if should_clear_assistant_input():
        set_state(question_key, "")
        set_clear_assistant_input(False)

    history = get_assistant_history("assistant")
    pending_question = get_pending_assistant_question()
    is_generating = is_assistant_responding()
    turns_to_render = history
    for turn in turns_to_render:
        with st.chat_message("user"):
            st.write(turn.question)
        with st.chat_message("assistant"):
            st.write(turn.response.answer)

    if pending_question and is_generating:
        with st.chat_message("user"):
            st.write(pending_question)
        with st.chat_message("assistant"):
            _render_assistant_loading_indicator(compact=compact)

    question = st.text_input(
        "Ask a question",
        key=question_key,
        placeholder=(
            "Ask about the app, your resume, or the current outputs..."
            if compact
            else "Ask about the app, your resume, the cover letter, or the report..."
        ),
        on_change=_handle_assistant_enter_submit,
        args=(page_slug,),
        disabled=is_generating,
        label_visibility="collapsed" if compact else "visible",
    )

    ask_clicked = st.button(
        "Ask" if compact else "Ask Assistant",
        key="assistant_submit_{page}".format(page=page_slug),
        use_container_width=True,
        disabled=is_generating,
    )

    if compact:
        clear_clicked = st.button(
            "Clear",
            key="clear_assistant_{page}".format(page=page_slug),
            use_container_width=True,
        )
    else:
        clear_clicked = st.button(
            "Clear Chat",
            key="clear_assistant_{page}".format(page=page_slug),
            use_container_width=True,
        )

    if clear_clicked:
        clear_assistant_history("assistant")
        clear_assistant_session_memory()
        set_pending_assistant_question(None)
        set_assistant_responding(False)
        set_clear_assistant_input(True)
        _rerun_assistant_panel(compact=compact)

    if ask_clicked:
        if _queue_assistant_question(page_slug=page_slug, question=question):
            _rerun_assistant_panel(compact=compact)

    if pending_question and is_generating:
        if _submit_assistant_question(
            current_page=current_page,
            question=pending_question,
            history=history,
            workflow_view_model=workflow_view_model,
            artifact=artifact,
            report=report,
        ):
            set_pending_assistant_question(None)
            set_assistant_responding(False)
            set_clear_assistant_input(True)
            _rerun_assistant_panel(compact=compact)


@st.fragment
def _render_compact_assistant_panel_fragment(
    current_page,
    workflow_view_model=None,
    artifact=None,
    report=None,
):
    _render_assistant_panel_contents(
        current_page,
        workflow_view_model=workflow_view_model,
        artifact=artifact,
        report=report,
        show_divider=False,
        show_header=False,
        compact=True,
    )


def render_assistant_panel(
    current_page,
    workflow_view_model=None,
    artifact=None,
    report=None,
    *,
    show_divider=True,
    show_header=True,
    compact=False,
):
    if compact:
        _render_compact_assistant_panel_fragment(
            current_page,
            workflow_view_model=workflow_view_model,
            artifact=artifact,
            report=report,
        )
        return

    _render_assistant_panel_contents(
        current_page,
        workflow_view_model=workflow_view_model,
        artifact=artifact,
        report=report,
        show_divider=show_divider,
        show_header=show_header,
        compact=compact,
    )
