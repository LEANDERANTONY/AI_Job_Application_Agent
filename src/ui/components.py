import base64
import json

import streamlit as st
import streamlit.components.v1 as components


def render_intro():
    st.markdown(
        """
        <div class="app-hero">
            <h1>Job Application Copilot</h1>
            <p class="app-copy">
                Ingest your resume and job description, prepare a targeted resume
                and application strategy, and apply for jobs with grounded materials.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metric_card(label, value, note, compact=False, dense=False, slim=False):
    compact_class = " metric-card-compact" if compact else ""
    dense_class = " metric-card-dense" if dense else ""
    slim_class = " metric-card-slim" if slim else ""
    value_class = "metric-value metric-value-compact" if compact else "metric-value"
    st.markdown(
        f"""
        <div class="metric-card{compact_class}{dense_class}{slim_class}">
            <div class="metric-label">{label}</div>
            <div class="{value_class}">{value}</div>
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


def render_page_divider():
    st.markdown('<hr class="page-divider" aria-hidden="true" />', unsafe_allow_html=True)


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


@st.fragment
def render_auto_download(data, file_name, mime, key):
    encoded = base64.b64encode(data).decode("ascii")
    components.html(
        f"""
        <script>
        (function() {{
            const encoded = {json.dumps(encoded)};
            const binary = window.atob(encoded);
            const bytes = new Uint8Array(binary.length);
            for (let i = 0; i < binary.length; i += 1) {{
                bytes[i] = binary.charCodeAt(i);
            }}
            const blob = new Blob([bytes], {{ type: {json.dumps(mime)} }});
            const url = URL.createObjectURL(blob);
            const link = document.createElement("a");
            link.href = url;
            link.download = {json.dumps(file_name)};
            link.style.display = "none";
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            setTimeout(() => URL.revokeObjectURL(url), 2000);
        }})();
        </script>
        """,
        height=0,
        width=0,
    )


def render_html_preview(html_document, height=720, scrolling=True):
    components.html(
        html_document,
        height=height,
        scrolling=scrolling,
    )
