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
            [data-testid="stSidebar"][aria-expanded="true"] {
                min-width: 36rem;
                max-width: 36rem;
            }
            [data-testid="stSidebar"][aria-expanded="false"] {
                min-width: 0 !important;
                max-width: 0 !important;
                width: 0 !important;
                border-right: none;
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
            .sidebar-usage-shell {
                margin-top: 1.1rem;
                margin-bottom: 0.65rem;
            }
            .sidebar-chat-shell,
            .sidebar-account-shell {
                margin-bottom: 0.65rem;
            }
            .sidebar-usage-stat {
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(148, 163, 184, 0.14);
                border-radius: 16px;
                padding: 0.72rem 0.65rem;
                margin-bottom: 0.55rem;
            }
            .sidebar-usage-kicker {
                text-transform: uppercase;
                letter-spacing: 0.11em;
                font-size: 0.61rem;
                color: #93c5fd !important;
                font-weight: 700;
                margin-bottom: 0.24rem;
            }
            .sidebar-usage-value {
                font-size: 0.96rem;
                line-height: 1.15;
                color: #f8fbff !important;
                font-weight: 800;
                margin-bottom: 0.2rem;
            }
            .sidebar-usage-copy {
                color: #cbd5e1 !important;
                font-size: 0.7rem;
                line-height: 1.25;
            }
            .sidebar-account-topline {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 1rem;
                margin-bottom: 0.45rem;
            }
            .sidebar-account-state {
                color: #f8fbff !important;
                font-weight: 700;
                font-size: 0.92rem;
            }
            .sidebar-account-plan {
                color: #cbd5e1 !important;
                font-size: 0.82rem;
                text-align: right;
            }
            .sidebar-account-name {
                color: #f8fbff !important;
                font-weight: 700;
                font-size: 0.98rem;
                margin-bottom: 0.18rem;
            }
            .sidebar-account-email {
                color: #cbd5e1 !important;
                font-size: 0.85rem;
            }
            [data-testid="stSidebar"] .stButton > button {
                border-radius: 14px;
                min-height: 2.6rem;
                font-weight: 700;
            }
            [data-testid="stSidebar"] .stExpander {
                background: rgba(255, 255, 255, 0.05) !important;
                border: 1px solid rgba(148, 163, 184, 0.14) !important;
            }
            [data-testid="stSidebar"] .stExpander summary,
            [data-testid="stSidebar"] .stExpander label,
            [data-testid="stSidebar"] .stExpander p,
            [data-testid="stSidebar"] .stExpander div,
            [data-testid="stSidebar"] .stExpander span {
                color: #e7eefc !important;
            }
            [data-testid="stSidebar"] [data-testid="stChatMessage"] {
                background: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(148, 163, 184, 0.12);
                border-radius: 16px;
                padding: 0.55rem 0.7rem;
                margin-bottom: 0.55rem;
            }
            [data-testid="stSidebar"] [data-testid="stChatMessage"] p,
            [data-testid="stSidebar"] [data-testid="stChatMessage"] span,
            [data-testid="stSidebar"] [data-testid="stChatMessage"] div,
            [data-testid="stSidebar"] [data-testid="stChatMessage"] label {
                color: #e7eefc !important;
            }
            [data-testid="stSidebar"] .stTextInput input,
            [data-testid="stSidebar"] .stTextArea textarea,
            [data-testid="stSidebar"] div[data-baseweb="input"] input {
                background: rgba(255, 255, 255, 0.08) !important;
                color: #f8fbff !important;
                border-color: rgba(148, 163, 184, 0.18) !important;
            }
            [data-testid="stSidebar"] [data-testid="stWidgetLabel"] {
                color: #cbd5e1 !important;
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
            .deterministic-draft-card {
                background: linear-gradient(180deg, rgba(5, 12, 24, 0.98), rgba(9, 20, 38, 0.98));
                border: 1px solid rgba(96, 165, 250, 0.18);
                box-shadow: 0 18px 34px rgba(0, 0, 0, 0.22);
                border-radius: 22px;
                padding: 1.2rem 1.25rem;
                margin-bottom: 1rem;
            }
            .deterministic-draft-card,
            .deterministic-draft-card * {
                color: #eef4ff !important;
            }
            .deterministic-draft-kicker {
                text-transform: uppercase;
                letter-spacing: 0.14em;
                font-size: 0.72rem;
                font-weight: 700;
                color: #93c5fd !important;
                margin-bottom: 0.35rem;
            }
            .deterministic-draft-card h3 {
                margin: 0 0 0.45rem 0;
                color: #f8fbff !important;
            }
            .deterministic-draft-copy {
                margin: 0 0 1rem 0;
                color: #c9daf8 !important;
                line-height: 1.55;
            }
            .deterministic-draft-grid {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 1rem;
            }
            .deterministic-draft-section {
                background: rgba(148, 163, 184, 0.06);
                border: 1px solid rgba(148, 163, 184, 0.14);
                border-radius: 16px;
                padding: 0.95rem 1rem;
            }
            .deterministic-draft-section h4 {
                margin: 0 0 0.55rem 0;
                color: #f8fbff !important;
            }
            .deterministic-draft-section p,
            .deterministic-draft-section li {
                color: #d7e6ff !important;
                line-height: 1.6;
            }
            .deterministic-draft-section ul {
                margin: 0;
                padding-left: 1.2rem;
            }
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
            @media (max-width: 900px) {
                .deterministic-draft-grid {
                    grid-template-columns: 1fr;
                }
            }
            </style>
            """
        ).strip(),
        unsafe_allow_html=True,
    )
