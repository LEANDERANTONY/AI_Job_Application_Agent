from pathlib import Path

from src.parsers.resume import parse_resume_document
from src.schemas import ResumeDocument
from src.services.profile_service import (
    build_candidate_profile_from_resume,
    build_candidate_context_text,
)


def test_build_candidate_profile_from_resume_extracts_core_signals():
    document = ResumeDocument(
        text=(
            "Leander Antony\n"
            "leander@example.com | +91 99999 99999 | linkedin.com/in/leander-antony\n"
            "Chennai, India\n"
            "Machine Learning Engineer\n"
            "Python SQL Docker communication"
        ),
        filetype="PDF",
        source="uploaded",
    )

    profile = build_candidate_profile_from_resume(document)

    assert profile.full_name == "Leander Antony"
    assert profile.location == "Chennai, India"
    assert "leander@example.com" in profile.contact_lines
    assert "+91 99999 99999" in profile.contact_lines
    assert "https://linkedin.com/in/leander-antony" in profile.contact_lines
    assert {"Python", "SQL", "Docker", "communication"}.issubset(set(profile.skills))
    assert "Resume parsed from PDF upload." in profile.source_signals


def test_build_candidate_context_text_uses_resume_fields_only():
    profile = build_candidate_profile_from_resume(
        ResumeDocument(
            text="Leander Antony\nChennai, India\nPython SQL\nBuilt ML services.",
            filetype="TXT",
            source="uploaded",
        )
    )

    context = build_candidate_context_text(profile)

    assert "Leander Antony" in context
    assert "Python SQL" in context


def test_build_candidate_profile_from_resume_extracts_projects_education_and_certifications():
    document = ResumeDocument(
        text=(
            "Leander Antony A\n"
            "Chennai, India\n"
            "Professional Summary\n"
            "Mechanical engineering graduate transitioning into AI/ML.\n"
            "Technical Skills\n"
            "Python, XGBoost, TensorFlow, Pandas\n"
            "Projects\n"
            "Ongoing\n"
            "• Multi-Modal Deep Learning for Early Pancreatic Cancer Detection\n"
            "- Designed multi-modal AI pipeline integrating CECT imaging and biomarkers.\n"
            "Completed\n"
            "• Credit Card Fraud Detection\n"
            "Built a fraud classification system on a highly imbalanced dataset using XGBoost.\n"
            "• Generative AI QA RAG System for Insurance Policy documents\n"
            "Designed a retrieval-augmented generation system using LangChain and ChromaDB.\n"
            "Education\n"
            "Master of Science in AI/ML from Liverpool John Moores University • Jan 2025 – Jan 2026\n"
            "Executive PG Program in Machine Learning & Artificial Intelligence with specialization in Generative AI IIIT Bangalore • Oct 2023 – Oct 2024\n"
            "Certifications\n"
            "• Data Science: R Basics - Harvard (edX), Dec 2019\n"
            "• Python 3 Programming Specialization – University of Michigan (Coursera), Nov 2025\n"
        ),
        filetype="PDF",
        source="uploaded",
    )

    profile = build_candidate_profile_from_resume(document)

    assert len(profile.experience) >= 3
    assert any(entry.title == "Credit Card Fraud Detection" for entry in profile.experience)
    assert any("LangChain" in entry.description for entry in profile.experience)
    assert len(profile.education) >= 2
    assert any("Master of Science in AI/ML" in entry.degree for entry in profile.education)
    assert any(entry.institution == "Liverpool John Moores University" for entry in profile.education)
    assert any(entry.institution == "IIIT Bangalore" for entry in profile.education)
    assert any("specialization in Generative AI" in entry.degree for entry in profile.education)
    assert len(profile.certifications) == 2
    assert any("Python 3 Programming Specialization" in item for item in profile.certifications)
    assert any("Structured 3 project entries" in signal for signal in profile.source_signals)


def test_build_candidate_profile_from_resume_handles_wrapped_education_specialization_lines():
    document = ResumeDocument(
        text=(
            "Leander Antony A\n"
            "Education\n"
            "Executive PG Program in Machine Learning & Artificial Intelligence with specialization in\n"
            "Generative AI IIIT Bangalore • Oct 2023 – Oct 2024\n"
        ),
        filetype="PDF",
        source="uploaded",
    )

    profile = build_candidate_profile_from_resume(document)

    assert len(profile.education) == 1
    assert profile.education[0].institution == "IIIT Bangalore"
    assert "specialization in Generative AI" in profile.education[0].degree
    assert profile.education[0].start == "Oct 2023 – Oct 2024"


def test_build_candidate_profile_from_sample_resume_pdf_extracts_expected_education():
    sample_path = Path(__file__).resolve().parents[1] / "static" / "demo_resume" / "LeanderAntony_Resume.pdf"

    with sample_path.open("rb") as handle:
        document = parse_resume_document(handle, source="sample:LeanderAntony_Resume.pdf")

    profile = build_candidate_profile_from_resume(document)

    assert document.filetype == "PDF"
    assert len(profile.education) >= 3
    assert any(entry.institution == "Liverpool John Moores University" for entry in profile.education)
    assert any(entry.institution == "IIIT Bangalore" for entry in profile.education)
    assert any(entry.institution == "Manipal Institute of Technology" for entry in profile.education)
    assert any(
        entry.degree == "Executive PG Program in Machine Learning & Artificial Intelligence with specialization in Generative AI"
        for entry in profile.education
    )


def test_build_candidate_profile_from_black_sample_resume_recovers_name_and_education():
    sample_path = Path(__file__).resolve().parents[1] / "static" / "demo_resume" / "Black White Beige Simple Modern Tech Resume.pdf"

    with sample_path.open("rb") as handle:
        document = parse_resume_document(handle, source="sample:Black White Beige Simple Modern Tech Resume.pdf")

    profile = build_candidate_profile_from_resume(document)

    assert profile.full_name == "Henrietta Mitchell"
    assert "hello@reallygreatsite.com" in profile.contact_lines
    assert len(profile.education) >= 1
    assert any("Master of Business Administration" in entry.degree for entry in profile.education)
    assert len(profile.experience) >= 3
    assert any(entry.title == "Senior Product Manager" for entry in profile.experience)
    assert "Certified Agile Product Leader ( CAPL )" in profile.certifications


def test_build_candidate_profile_from_blue_sample_resume_recovers_name_and_education():
    sample_path = Path(__file__).resolve().parents[1] / "static" / "demo_resume" / "Blue Geometric Lines Professional UX Design Tech Resume.pdf"

    with sample_path.open("rb") as handle:
        document = parse_resume_document(handle, source="sample:Blue Geometric Lines Professional UX Design Tech Resume.pdf")

    profile = build_candidate_profile_from_resume(document)

    assert profile.full_name == "ESTELLE DARCY"
    assert "hello@reallygreatsite.com" in profile.contact_lines
    assert "https://www.reallygreatsite.com" in profile.contact_lines
    assert len(profile.education) == 1
    assert profile.education[0].institution == "Engineering University"
    assert profile.education[0].degree == "Bachelor of Design in Process Engineering"
    assert profile.education[0].start == "May 2014 - May 2016"
    assert any(entry.title == "System UX Engineer" for entry in profile.experience)
    assert "Professional Design Engineer ( PDE ) License" in profile.certifications
    assert "Project Management Tech ( PMT )" in profile.certifications


def test_build_candidate_profile_from_black_and_white_test_resume_recovers_experience():
    sample_path = Path(__file__).resolve().parents[1] / "static" / "demo_resume" / "test" / "Black and White Modern Professional Resume.pdf"

    with sample_path.open("rb") as handle:
        document = parse_resume_document(handle, source="sample:Black and White Modern Professional Resume.pdf")

    profile = build_candidate_profile_from_resume(document)

    assert profile.full_name == "ESTELLE DARCY"
    assert "hello@reallygreatsite.com" in profile.contact_lines
    assert any(entry.title == "Internship" for entry in profile.experience)
    assert any(entry.title == "Instrument Tech" for entry in profile.experience)
    assert any(entry.institution == "Engineering University" for entry in profile.education)
    assert "Professional Design Engineer ( PDE ) License" in profile.certifications


def test_build_candidate_profile_from_blue_and_white_test_resume_recovers_experience():
    sample_path = Path(__file__).resolve().parents[1] / "static" / "demo_resume" / "test" / "Blue and White Professional Resume.pdf"

    with sample_path.open("rb") as handle:
        document = parse_resume_document(handle, source="sample:Blue and White Professional Resume.pdf")

    profile = build_candidate_profile_from_resume(document)

    assert profile.full_name == "Rachelle Beaudry"
    assert "hello@reallygreatsite.com" in profile.contact_lines
    assert any(entry.title == "Accounting Executive" for entry in profile.experience)
    assert any(entry.title == "Accountant" for entry in profile.experience)
    assert any(entry.institution == "Rimberio University" for entry in profile.education)
    assert "Certified Financial Analyst" in profile.certifications


def test_build_candidate_profile_from_purple_and_white_test_resume_recovers_experience():
    sample_path = Path(__file__).resolve().parents[1] / "static" / "demo_resume" / "test" / "Purple and White Clean and Professional Resume.pdf"

    with sample_path.open("rb") as handle:
        document = parse_resume_document(handle, source="sample:Purple and White Clean and Professional Resume.pdf")

    profile = build_candidate_profile_from_resume(document)

    assert profile.full_name == "JACQUELINE THOMPSON"
    assert "hello@reallygreatsite.com" in profile.contact_lines
    assert any(entry.title == "Engineering Executive" for entry in profile.experience)
    assert any(entry.title == "Project Engineer" for entry in profile.experience)
    assert any(entry.institution == "University of Engineering and Technology" for entry in profile.education)
    assert "Professional Engineer ( PE ) License" in profile.certifications
