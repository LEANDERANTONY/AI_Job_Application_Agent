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
            [data-testid="collapsedControl"],
            button[kind="header"][aria-label*="sidebar" i] {
                display: none !important;
            }
            [data-testid="stSidebarCollapseButton"] {
                display: flex !important;
            }
            [data-testid="stSidebar"] * { color: var(--page-ink) !important; }
            .app-hero, .section-head, .metric-card {
                background: #ffffff !important;
                border: 1px solid var(--surface-line);
                box-shadow: var(--shadow);
            }
            .app-hero {
                border-radius: 24px;
                padding: 1.02rem 1.3rem;
                margin-bottom: 0.82rem;
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
            .app-hero h1 { color: var(--ink); margin: 0 0 0.18rem 0; }
            .app-copy {
                color: #2563eb !important;
                font-size: 0.96rem;
                line-height: 1.45;
                font-weight: 500;
                margin: 0;
            }
            .section-head {
                border-radius: 18px;
                padding: 0.72rem 0.95rem;
                margin-bottom: 0.65rem;
            }
            hr.page-divider,
            .stMarkdown hr.page-divider,
            [data-testid="stMarkdownContainer"] hr.page-divider {
                display: block !important;
                width: 100% !important;
                height: 0 !important;
                border: 0 !important;
                border-top: 1px solid rgba(148, 163, 184, 0.34) !important;
                box-shadow: 0 1px 0 rgba(255, 255, 255, 0.03);
                margin: 0.95rem 0 !important;
                background: none !important;
            }
            hr,
            .stMarkdown hr,
            [data-testid="stMarkdownContainer"] hr {
                border: 0 !important;
                border-top: 1px solid rgba(148, 163, 184, 0.22) !important;
                margin: 0.9rem 0 !important;
            }
            .section-head h4 { margin: 0 0 0.12rem 0; color: var(--ink) !important; }
            .section-meta, .metric-note { color: var(--muted) !important; }
            .metric-card {
                border-radius: 18px;
                padding: 1rem 1rem 0.9rem;
                min-height: 168px;
                display: flex;
                flex-direction: column;
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
            .metric-card-compact {
                min-height: 168px;
            }
            .metric-card-dense {
                min-height: 142px;
                padding: 0.85rem 0.9rem 0.8rem;
            }
            .metric-card-dense .metric-value {
                font-size: 1.55rem;
                line-height: 1.12;
            }
            .metric-card-slim {
                min-height: 76px;
                padding: 0.62rem 0.72rem 0.58rem;
                border-radius: 16px;
            }
            .metric-card-slim .metric-label {
                font-size: 0.63rem;
                margin-bottom: 0.16rem;
                letter-spacing: 0.12em;
            }
            .metric-card-slim .metric-value {
                font-size: 1.18rem;
                line-height: 1.12;
                margin-bottom: 0.18rem;
            }
            .metric-card-slim.metric-card-dense .metric-value {
                font-size: 0.98rem;
                line-height: 1.15;
                min-height: 2.3em;
                display: -webkit-box;
                -webkit-box-orient: vertical;
                -webkit-line-clamp: 2;
                overflow: hidden;
            }
            .metric-card-slim .metric-value-compact {
                font-size: 0.74rem;
                line-height: 1.2;
                font-weight: 700;
            }
            .metric-card-slim .metric-note {
                font-size: 0.72rem;
                line-height: 1.18;
                min-height: 2.36em;
            }
            .metric-value-compact {
                font-size: 0.92rem;
                line-height: 1.35;
                font-weight: 700;
                word-break: break-word;
                overflow-wrap: anywhere;
            }
            .metric-note {
                margin-top: auto;
            }
            textarea[aria-label="Paste the job description here"] {
                background: linear-gradient(180deg, rgba(18, 28, 46, 0.98), rgba(22, 35, 58, 0.98)) !important;
                color: #eef4ff !important;
                border: 1px solid rgba(96, 165, 250, 0.18) !important;
                box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04) !important;
            }
            textarea[aria-label="Paste the job description here"]::placeholder {
                color: #c9daf8 !important;
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
            [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"]:has(.sidebar-assistant-card-header) {
                background: rgba(255, 255, 255, 0.06);
                border: 1px solid rgba(148, 163, 184, 0.16);
                border-radius: 18px;
                padding: 0.95rem;
                margin-bottom: 0.9rem;
            }
            .sidebar-assistant-card-header {
                margin-bottom: 0.7rem;
            }
            .sidebar-assistant-card-title {
                font-size: 0.92rem;
                color: #e7eefc !important;
                font-weight: 700;
                margin-bottom: 0.1rem;
                line-height: 1.35;
            }
            .sidebar-chat-shell,
            .sidebar-account-shell {
                margin-bottom: 0.65rem;
            }
            .sidebar-account-shell {
                padding: 0.72rem 0.8rem;
            }
            .sidebar-usage-stat {
                background: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(148, 163, 184, 0.14);
                border-radius: 16px;
                padding: 0.58rem 0.58rem;
                margin-bottom: 0.48rem;
                min-height: 6.6rem;
                display: flex;
                flex-direction: column;
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
                font-size: 0.9rem;
                line-height: 1.15;
                color: #f8fbff !important;
                font-weight: 800;
                margin-bottom: 0.2rem;
            }
            .sidebar-usage-copy {
                color: #cbd5e1 !important;
                font-size: 0.66rem;
                line-height: 1.2;
                margin-top: auto;
            }
            .sidebar-account-row {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 1rem;
            }
            .sidebar-account-summary {
                color: #f8fbff !important;
                font-weight: 700;
                font-size: 0.9rem;
                line-height: 1.2;
            }
            .sidebar-account-plan {
                color: #cbd5e1 !important;
                font-size: 0.82rem;
                text-align: right;
            }
            @media (max-width: 1200px) {
                .sidebar-account-row {
                    flex-direction: column;
                    align-items: flex-start;
                    gap: 0.25rem;
                }
                .sidebar-account-plan {
                    text-align: left;
                }
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
            [data-testid="stSidebar"] .stExpander summary {
                background: #ffffff !important;
                color: var(--ink) !important;
                border-bottom: 1px solid rgba(20, 32, 51, 0.08) !important;
            }
            [data-testid="stSidebar"] .stExpander summary *,
            [data-testid="stSidebar"] .stExpander summary p,
            [data-testid="stSidebar"] .stExpander summary span,
            [data-testid="stSidebar"] .stExpander summary div,
            [data-testid="stSidebar"] .stExpander summary label {
                color: var(--ink) !important;
            }
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
            [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"]:has(.sidebar-assistant-card-header) [data-testid="stChatMessage"] {
                background: rgba(255, 255, 255, 0.04);
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
            [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"]:has(.sidebar-assistant-card-header) .stTextInput,
            [data-testid="stSidebar"] [data-testid="stVerticalBlockBorderWrapper"]:has(.sidebar-assistant-card-header) .stButton {
                margin-top: 0.2rem;
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
            div[data-testid="stFileUploader"] {
                background: linear-gradient(180deg, rgba(5, 12, 24, 0.98), rgba(9, 20, 38, 0.98)) !important;
                border: 1px solid rgba(96, 165, 250, 0.16) !important;
                border-radius: 18px !important;
                padding: 0.8rem !important;
                box-shadow: 0 18px 34px rgba(0, 0, 0, 0.18) !important;
                margin-bottom: 0.95rem !important;
            }
            div[data-testid="stFileUploader"] [data-testid="stWidgetLabel"] {
                color: #f8fbff !important;
                font-weight: 700 !important;
                margin-bottom: 0.65rem !important;
            }
            div[data-testid="stFileUploader"] section {
                background: rgba(148, 163, 184, 0.08) !important;
                border: 1px solid rgba(148, 163, 184, 0.14) !important;
                border-radius: 14px !important;
                box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03) !important;
                padding: 0.35rem !important;
            }
            div[data-testid="stFileUploader"] section button {
                border-radius: 12px !important;
            }
            div[data-testid="stFileUploader"] [data-testid="stFileUploaderDropzoneInstructions"] > div,
            div[data-testid="stFileUploader"] small {
                color: #dbe8ff !important;
            }
            .intake-divider {
                display: flex;
                align-items: center;
                gap: 0.85rem;
                margin: 0.25rem 0 0.9rem;
            }
            .intake-divider::before,
            .intake-divider::after {
                content: "";
                flex: 1 1 auto;
                height: 1px;
                background: rgba(148, 163, 184, 0.26);
            }
            .intake-divider span {
                color: #93c5fd !important;
                font-size: 0.76rem;
                font-weight: 700;
                letter-spacing: 0.16em;
            }
            .parser-agent-brief {
                position: relative;
                overflow: hidden;
                border: 1px solid rgba(20, 32, 51, 0.12);
                border-radius: 18px;
                background: linear-gradient(135deg, rgba(255,255,255,0.98), rgba(239,246,255,0.96));
                padding: 0.95rem 1rem 0.95rem 1.05rem;
                margin: 0 0 0.8rem 0;
                box-shadow: 0 16px 34px rgba(0, 0, 0, 0.14);
            }
            .parser-agent-brief::before {
                content: "";
                position: absolute;
                left: 0;
                top: 0;
                bottom: 0;
                width: 4px;
                background: #2563eb;
            }
            .parser-agent-pill {
                display: inline-flex;
                align-items: center;
                border-radius: 999px;
                padding: 0.25rem 0.55rem;
                background: rgba(37, 99, 235, 0.10);
                color: #1d4ed8 !important;
                font-size: 0.74rem;
                font-weight: 700;
                letter-spacing: 0.08em;
                text-transform: uppercase;
                margin-bottom: 0.45rem;
            }
            .parser-agent-title {
                font-size: 0.97rem;
                line-height: 1.35;
                color: var(--ink) !important;
                font-weight: 700;
                margin-bottom: 0.18rem;
            }
            .parser-agent-copy {
                font-size: 0.92rem;
                line-height: 1.45;
                color: var(--muted) !important;
            }
            div[data-testid="stTextArea"]:has(textarea[aria-label="Paste the job description here"]) {
                background: linear-gradient(180deg, rgba(5, 12, 24, 0.98), rgba(9, 20, 38, 0.98)) !important;
                border: 1px solid rgba(96, 165, 250, 0.16) !important;
                border-radius: 18px !important;
                padding: 0.8rem !important;
                box-shadow: 0 18px 34px rgba(0, 0, 0, 0.18) !important;
            }
            div[data-testid="stTextArea"]:has(textarea[aria-label="Paste the job description here"]) textarea {
                background: rgba(148, 163, 184, 0.08) !important;
                color: #eef4ff !important;
                border: 1px solid rgba(148, 163, 184, 0.14) !important;
                box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03) !important;
                border-radius: 14px !important;
                padding: 0.95rem 1rem !important;
            }
            div[data-testid="stTextArea"]:has(textarea[aria-label="Paste the job description here"]) textarea::placeholder {
                color: #c9daf8 !important;
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
                border: 1px solid rgba(96, 165, 250, 0.16) !important;
                border-radius: 18px !important;
                background: linear-gradient(180deg, rgba(5, 12, 24, 0.98), rgba(9, 20, 38, 0.98)) !important;
                box-shadow: 0 18px 34px rgba(0, 0, 0, 0.18);
                overflow: hidden;
            }
            .stExpander details {
                background: transparent !important;
            }
            .stExpander summary {
                list-style: none !important;
                background: #ffffff !important;
                color: var(--ink) !important;
                border-bottom: 1px solid rgba(20, 32, 51, 0.08) !important;
                position: relative;
                padding-right: 2.6rem !important;
            }
            .stExpander summary::-webkit-details-marker {
                display: none !important;
            }
            .stExpander summary svg,
            .stExpander summary [data-testid="stIconMaterial"] {
                display: none !important;
            }
            .stExpander summary::marker {
                content: "";
            }
            .stExpander summary::after {
                content: "▾";
                position: absolute;
                right: 1rem;
                top: 50%;
                transform: translateY(-50%);
                color: var(--ink) !important;
                font-size: 1rem;
                line-height: 1;
                font-weight: 700;
            }
            .stExpander details:not([open]) summary::after {
                content: "▸";
            }
            .stExpander summary:hover {
                background: #f8fafc !important;
            }
            .stExpander summary *,
            .stExpander summary svg,
            .stExpander summary [data-testid="stIconMaterial"] {
                color: var(--ink) !important;
                fill: var(--ink) !important;
                opacity: 1 !important;
            }
            .stExpander summary p,
            .stExpander summary span,
            .stExpander summary label,
            .stExpander summary div {
                color: var(--ink) !important;
            }
            .stExpander [data-testid="stExpanderDetails"],
            .stExpander details > div {
                padding: 0.75rem 0.8rem 0.85rem !important;
                background: transparent !important;
            }
            .stExpander [data-testid="stExpanderDetails"] > div,
            .stExpander details > div > div {
                background: rgba(148, 163, 184, 0.07) !important;
                border: 1px solid rgba(148, 163, 184, 0.14) !important;
                border-radius: 16px !important;
                padding: 0.9rem 1rem !important;
                box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.03) !important;
            }
            .stExpander label,
            .stExpander p,
            .stExpander div,
            .stExpander span,
            .stExpander li,
            .stExpander h1,
            .stExpander h2,
            .stExpander h3,
            .stExpander h4,
            .stExpander h5,
            .stExpander h6,
            .stExpander strong {
                color: #e7eefc !important;
            }
            .stExpander [data-testid="stExpanderDetails"] > div p,
            .stExpander [data-testid="stExpanderDetails"] > div li,
            .stExpander [data-testid="stExpanderDetails"] > div label,
            .stExpander [data-testid="stExpanderDetails"] > div span,
            .stExpander [data-testid="stExpanderDetails"] > div strong,
            .stExpander details > div > div p,
            .stExpander details > div > div li,
            .stExpander details > div > div label,
            .stExpander details > div > div span,
            .stExpander details > div > div strong {
                color: #dbe8ff !important;
            }
            .stExpander [data-testid="stMarkdownContainer"] code,
            .stExpander pre,
            .stExpander code {
                background: rgba(15, 23, 42, 0.82) !important;
                color: #e2e8f0 !important;
                border-color: rgba(148, 163, 184, 0.16) !important;
            }
            .stExpander summary p,
            .stExpander summary span,
            .stExpander summary label,
            .stExpander summary div,
            .stExpander summary strong {
                color: var(--ink) !important;
            }
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
