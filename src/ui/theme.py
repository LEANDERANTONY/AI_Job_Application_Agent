import textwrap

import streamlit as st


def apply_theme():
    st.markdown(
        textwrap.dedent(
            """
            <style>
            :root {
                --page-ink: #e7eefc;
                --ink: #142033;
                --muted: #5b6b83;
                --surface-line: rgba(20, 32, 51, 0.14);
                --accent-strong: #2563eb;
                --shadow: 0 24px 48px rgba(0, 0, 0, 0.34);
            }
            .stApp {
                background:
                    radial-gradient(circle at top left, rgba(37, 99, 235, 0.22), transparent 26%),
                    radial-gradient(circle at top right, rgba(14, 165, 233, 0.14), transparent 24%),
                    linear-gradient(180deg, #070a10 0%, #0b1220 48%, #05070c 100%);
            }
            .block-container {
                max-width: 1220px;
                padding-top: 2rem;
                padding-bottom: 3rem;
            }
            .stApp, .stMarkdown, .stMarkdown p, .stMarkdown li, .stCaption,
            [data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li,
            [data-testid="stWidgetLabel"] p, [data-testid="stRadio"] label,
            [data-testid="stCheckbox"] label, [data-testid="stFileUploaderDropzoneInstructions"] {
                color: var(--page-ink);
            }
            h1, h2, h3, h4 { color: var(--page-ink); letter-spacing: -0.02em; }
            [data-testid="stSidebar"] {
                background: linear-gradient(180deg, rgba(7, 10, 16, 0.96), rgba(11, 18, 32, 0.98));
                border-right: 1px solid rgba(148, 163, 184, 0.14);
            }
            [data-testid="stSidebar"] * { color: var(--page-ink) !important; }
            .app-hero, .section-head, .metric-card {
                background: #ffffff !important;
                border: 1px solid var(--surface-line);
                box-shadow: var(--shadow);
            }
            .app-hero {
                border-radius: 24px;
                padding: 1.4rem 1.5rem;
                margin-bottom: 1rem;
            }
            .app-kicker, .metric-label {
                text-transform: uppercase;
                letter-spacing: 0.12em;
                font-weight: 700;
            }
            .app-kicker {
                font-size: 0.72rem;
                color: var(--accent-strong);
                margin-bottom: 0.35rem;
            }
            .app-hero h1 { color: var(--ink); margin: 0 0 0.4rem 0; }
            .app-copy {
                color: #2563eb !important;
                font-size: 1rem;
                line-height: 1.6;
                font-weight: 500;
                margin: 0;
            }
            .section-head {
                border-radius: 18px;
                padding: 0.95rem 1rem;
                margin-bottom: 0.8rem;
            }
            .section-head h4 { margin: 0 0 0.2rem 0; color: var(--ink) !important; }
            .section-meta, .metric-note { color: var(--muted) !important; }
            .metric-card {
                border-radius: 18px;
                padding: 1rem 1rem 0.9rem;
                min-height: 130px;
                margin-bottom: 0.8rem;
            }
            .metric-label {
                font-size: 0.74rem;
                color: var(--muted);
                margin-bottom: 0.35rem;
            }
            .metric-value {
                font-size: 1.85rem;
                font-weight: 800;
                color: var(--ink);
                line-height: 1.08;
                margin-bottom: 0.4rem;
            }
            .sidebar-card, .narrative-panel {
                border-radius: 18px;
                padding: 0.95rem;
                margin-bottom: 0.9rem;
            }
            .sidebar-card {
                background: rgba(255, 255, 255, 0.06);
                border: 1px solid rgba(148, 163, 184, 0.16);
            }
            .sidebar-kicker {
                text-transform: uppercase;
                letter-spacing: 0.12em;
                font-size: 0.7rem;
                color: #93c5fd !important;
                font-weight: 700;
                margin-bottom: 0.3rem;
            }
            .narrative-panel {
                background: linear-gradient(180deg, rgba(5, 12, 24, 0.98), rgba(9, 20, 38, 0.98));
                border: 1px solid rgba(96, 165, 250, 0.16);
                box-shadow: 0 18px 34px rgba(0, 0, 0, 0.22);
            }
            .narrative-panel, .narrative-panel * { color: #eef4ff !important; }
            .narrative-panel h4 { color: #f8fbff !important; margin: 0 0 0.45rem 0; }
            .stTextInput input, .stTextArea textarea, div[data-baseweb="input"] input, div[data-baseweb="select"] > div {
                background: #ffffff !important;
                color: var(--ink) !important;
                border-color: rgba(20, 32, 51, 0.14) !important;
            }
            .stButton > button, .stFormSubmitButton > button, .stDownloadButton > button {
                background: var(--accent-strong) !important;
                color: #f8fafc !important;
                border: 1px solid var(--accent-strong) !important;
            }
            .stExpander {
                border: 1px solid var(--surface-line) !important;
                border-radius: 18px !important;
                background: #ffffff !important;
                overflow: hidden;
            }
            .stExpander * { color: var(--ink) !important; }
            </style>
            """
        ).strip(),
        unsafe_allow_html=True,
    )
