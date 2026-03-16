from dataclasses import replace

import streamlit as st

from src.errors import ExportError
from src.exporters import build_report_preview_html, build_resume_preview_html, export_markdown_bytes
from src.resume_builder import RESUME_THEMES
from src.schemas import AgentWorkflowResult, ApplicationReport, TailoredResumeArtifact
from src.ui.components import (
    render_auto_download,
    render_download_button,
    render_html_preview,
    render_metric_card,
    render_section_head,
)
from src.ui.state import (
    consume_pending_browser_download,
    get_pending_browser_download,
    get_tailored_resume_theme,
    set_pending_browser_download,
    set_tailored_resume_theme,
)
from src.ui.workflow_signatures import report_signature
from src.ui.workflow import (
    get_cached_pdf_package,
    get_cached_tailored_resume_pdf_package,
    prepare_pdf_package,
    prepare_tailored_resume_pdf_package,
)


def _build_download_widget_key(base_key: str, artifact) -> str:
    return "{base}:{signature}".format(
        base=base_key,
        signature=report_signature(artifact)[:12],
    )


def _build_themed_resume_artifact(artifact: TailoredResumeArtifact, theme_name: str) -> TailoredResumeArtifact:
    return replace(
        artifact,
        theme=theme_name,
        summary="{label} template ready for review and export.".format(
            label=RESUME_THEMES.get(theme_name, {"label": theme_name})["label"]
        ),
    )


def _resolve_resume_theme_widget_value(default_theme: str, available_themes: list[str]) -> str:
    stored_theme = get_tailored_resume_theme(default_theme=default_theme)
    if stored_theme in available_themes:
        return stored_theme
    set_tailored_resume_theme(default_theme)
    return default_theme


def _prepare_deferred_download(clicked: bool, cached_payload, prepare_callback) -> bool:
    if not clicked or cached_payload is not None:
        return False
    prepare_callback()
    return True


def _queue_browser_download(target: str, data: bytes, file_name: str, mime: str) -> None:
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
    st.caption("Download starting...")
    consume_pending_browser_download()
    return True


def _render_resume_variant_preview(artifact: TailoredResumeArtifact):
    theme_config = RESUME_THEMES.get(artifact.theme, {"label": artifact.theme, "tagline": ""})
    cached_pdf_bytes = get_cached_tailored_resume_pdf_package(theme_name=artifact.theme)
    expander_title = "{label} | {tagline}".format(
        label=theme_config["label"],
        tagline=theme_config.get("tagline", "Preview this resume variant."),
    )

    if cached_pdf_bytes is None:
        try:
            with st.spinner("Preparing {label} PDF...".format(label=theme_config["label"])):
                cached_pdf_bytes = prepare_tailored_resume_pdf_package(artifact)
        except ExportError as error:
            st.warning(error.user_message)
            cached_pdf_bytes = None

    with st.expander(expander_title, expanded=False):
        render_html_preview(
            build_resume_preview_html(artifact),
            height=760,
            scrolling=True,
        )

    action_cols = st.columns(2)
    with action_cols[0]:
        render_download_button(
            "Download {label} Markdown".format(label=theme_config["label"]),
            data=export_markdown_bytes(artifact),
            file_name=artifact.filename_stem + "-" + artifact.theme + ".md",
            mime="text/markdown",
            key=_build_download_widget_key(
                "download_tailored_resume_markdown:{theme}".format(theme=artifact.theme),
                artifact,
            ),
            use_container_width=True,
        )
    with action_cols[1]:
        if cached_pdf_bytes is not None:
            render_download_button(
                "Download {label} PDF".format(label=theme_config["label"]),
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
            slim=True,
        )
    with cols[1]:
        render_metric_card(
            "Export Formats",
            "Markdown + PDF",
            "Markdown stays editable. PDF is the polished package for sharing.",
            slim=True,
        )
    with cols[2]:
        render_metric_card(
            "Report Status",
            "Ready",
            report.summary,
            slim=True,
        )

    cached_report_pdf = get_cached_pdf_package()
    if cached_report_pdf is None:
        try:
            with st.spinner("Preparing PDF package..."):
                cached_report_pdf = prepare_pdf_package(report)
        except ExportError as error:
            st.warning(error.user_message)
            cached_report_pdf = None

    with st.expander("Preview Application Package", expanded=False):
        render_html_preview(
            build_report_preview_html(report),
            height=760,
            scrolling=True,
        )

    download_col, pdf_col = st.columns(2)
    with download_col:
        render_download_button(
            "Download Markdown Package",
            data=export_markdown_bytes(report),
            file_name=report.filename_stem + ".md",
            mime="text/markdown",
            key=_build_download_widget_key("download_markdown_package", report),
            use_container_width=True,
        )
    with pdf_col:
        if cached_report_pdf is not None:
            render_download_button(
                "Download PDF Package",
                data=cached_report_pdf,
                file_name=report.filename_stem + ".pdf",
                mime="application/pdf",
                key=_build_download_widget_key("download_pdf_package", report),
                use_container_width=True,
            )


def render_tailored_resume_artifact(artifact: TailoredResumeArtifact, agent_result: AgentWorkflowResult = None):
    st.markdown("---")
    theme_options = list(RESUME_THEMES.keys())
    themed_artifacts = {
        theme_name: _build_themed_resume_artifact(artifact, theme_name)
        for theme_name in theme_options
    }

    render_section_head(
        "Resume Preview",
        "Preview both resume variants below, then download the one you prefer.",
    )
    preview_tabs = st.tabs([RESUME_THEMES[theme_name]["label"] for theme_name in theme_options])
    for tab, theme_name in zip(preview_tabs, theme_options):
        with tab:
            _render_resume_variant_preview(themed_artifacts[theme_name])
