from io import BytesIO
from unittest.mock import patch

from src.errors import ExportError

from src.exporters import _build_resume_html, build_cover_letter_preview_html, export_markdown_bytes, export_pdf_bytes, generate_pdf
from src.schemas import CoverLetterArtifact, EducationEntry, ResumeDocument, ResumeExperienceEntry, ResumeHeader, TailoredResumeArtifact, WorkExperience


def test_export_markdown_bytes_returns_utf8_bytes():
    artifact = TailoredResumeArtifact(
        title="Tailored Resume",
        filename_stem="tailored-resume",
        summary="Structured resume",
        markdown="# Resume\n\nGrounded summary.",
        plain_text="Resume\n\nGrounded summary.",
        theme="classic_ats",
    )

    markdown_bytes = export_markdown_bytes(artifact)

    assert isinstance(markdown_bytes, bytes)
    assert markdown_bytes.decode("utf-8").startswith("# ")


def test_build_cover_letter_preview_html_contains_structure():
    artifact = CoverLetterArtifact(
        title="Leander Antony - Data Analyst Cover Letter",
        filename_stem="candidate-cover-letter",
        summary="Grounded cover letter draft.",
        markdown="# Leander Antony - Data Analyst Cover Letter\n\nDear Hiring Team,\n\nI am excited to apply for the role.",
        plain_text="Leander Antony - Data Analyst Cover Letter\n\nDear Hiring Team,\n\nI am excited to apply for the role.",
    )

    html_output = build_cover_letter_preview_html(artifact)

    assert 'class="cover-letter-title"' in html_output
    assert "Leander Antony" in html_output
    assert 'class="cover-letter-role"' in html_output
    assert "Data Analyst" in html_output
    assert "Dear Hiring Team" in html_output
    assert 'class="cover-letter-greeting-break"' in html_output
    assert "font-size: 11.4pt;" in html_output


def test_build_resume_html_uses_classic_template_with_warm_neutral_palette():
    html_output = _build_resume_html("# Candidate\n\n## Experience", theme="classic_ats")

    assert "resume-shell--classic" in html_output
    assert "@page {{ size: A4; margin: 0; }}" not in html_output
    assert "@page { size: A4; margin: 0; }" in html_output
    # Warm-brown palette values must appear in the :root block; the
    # rest of the CSS now references them via var(--*) so we no
    # longer assert on the literal property declarations.
    assert "#221912" in html_output  # --ink
    assert "#fffdf9" in html_output  # --paper
    assert "#fffdfa" in html_output  # --surface
    assert "#8f6845" in html_output  # --accent (warm brown)
    assert "#d7c2af" in html_output  # --line
    assert "margin: 0 -15mm 6px;" in html_output
    # Structural classes are still here.
    assert ".resume-experience-card + .resume-experience-card" in html_output
    assert ".resume-classic-section--plain-head h2" in html_output
    # Pagination guards added when we lifted the one-page clip.
    assert "page-break-inside: avoid" in html_output


def test_build_resume_html_omits_empty_contact_card():
    artifact = TailoredResumeArtifact(
        title="Tailored Resume",
        filename_stem="tailored-resume",
        summary="Structured resume",
        markdown="# Resume",
        plain_text="Resume",
        theme="classic_ats",
        header=ResumeHeader(
            full_name="Leander Antony",
            location="Chennai, India",
            contact_lines=[],
        ),
        target_role="AI Engineer",
        professional_summary="Builds grounded AI workflow products.",
        highlighted_skills=["Python", "SQL"],
        experience_entries=[],
        education_entries=[],
        certifications=[],
        validation_notes=["Internal only"],
    )

    html_output = _build_resume_html(artifact.markdown, theme="classic_ats", artifact=artifact)

    assert "<h2>Contact</h2>" not in html_output


def test_build_resume_html_renders_classic_ats_as_single_column_blue_layout():
    artifact = TailoredResumeArtifact(
        title="Tailored Resume",
        filename_stem="tailored-resume",
        summary="Structured resume",
        markdown="# Resume",
        plain_text="Resume",
        theme="classic_ats",
        header=ResumeHeader(
            full_name="Leander Antony",
            location="Chennai, India",
            contact_lines=["leander@example.com", "+91 99999 99999"],
        ),
        target_role="AI Engineer",
        professional_summary="Builds grounded AI workflow products.",
        highlighted_skills=["Python", "SQL"],
        experience_entries=[
            ResumeExperienceEntry(
                title="AI Engineer",
                organization="Example Labs",
                location="Remote",
                start="2023",
                end="Present",
                bullets=["Built ML workflow products."],
            )
        ],
        education_entries=[],
        certifications=[],
    )

    html_output = _build_resume_html(artifact.markdown, theme="classic_ats", artifact=artifact)

    assert "resume-classic-header" in html_output
    assert "resume-contact-inline" in html_output
    assert "resume-classic-section" in html_output
    assert "resume-classic-sidebar" not in html_output
    assert "resume-modern-contact" not in html_output
    assert '<p class="resume-classic-role">' not in html_output
    assert "Chennai, India" in html_output
    assert "leander@example.com" in html_output


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


def test_export_pdf_bytes_treats_cover_letter_as_cover_letter_document():
    artifact = CoverLetterArtifact(
        title="Candidate Cover Letter",
        filename_stem="candidate-cover-letter",
        summary="Grounded cover letter draft.",
        markdown="# Candidate Cover Letter\n\nDear Hiring Team,\n\nI am excited to apply for the role.",
        plain_text="Candidate Cover Letter\n\nDear Hiring Team,\n\nI am excited to apply for the role.",
    )

    with patch("src.exporters.generate_pdf", return_value=BytesIO(b"%PDF-cover-letter")) as mock_generate_pdf:
        pdf_bytes = export_pdf_bytes(artifact)

    assert pdf_bytes == b"%PDF-cover-letter"
    assert mock_generate_pdf.call_args.kwargs["artifact"] is None
    assert mock_generate_pdf.call_args.kwargs["document_kind"] == "cover_letter"


@patch("src.exporters._generate_pdf_with_weasyprint", side_effect=RuntimeError("renderer unavailable"))
def test_export_pdf_bytes_falls_back_when_weasyprint_backend_fails(_mock_generate_pdf):
    artifact = CoverLetterArtifact(
        title="Candidate Cover Letter",
        filename_stem="candidate-cover-letter",
        summary="Grounded cover letter draft.",
        markdown="# Candidate Cover Letter\n\nDear Hiring Team,\n\nI am excited to apply for the role.",
        plain_text="Candidate Cover Letter\n\nDear Hiring Team,\n\nI am excited to apply for the role.",
    )

    pdf_bytes = export_pdf_bytes(artifact)

    assert pdf_bytes.startswith(b"%PDF")
    assert len(pdf_bytes) > 500


@patch("src.exporters._generate_pdf_with_reportlab", return_value=BytesIO(b"%PDF-skip"))
@patch("src.exporters._generate_pdf_with_weasyprint", side_effect=OSError("libgobject missing"))
def test_generate_pdf_falls_back_when_weasyprint_runtime_is_unavailable(
    _mock_weasyprint,
    mock_reportlab,
):
    pdf_buffer = generate_pdf("# Resume", title="Test Resume")

    assert pdf_buffer.getvalue() == b"%PDF-skip"
    mock_reportlab.assert_called_once_with("# Resume", "Test Resume")


@patch("src.exporters._generate_pdf_with_reportlab", side_effect=RuntimeError("reportlab failed"))
@patch("src.exporters._generate_pdf_with_weasyprint", side_effect=RuntimeError("weasyprint failed"))
def test_export_pdf_bytes_raises_export_error_when_both_backends_fail(
    _mock_weasyprint,
    _mock_reportlab,
):
    artifact = CoverLetterArtifact(
        title="Candidate Cover Letter",
        filename_stem="candidate-cover-letter",
        summary="Grounded cover letter draft.",
        markdown="# Candidate Cover Letter\n",
        plain_text="Candidate Cover Letter\n",
    )

    try:
        export_pdf_bytes(artifact)
        assert False, "Expected ExportError"
    except ExportError:
        assert True
