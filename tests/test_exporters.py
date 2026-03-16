from io import BytesIO
from unittest.mock import patch

from src.errors import ExportError
import zipfile

from src.exporters import _build_report_html, _build_resume_html, export_markdown_bytes, export_pdf_bytes, export_zip_bundle_bytes, generate_pdf
from src.report_builder import build_application_report
from src.schemas import EducationEntry, ResumeDocument, ResumeExperienceEntry, ResumeHeader, TailoredResumeArtifact, WorkExperience
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


def test_build_resume_html_uses_beige_template_for_modern_professional():
    html_output = _build_resume_html("# Candidate\n\n## Experience", theme="modern_professional")

    assert "resume-shell--modern" in html_output
    assert "#a06b44" in html_output
    assert "#f6efe8" in html_output


def test_build_resume_html_uses_blue_template_for_classic_ats():
    html_output = _build_resume_html("# Candidate\n\n## Experience", theme="classic_ats")

    assert "resume-shell--classic" in html_output
    assert "#2563eb" in html_output
    assert "#f7fbff" in html_output


def test_build_resume_html_renders_structured_modern_resume_sections():
    artifact = TailoredResumeArtifact(
        title="Tailored Resume",
        filename_stem="tailored-resume",
        summary="Structured resume",
        markdown="# Fallback markdown should not drive this layout",
        plain_text="Structured resume",
        theme="modern_professional",
        header=ResumeHeader(
            full_name="Leander Antony",
            location="Chennai, India",
            contact_lines=["leander@example.com", "+91 99999 99999", "linkedin.com/in/leander"],
        ),
        target_role="AI Engineer",
        professional_summary="Builds grounded AI workflow products with reliable delivery and measurable impact.",
        highlighted_skills=["Python", "LLM orchestration", "Streamlit", "SQL"],
        experience_entries=[
            ResumeExperienceEntry(
                title="AI Engineer",
                organization="Example Labs",
                location="Remote",
                start="2023",
                end="Present",
                bullets=[
                    "Built multi-agent job application workflows with human review loops.",
                    "Shipped PDF export improvements that removed browser runtime dependencies.",
                ],
            )
        ],
        education_entries=[
            EducationEntry(
                institution="Example University",
                degree="B.Tech",
                field_of_study="Computer Science",
                start="2018",
                end="2022",
            )
        ],
        certifications=["Azure AI Fundamentals"],
        validation_notes=["All achievements trace back to resume evidence."],
    )

    html_output = _build_resume_html(artifact.markdown, theme="modern_professional", artifact=artifact)

    assert "Leander Antony" in html_output
    assert "Professional Experience" in html_output
    assert "Core Skills" in html_output
    assert "Azure AI Fundamentals" in html_output
    assert "Fallback markdown should not drive this layout" not in html_output


def test_export_pdf_bytes_passes_tailored_resume_artifact_to_generator():
    artifact = TailoredResumeArtifact(
        title="Tailored Resume",
        filename_stem="tailored-resume",
        summary="Structured resume",
        markdown="# Resume",
        plain_text="Resume",
        theme="classic_ats",
    )

    with patch("src.exporters.generate_pdf", return_value=BytesIO(b"%PDF-structured")) as mock_generate_pdf:
        pdf_bytes = export_pdf_bytes(artifact)

    assert pdf_bytes == b"%PDF-structured"
    assert mock_generate_pdf.call_args.kwargs["artifact"] is artifact
    assert mock_generate_pdf.call_args.kwargs["document_kind"] == "tailored_resume"


@patch("src.exporters._generate_pdf_with_weasyprint", side_effect=RuntimeError("renderer unavailable"))
def test_export_pdf_bytes_falls_back_when_weasyprint_backend_fails(_mock_generate_pdf):
    report = _build_report()

    pdf_bytes = export_pdf_bytes(report)

    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 500


@patch("src.exporters._generate_pdf_with_reportlab", return_value=BytesIO(b"%PDF-skip"))
@patch("src.exporters._generate_pdf_with_weasyprint", side_effect=OSError("libgobject missing"))
def test_generate_pdf_falls_back_when_weasyprint_runtime_is_unavailable(
    _mock_weasyprint,
    mock_reportlab,
):
    pdf_buffer = generate_pdf("# Report", title="Test Report")

    assert pdf_buffer.getvalue() == b"%PDF-skip"
    mock_reportlab.assert_called_once_with("# Report", "Test Report")


@patch("src.exporters._generate_pdf_with_reportlab", side_effect=RuntimeError("reportlab failed"))
@patch("src.exporters._generate_pdf_with_weasyprint", side_effect=RuntimeError("weasyprint failed"))
def test_export_pdf_bytes_raises_export_error_when_both_backends_fail(
    _mock_weasyprint,
    _mock_reportlab,
):
    report = _build_report()

    try:
        export_pdf_bytes(report)
        assert False, "Expected ExportError"
    except ExportError:
        assert True


def test_export_zip_bundle_bytes_packages_all_files():
    bundle_bytes = export_zip_bundle_bytes(
        {
            "resume.md": b"resume content",
            "report.md": b"report content",
        }
    )

    with zipfile.ZipFile(BytesIO(bundle_bytes), "r") as archive:
        names = sorted(archive.namelist())
        assert names == ["report.md", "resume.md"]
        assert archive.read("resume.md") == b"resume content"
