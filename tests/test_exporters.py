from unittest.mock import patch

from src.errors import ExportError
from src.exporters import _build_report_html, export_markdown_bytes, export_pdf_bytes
from src.report_builder import build_application_report
from src.schemas import ResumeDocument, WorkExperience
from src.services.fit_service import build_fit_analysis
from src.services.job_service import build_job_description_from_text
from src.services.profile_service import build_candidate_profile_from_resume
from src.services.tailoring_service import build_tailored_resume_draft


def _build_report():
    candidate_profile = build_candidate_profile_from_resume(
        ResumeDocument(
            text="Leander Antony\nChennai, India\nPython SQL Docker",
            filetype="TXT",
            source="uploaded",
        )
    )
    candidate_profile.experience = [
        WorkExperience(
            title="AI Engineer",
            organization="Example Labs",
            description="Built ML applications.",
            start={"year": 2023},
            end={"year": 2025},
        )
    ]
    job_description = build_job_description_from_text(
        "Machine Learning Engineer\nRequired: Python, SQL, Docker.\n"
    )
    fit_analysis = build_fit_analysis(candidate_profile, job_description)
    tailored_draft = build_tailored_resume_draft(
        candidate_profile,
        job_description,
        fit_analysis,
    )
    return build_application_report(
        candidate_profile,
        job_description,
        fit_analysis,
        tailored_draft,
    )


def test_export_markdown_bytes_returns_utf8_bytes():
    report = _build_report()

    markdown_bytes = export_markdown_bytes(report)

    assert isinstance(markdown_bytes, bytes)
    assert markdown_bytes.decode("utf-8").startswith("# ")


def test_build_report_html_contains_structure():
    report = _build_report()

    html_output = _build_report_html(report.markdown, title=report.title)

    assert "<h1>" in html_output
    assert report.title in html_output
    assert "<h2>" in html_output
    assert "<ul>" in html_output or "<ol>" in html_output


@patch("src.exporters._generate_pdf_with_playwright", side_effect=RuntimeError("no browser"))
def test_export_pdf_bytes_falls_back_when_playwright_backend_fails(_mock_generate_pdf):
    report = _build_report()

    pdf_bytes = export_pdf_bytes(report)

    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 500


@patch("src.exporters._generate_pdf_with_reportlab", side_effect=RuntimeError("reportlab failed"))
@patch("src.exporters._generate_pdf_with_playwright", side_effect=RuntimeError("playwright failed"))
def test_export_pdf_bytes_raises_export_error_when_both_backends_fail(
    _mock_playwright,
    _mock_reportlab,
):
    report = _build_report()

    try:
        export_pdf_bytes(report)
        assert False, "Expected ExportError"
    except ExportError:
        assert True
