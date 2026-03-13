import streamlit as st

from src.errors import AppError, InputValidationError, ParsingError
from src.ui.components import (
    render_evolution_note,
    render_footer,
    render_intro,
    render_metric_card,
)
from src.ui.navigation import render_sidebar
from src.ui.pages import (
    render_job_description_page,
    render_job_search_page,
    render_linkedin_page,
    render_resume_page,
)
from src.ui.theme import apply_theme


def main():
    st.set_page_config(
        page_title="AI Job Application Agent",
        page_icon="AI",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    apply_theme()
    menu = render_sidebar()
    render_intro()

    cols = st.columns(3)
    with cols[0]:
        render_metric_card(
            "Resume Intake",
            "Ready",
            "PDF, DOCX, and TXT parsing are in place.",
        )
    with cols[1]:
        render_metric_card(
            "LinkedIn Import",
            "Ready",
            "ZIP-based profile ingestion is available now.",
        )
    with cols[2]:
        render_metric_card(
            "Application Package",
            "Ready",
            "The JD flow now supports supervised orchestration plus Markdown and TXT package export.",
        )

    render_evolution_note()

    try:
        if menu == "Upload Resume":
            render_resume_page()
        elif menu == "Build from LinkedIn":
            render_linkedin_page()
        elif menu == "Job Search":
            render_job_search_page()
        elif menu == "Manual JD Input":
            render_job_description_page()
        else:
            raise InputValidationError("Unknown navigation target.")
    except ParsingError as error:
        st.error(error.user_message)
    except AppError as error:
        st.warning(error.user_message)
    except Exception as error:
        st.error(str(error))

    render_footer()
