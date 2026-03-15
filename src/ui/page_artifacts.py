import streamlit as st

from src.errors import ExportError
from src.exporters import export_markdown_bytes
from src.resume_builder import RESUME_THEMES
from src.resume_diff import build_resume_diff, build_resume_diff_metrics
from src.schemas import AgentWorkflowResult, ApplicationReport, TailoredResumeArtifact
from src.ui.components import render_download_button, render_metric_card, render_section_head
from src.ui.state import TAILORED_RESUME_THEME
from src.ui.workflow import (
    get_active_candidate_profile,
    get_cached_export_bundle_package,
    get_cached_pdf_package,
    get_cached_tailored_resume_pdf_package,
    prepare_export_bundle_package,
    prepare_pdf_package,
    prepare_tailored_resume_pdf_package,
)


def render_report_package(report: ApplicationReport, agent_result: AgentWorkflowResult = None):
    st.markdown("---")
    render_section_head(
        "Application Package",
        "Deterministic final assembly for export and recruiter-facing review.",
    )

    cols = st.columns(3)
    with cols[0]:
        render_metric_card(
            "Package Mode",
            "Agent-Enhanced" if agent_result else "Deterministic",
            "The report builder assembles a stable package from current workflow outputs.",
        )
    with cols[1]:
        render_metric_card(
            "Export Formats",
            "Markdown + PDF",
            "Markdown stays editable. PDF is the polished package for sharing.",
        )
    with cols[2]:
        render_metric_card(
            "Report Status",
            "Ready",
            report.summary,
        )

    with st.expander("Preview Application Package", expanded=False):
        st.text_area(
            "Package Preview",
            report.markdown,
            height=360,
            label_visibility="collapsed",
        )

    download_col, pdf_col = st.columns(2)
    with download_col:
        render_download_button(
            "Download Markdown Package",
            data=export_markdown_bytes(report),
            file_name=report.filename_stem + ".md",
            mime="text/markdown",
            key="download_markdown_package",
        )
    with pdf_col:
        if get_cached_pdf_package() is None:
            if st.button("Prepare PDF Package", key="prepare_pdf_package"):
                try:
                    with st.spinner("Generating PDF package..."):
                        prepare_pdf_package(report)
                except ExportError as error:
                    st.warning(error.user_message)
        else:
            render_download_button(
                "Download PDF Package",
                data=get_cached_pdf_package(),
                file_name=report.filename_stem + ".pdf",
                mime="application/pdf",
                key="download_pdf_package",
            )


def render_export_bundle_actions(
    artifact: TailoredResumeArtifact,
    report: ApplicationReport,
):
    st.markdown("---")
    render_section_head(
        "Combined Export",
        "Download the tailored resume and strategy report together in one bundle.",
    )

    cols = st.columns(3)
    with cols[0]:
        render_metric_card(
            "Resume Only",
            "Available",
            "Use the tailored resume section if you only want the generated resume artifact.",
        )
    with cols[1]:
        render_metric_card(
            "Report Only",
            "Available",
            "Use the application package section if you only want the report artifact.",
        )
    with cols[2]:
        render_metric_card(
            "Both Together",
            "ZIP Bundle",
            "Generates one archive containing markdown and PDF versions of both outputs.",
        )

    cached_bundle = get_cached_export_bundle_package()
    if cached_bundle is None:
        if st.button("Prepare Combined Export Bundle", key="prepare_export_bundle"):
            try:
                with st.spinner("Preparing report and tailored resume bundle..."):
                    prepare_export_bundle_package(report, artifact)
            except ExportError as error:
                st.warning(error.user_message)
    else:
        bundle_name = "{name}.zip".format(
            name=artifact.filename_stem.replace("-tailored-resume", "-application-bundle")
        )
        render_download_button(
            "Download Combined Export Bundle",
            data=cached_bundle,
            file_name=bundle_name,
            mime="application/zip",
            key="download_export_bundle",
        )


def render_tailored_resume_artifact(artifact: TailoredResumeArtifact, agent_result: AgentWorkflowResult = None):
    st.markdown("---")
    render_section_head(
        "Tailored Resume Draft",
        "A grounded, JD-aligned resume artifact the candidate can use directly or refine manually.",
    )

    theme_options = list(RESUME_THEMES.keys())
    selected_theme = st.selectbox(
        "Resume Template",
        theme_options,
        index=theme_options.index(artifact.theme) if artifact.theme in theme_options else 0,
        key=TAILORED_RESUME_THEME,
        format_func=lambda value: RESUME_THEMES[value]["label"],
    )
    if selected_theme != artifact.theme:
        st.rerun()

    cols = st.columns(3)
    with cols[0]:
        render_metric_card(
            "Resume Mode",
            "Agent-Enhanced" if agent_result else "Deterministic",
            "Uses the current workflow outputs to generate a recruiter-facing tailored resume draft.",
        )
    with cols[1]:
        render_metric_card(
            "Template",
            RESUME_THEMES.get(artifact.theme, {"label": artifact.theme})["label"],
            RESUME_THEMES.get(artifact.theme, {"tagline": "Theme controls the deterministic layout and section rhythm of the export."})["tagline"],
        )
    with cols[2]:
        render_metric_card(
            "Validation Notes",
            str(len(artifact.validation_notes)),
            artifact.summary,
        )

    left_col, right_col = st.columns(2)
    with left_col:
        st.markdown("**Change Summary**")
        if artifact.change_log:
            for item in artifact.change_log:
                st.markdown(f"- {item}")
        else:
            st.caption("No change summary available.")
    with right_col:
        st.markdown("**Validation Notes**")
        if artifact.validation_notes:
            for item in artifact.validation_notes:
                st.markdown(f"- {item}")
        else:
            st.caption("No validation notes available.")

    original_resume_text = get_active_candidate_profile().resume_text if get_active_candidate_profile() else ""
    diff_metrics = build_resume_diff_metrics(original_resume_text, artifact.markdown)

    metric_cols = st.columns(4)
    with metric_cols[0]:
        render_metric_card(
            "Original Lines",
            str(diff_metrics["original_line_count"]),
            "Line count from the current parsed resume text.",
        )
    with metric_cols[1]:
        render_metric_card(
            "Tailored Lines",
            str(diff_metrics["tailored_line_count"]),
            "Line count in the generated tailored resume artifact.",
        )
    with metric_cols[2]:
        render_metric_card(
            "Added / Removed",
            "{added}/{removed}".format(
                added=diff_metrics["added_lines"],
                removed=diff_metrics["removed_lines"],
            ),
            "Simple diff count to show how much content shifted.",
        )
    with metric_cols[3]:
        render_metric_card(
            "Similarity",
            "{ratio}%".format(ratio=diff_metrics["similarity_ratio"]),
            "Text-level similarity between the original input and tailored output.",
        )

    with st.expander("Preview Tailored Resume", expanded=True):
        st.text_area(
            "Tailored Resume Preview",
            artifact.markdown,
            height=420,
            label_visibility="collapsed",
        )

    with st.expander("Compare Original vs Tailored Resume", expanded=False):
        original_col, tailored_col = st.columns(2)
        with original_col:
            st.markdown("**Original Resume Text**")
            st.text_area(
                "Original Resume Text",
                original_resume_text,
                height=360,
                label_visibility="collapsed",
            )
        with tailored_col:
            st.markdown("**Tailored Resume Text**")
            st.text_area(
                "Tailored Resume Text",
                artifact.markdown,
                height=360,
                label_visibility="collapsed",
            )
        st.markdown("**Unified Diff**")
        st.code(build_resume_diff(original_resume_text, artifact.markdown), language="diff")

    download_col, pdf_col = st.columns(2)
    with download_col:
        render_download_button(
            "Download Tailored Resume Markdown",
            data=export_markdown_bytes(artifact),
            file_name=artifact.filename_stem + ".md",
            mime="text/markdown",
            key="download_tailored_resume_markdown",
        )
    with pdf_col:
        if get_cached_tailored_resume_pdf_package() is None:
            if st.button("Prepare Tailored Resume PDF", key="prepare_tailored_resume_pdf"):
                try:
                    with st.spinner("Generating tailored resume PDF..."):
                        prepare_tailored_resume_pdf_package(artifact)
                except ExportError as error:
                    st.warning(error.user_message)
        else:
            render_download_button(
                "Download Tailored Resume PDF",
                data=get_cached_tailored_resume_pdf_package(),
                file_name=artifact.filename_stem + ".pdf",
                mime="application/pdf",
                key="download_tailored_resume_pdf",
            )