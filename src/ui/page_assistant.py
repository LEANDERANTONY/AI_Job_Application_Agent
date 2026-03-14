import streamlit as st

from src.assistant_service import AssistantService
from src.schemas import AssistantTurn
from src.ui.components import render_section_head
from src.ui.state import append_assistant_turn, clear_assistant_history, get_assistant_history


def render_assistant_panel(current_page, workflow_view_model=None, artifact=None, report=None):
    st.markdown("---")
    render_section_head(
        "Ask The Assistant",
        "Use product help for navigation questions or ask grounded questions about the current resume and report.",
    )

    mode_options = ["product_help"]
    if workflow_view_model and workflow_view_model.candidate_profile and workflow_view_model.job_description:
        mode_options.append("application_qa")

    page_slug = current_page.lower().replace(" ", "_")
    mode_labels = {
        "product_help": "Using the App",
        "application_qa": "About My Resume",
    }
    mode = st.radio(
        "Assistant Mode",
        mode_options,
        horizontal=True,
        key="assistant_mode_{page}".format(page=page_slug),
        format_func=lambda value: mode_labels[value],
    )

    history = get_assistant_history(mode)
    for turn in history:
        with st.chat_message("user"):
            st.write(turn.question)
        with st.chat_message("assistant"):
            st.write(turn.response.answer)
            if turn.response.sources:
                st.caption("Sources: " + ", ".join(turn.response.sources))

    question = st.text_input(
        "Ask a question",
        key="assistant_question_{page}_{mode}".format(page=page_slug, mode=mode),
        placeholder=(
            "Ask how to use the app..."
            if mode == "product_help"
            else "Ask about your resume, JD, or report..."
        ),
    )
    ask_col, clear_col = st.columns(2)
    with ask_col:
        ask_clicked = st.button(
            "Ask Assistant",
            key="ask_assistant_{page}_{mode}".format(page=page_slug, mode=mode),
        )
    with clear_col:
        clear_clicked = st.button(
            "Clear Chat",
            key="clear_assistant_{page}_{mode}".format(page=page_slug, mode=mode),
        )

    if clear_clicked:
        clear_assistant_history(mode)
        st.rerun()

    if ask_clicked and question.strip():
        openai_service = None
        if workflow_view_model and workflow_view_model.ai_session:
            openai_service = workflow_view_model.ai_session.openai_service
        assistant = AssistantService(openai_service=openai_service)
        if mode == "product_help":
            response = assistant.answer_product_help(
                question,
                current_page=current_page,
                history=history,
                app_context={
                    "available_pages": ["Upload Resume", "Job Search", "Manual JD Input"],
                    "has_resume": bool(workflow_view_model and workflow_view_model.candidate_profile),
                    "has_job_description": bool(workflow_view_model and workflow_view_model.job_description),
                    "has_tailored_resume": bool(artifact),
                    "has_report": bool(report),
                },
            )
        else:
            response = assistant.answer_application_qa(
                question,
                workflow_view_model,
                report=report,
                artifact=artifact,
                history=history,
            )
        append_assistant_turn(
            mode,
            AssistantTurn(mode=mode, question=question.strip(), response=response),
        )
        st.rerun()