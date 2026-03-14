import streamlit as st

from src.ui.state import CURRENT_MENU, get_current_menu


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


def render_sidebar():
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
        st.caption(MENU_COPY[menu])
        st.markdown(
            """
            <div class="sidebar-card">
                <div class="sidebar-kicker">Current Focus</div>
                <div style="font-size:0.92rem; color:#cbd5e1;">
                    Parser hardening, modular UI, and preparation for the first real agent workflow.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return menu
