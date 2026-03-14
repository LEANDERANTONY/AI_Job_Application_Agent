from src.exporters import export_markdown_bytes, export_pdf_bytes, export_zip_bundle_bytes
from src.schemas import ApplicationReport, TailoredResumeArtifact
from src.ui.state import (
    get_cached_export_bundle_bytes,
    get_cached_pdf_bytes,
    get_cached_tailored_resume_pdf_bytes,
    set_cached_export_bundle_bytes,
    set_cached_pdf_bytes,
    set_cached_tailored_resume_pdf_bytes,
)
from src.ui.workflow_history import persist_artifact_record


def prepare_pdf_package(report: ApplicationReport):
    pdf_bytes = export_pdf_bytes(report)
    set_cached_pdf_bytes(pdf_bytes)
    persist_artifact_record(
        "application_report_pdf",
        report.filename_stem,
        report.filename_stem + ".pdf",
    )
    return pdf_bytes


def get_cached_pdf_package():
    return get_cached_pdf_bytes()


def prepare_tailored_resume_pdf_package(artifact: TailoredResumeArtifact):
    pdf_bytes = export_pdf_bytes(artifact)
    set_cached_tailored_resume_pdf_bytes(pdf_bytes)
    persist_artifact_record(
        "tailored_resume_pdf",
        artifact.filename_stem,
        artifact.filename_stem + ".pdf",
    )
    return pdf_bytes


def get_cached_tailored_resume_pdf_package():
    return get_cached_tailored_resume_pdf_bytes()


def prepare_export_bundle_package(
    report: ApplicationReport,
    artifact: TailoredResumeArtifact,
):
    report_pdf_bytes = export_pdf_bytes(report)
    tailored_resume_pdf_bytes = export_pdf_bytes(artifact)
    set_cached_pdf_bytes(report_pdf_bytes)
    set_cached_tailored_resume_pdf_bytes(tailored_resume_pdf_bytes)

    bundle_bytes = export_zip_bundle_bytes(
        {
            report.filename_stem + ".md": export_markdown_bytes(report),
            report.filename_stem + ".pdf": report_pdf_bytes,
            artifact.filename_stem + ".md": export_markdown_bytes(artifact),
            artifact.filename_stem + ".pdf": tailored_resume_pdf_bytes,
        }
    )
    set_cached_export_bundle_bytes(bundle_bytes)
    bundle_stem = artifact.filename_stem.replace("-tailored-resume", "-application-bundle")
    persist_artifact_record(
        "application_bundle_zip",
        bundle_stem,
        bundle_stem + ".zip",
    )
    return bundle_bytes


def get_cached_export_bundle_package():
    return get_cached_export_bundle_bytes()