from src.schemas import ResumeDocument
from src.services.profile_service import (
    build_candidate_profile_from_resume,
    build_candidate_context_text,
)


def test_build_candidate_profile_from_resume_extracts_core_signals():
    document = ResumeDocument(
        text=(
            "Leander Antony\n"
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
    assert len(profile.certifications) == 2
    assert any("Python 3 Programming Specialization" in item for item in profile.certifications)
    assert any("Structured 3 project entries" in signal for signal in profile.source_signals)
