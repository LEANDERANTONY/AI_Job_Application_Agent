import streamlit as st


def render_intro():
    st.markdown(
        """
        <div class="app-hero">
            <div class="app-kicker">Application Copilot</div>
            <h1>AI Job Application Agent</h1>
            <p class="app-copy">
                Ingest your resume, structure a target job description, and prepare
                the inputs needed for fit analysis, tailoring, and export.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metric_card(label, value, note):
    st.markdown(
        f"""
        <div class="metric-card">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
            <div class="metric-note">{note}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_section_head(title, subtitle):
    st.markdown(
        f"""
        <div class="section-head">
            <h4>{title}</h4>
            <div class="section-meta">{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_footer():
    st.markdown("---")
    st.caption(
        "Built by Leander Antony | Streamlit-first, backend-ready AI application workflow"
    )


@st.fragment
def render_download_button(label, data, file_name, mime, key, use_container_width=False):
    st.download_button(
        label,
        data=data,
        file_name=file_name,
        mime=mime,
        key=key,
        use_container_width=use_container_width,
    )


def render_evolution_note():
    with st.expander("How this app is evolving", expanded=False):
        st.markdown(
            """
1. Collect and normalize candidate inputs.
2. Structure the target job description.
3. Run supervised agent orchestration on top of the deterministic baseline.
4. Render recruiter-facing output and export it cleanly.
5. Harden deployment for Streamlit first, then extract a backend when the workflow stabilizes.
"""
        )
