from dataclasses import replace

import streamlit as st

from src.errors import ExportError
from src.exporters import build_resume_preview_html, export_markdown_bytes
from src.resume_builder import RESUME_THEMES
from src.resume_diff import build_resume_diff, build_resume_diff_metrics
from src.schemas import AgentWorkflowResult, ApplicationReport, TailoredResumeArtifact
from src.ui.components import render_auto_download, render_download_button, render_html_preview, render_metric_card, render_section_head
from src.ui.state import (
    TAILORED_RESUME_THEME,
    consume_pending_browser_download,
    get_pending_browser_download,
    get_tailored_resume_theme,
    set_pending_browser_download,
    set_tailored_resume_theme,
)
from src.ui.workflow_signatures import report_signature
from src.ui.workflow import (
    get_active_candidate_profile,
    get_cached_export_bundle_package,
    get_cached_pdf_package,
    get_cached_tailored_resume_pdf_package,
    prepare_export_bundle_package,
    prepare_pdf_package,
    prepare_tailored_resume_pdf_package,
)


def _resolve_resume_theme_widget_value(artifact_theme: str, theme_options: list[str]) -> str:
    stored_theme = get_tailored_resume_theme(default_theme=artifact_theme)
    if stored_theme in theme_options:
        return stored_theme

    fallback_theme = artifact_theme if artifact_theme in theme_options else theme_options[0]
    set_tailored_resume_theme(fallback_theme)
    return fallback_theme


def _build_download_widget_key(base_key: str, artifact) -> str:
    return "{base}:{signature}".format(
        base=base_key,
        signature=report_signature(artifact)[:12],
    )


def _prepare_deferred_download(clicked: bool, cached_payload, prepare_callback) -> bool:
    if cached_payload is not None or not clicked:
        return False
    prepare_callback()
    return True


def _queue_browser_download(target: str, data: bytes, file_name: str, mime: str):
    set_pending_browser_download(
        {
            "target": target,
            "data": data,
            "file_name": file_name,
            "mime": mime,
        }
    )


def _render_pending_auto_download(target: str) -> bool:
    pending_download = get_pending_browser_download()
    if not pending_download or pending_download.get("target") != target:
        return False

    render_auto_download(
        pending_download["data"],
        pending_download["file_name"],
        pending_download["mime"],
        key="auto_download:{target}".format(target=target),
    )
    consume_pending_browser_download()
    st.caption("Download should start automatically. If the browser blocks it, use the backup download button below.")
    return True


def _build_themed_resume_artifact(artifact: TailoredResumeArtifact, theme_name: str) -> TailoredResumeArtifact:
    return replace(
        artifact,
        theme=theme_name,
        summary="{label} template ready for review and export.".format(
            label=RESUME_THEMES.get(theme_name, {"label": theme_name})["label"]
        ),
    )


def _render_resume_variant_preview(artifact: TailoredResumeArtifact, is_active_theme: bool):
    theme_config = RESUME_THEMES.get(artifact.theme, {"label": artifact.theme, "tagline": ""})
    preview_target = "tailored_resume_pdf:{theme}".format(theme=artifact.theme)
    cached_pdf_bytes = get_cached_tailored_resume_pdf_package(theme_name=artifact.theme)

    st.markdown("### {label}".format(label=theme_config["label"]))
    st.caption(theme_config.get("tagline", ""))
    if is_active_theme:
        st.success("This template is currently selected for the combined export bundle.")
    else:
        if st.button(
            "Use This Template For Bundle",
            key="use_template_for_bundle:{theme}".format(theme=artifact.theme),
        ):
            set_tailored_resume_theme(artifact.theme)
            st.rerun()

    render_html_preview(
        build_resume_preview_html(artifact),
        height=760,
        scrolling=True,
    )

    _render_pending_auto_download(preview_target)
    if cached_pdf_bytes is None:
        if st.button(
            "Download {label} PDF".format(label=theme_config["label"]),
            key="prepare_tailored_resume_pdf:{theme}".format(theme=artifact.theme),
            use_container_width=True,
        ):
            try:
                with st.spinner(
                    "Generating {label} PDF...".format(label=theme_config["label"])
                ):
                    pdf_bytes = prepare_tailored_resume_pdf_package(artifact)
                    _queue_browser_download(
                        preview_target,
                        pdf_bytes,
                        artifact.filename_stem + "-" + artifact.theme + ".pdf",
                        "application/pdf",
                    )
                    st.rerun()
            except ExportError as error:
                st.warning(error.user_message)
        st.caption("Generates this template variant as a PDF and starts the browser download when ready.")
    else:
        render_download_button(
            "Download {label} PDF Again".format(label=theme_config["label"]),
            data=cached_pdf_bytes,
            file_name=artifact.filename_stem + "-" + artifact.theme + ".pdf",
            mime="application/pdf",
            key=_build_download_widget_key(
                "download_tailored_resume_pdf:{theme}".format(theme=artifact.theme),
                artifact,
            ),
            use_container_width=True,
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
            key=_build_download_widget_key("download_markdown_package", report),
        )
    with pdf_col:
        _render_pending_auto_download("report_pdf")
        if get_cached_pdf_package() is None:
            if st.button("Download PDF Package", key="prepare_pdf_package"):
                try:
                    with st.spinner("Generating PDF package..."):
                        pdf_bytes = get_cached_pdf_package() or prepare_pdf_package(report)
                        _queue_browser_download(
                            "report_pdf",
                            pdf_bytes,
                            report.filename_stem + ".pdf",
                            "application/pdf",
                        )
                        st.rerun()
                except ExportError as error:
                    st.warning(error.user_message)
            st.caption("Generates the PDF and should start the browser download automatically when ready.")
        else:
            render_download_button(
                "Download PDF Package Again",
                data=get_cached_pdf_package(),
                file_name=report.filename_stem + ".pdf",
                mime="application/pdf",
                key=_build_download_widget_key("download_pdf_package", report),
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
    _render_pending_auto_download("export_bundle")
    if cached_bundle is None:
        if st.button("Download Combined Export Bundle", key="prepare_export_bundle"):
            try:
                with st.spinner("Preparing report and tailored resume bundle..."):
                    bundle_bytes = get_cached_export_bundle_package() or prepare_export_bundle_package(report, artifact)
                    bundle_name = "{name}.zip".format(
                        name=artifact.filename_stem.replace("-tailored-resume", "-application-bundle")
                    )
                    _queue_browser_download(
                        "export_bundle",
                        bundle_bytes,
                        bundle_name,
                        "application/zip",
                    )
                    st.rerun()
            except ExportError as error:
                st.warning(error.user_message)
        st.caption("Generates the ZIP bundle and should start the browser download automatically when ready.")
    else:
        bundle_name = "{name}.zip".format(
            name=artifact.filename_stem.replace("-tailored-resume", "-application-bundle")
        )
        render_download_button(
            "Download Combined Export Bundle Again",
            data=cached_bundle,
            file_name=bundle_name,
            mime="application/zip",
            key="{report_key}:{artifact_key}".format(
                report_key=_build_download_widget_key("download_export_bundle_report", report),
                artifact_key=_build_download_widget_key("download_export_bundle_artifact", artifact),
            ),
        )


def render_tailored_resume_artifact(artifact: TailoredResumeArtifact, agent_result: AgentWorkflowResult = None):
    st.markdown("---")
    render_section_head(
        "Tailored Resume Draft",
        "A grounded, JD-aligned resume artifact the candidate can use directly or refine manually.",
    )

    theme_options = list(RESUME_THEMES.keys())
    active_theme = _resolve_resume_theme_widget_value(artifact.theme, theme_options)
    themed_artifacts = {
        theme_name: _build_themed_resume_artifact(artifact, theme_name)
        for theme_name in theme_options
    }

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
            RESUME_THEMES.get(active_theme, {"label": active_theme})["label"],
            RESUME_THEMES.get(active_theme, {"tagline": "Theme controls the deterministic layout and section rhythm of the export."})["tagline"],
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

    st.markdown("**Template Gallery**")
    st.caption("Preview both resume variants below, then download the one you prefer. The active template is also used for the combined export bundle.")
    preview_tabs = st.tabs([RESUME_THEMES[theme_name]["label"] for theme_name in theme_options])
    for tab, theme_name in zip(preview_tabs, theme_options):
        with tab:
            _render_resume_variant_preview(
                themed_artifacts[theme_name],
                is_active_theme=(theme_name == active_theme),
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
            key=_build_download_widget_key("download_tailored_resume_markdown", artifact),
        )
    with pdf_col:
        _render_pending_auto_download("tailored_resume_pdf:active")
        active_artifact = themed_artifacts[active_theme]
        cached_active_pdf = get_cached_tailored_resume_pdf_package(theme_name=active_theme)
        if cached_active_pdf is None:
            if st.button("Download Tailored Resume PDF", key="prepare_tailored_resume_pdf"):
                try:
                    with st.spinner("Generating tailored resume PDF..."):
                        pdf_bytes = prepare_tailored_resume_pdf_package(active_artifact)
                        _queue_browser_download(
                            "tailored_resume_pdf:active",
                            pdf_bytes,
                            active_artifact.filename_stem + "-" + active_theme + ".pdf",
                            "application/pdf",
                        )
                        st.rerun()
                except ExportError as error:
                    st.warning(error.user_message)
            st.caption("Generates the PDF and should start the browser download automatically when ready.")
        else:
            render_download_button(
                "Download Tailored Resume PDF Again",
                data=cached_active_pdf,
                file_name=active_artifact.filename_stem + "-" + active_theme + ".pdf",
                mime="application/pdf",
                key=_build_download_widget_key("download_tailored_resume_pdf", active_artifact),
            )