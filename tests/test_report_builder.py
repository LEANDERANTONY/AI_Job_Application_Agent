from src.report_builder import build_application_report
from src.schemas import (
    AgentWorkflowResult,
    FitAgentOutput,
    JobAgentOutput,
    ProfileAgentOutput,
    ReviewAgentOutput,
    TailoringAgentOutput,
)
from src.services.fit_service import build_fit_analysis
from src.services.job_service import build_job_description_from_text
from src.services.profile_service import build_candidate_profile_from_resume
from src.services.tailoring_service import build_tailored_resume_draft
from src.schemas import ResumeDocument, WorkExperience


def _build_profile():
    profile = build_candidate_profile_from_resume(
        ResumeDocument(
            text=(
                "Leander Antony\n"
                "Chennai, India\n"
                "Python SQL Docker communication\n"
                "Built production ML applications."
            ),
            filetype="TXT",
            source="uploaded",
        )
    )
    profile.experience = [
        WorkExperience(
            title="AI Engineer",
            organization="Example Labs",
            description="Built production ML APIs and model evaluation workflows.",
            start={"year": 2023},
            end={"year": 2025},
        )
    ]
    return profile


def _build_job():
    return build_job_description_from_text(
        "Machine Learning Engineer\n"
        "Location: Chennai, India\n"
        "Required: Python, SQL, Docker, AWS, communication.\n"
        "Must have experience deploying ML services.\n"
        "Need 3+ years of experience.\n"
    )


def test_build_application_report_includes_core_sections():
    candidate_profile = _build_profile()
    job_description = _build_job()
    fit_analysis = build_fit_analysis(candidate_profile, job_description)
    tailored_draft = build_tailored_resume_draft(
        candidate_profile,
        job_description,
        fit_analysis,
    )

    report = build_application_report(
        candidate_profile,
        job_description,
        fit_analysis,
        tailored_draft,
    )

    assert report.title == "Leander Antony - Machine Learning Engineer Application Package"
    assert report.filename_stem == "leander-antony-machine-learning-engineer"
    assert "## Candidate Snapshot" in report.markdown
    assert "## Deterministic Fit Analysis" in report.markdown
    assert "## Supervised Workflow" in report.markdown
    assert "Status: Not run" in report.markdown
    assert "Fit Score" in report.plain_text


def test_build_application_report_includes_agent_sections_when_available():
    candidate_profile = _build_profile()
    job_description = _build_job()
    fit_analysis = build_fit_analysis(candidate_profile, job_description)
    tailored_draft = build_tailored_resume_draft(
        candidate_profile,
        job_description,
        fit_analysis,
    )
    agent_result = AgentWorkflowResult(
        mode="openai",
        model="gpt-test",
        profile=ProfileAgentOutput(
            positioning_headline="Applied AI engineer with grounded delivery evidence",
            evidence_highlights=["Python delivery", "Production ML APIs"],
            strengths=["Strong implementation evidence"],
            cautions=["AWS is not directly evidenced"],
        ),
        job=JobAgentOutput(
            requirement_summary="Production ML role.",
            priority_skills=["Python", "SQL", "Docker", "AWS"],
            must_have_themes=["Production ML systems"],
            messaging_guidance=["Mirror implementation language from the JD."],
        ),
        fit=FitAgentOutput(
            fit_summary="Strong fit overall with one cloud gap.",
            top_matches=["Python", "SQL", "Docker"],
            key_gaps=["AWS"],
            interview_themes=["Production delivery"],
        ),
        tailoring=TailoringAgentOutput(
            professional_summary="Grounded tailored summary.",
            rewritten_bullets=["Built production ML APIs using Python and Docker."],
            highlighted_skills=["Python", "SQL", "Docker"],
            cover_letter_themes=["Hands-on delivery fit."],
        ),
        review=ReviewAgentOutput(
            approved=True,
            grounding_issues=[],
            revision_requests=[],
            final_notes=["Grounded output."],
        ),
    )

    report = build_application_report(
        candidate_profile,
        job_description,
        fit_analysis,
        tailored_draft,
        agent_result=agent_result,
    )

    assert "Review Status: Approved" in report.markdown
    assert "Applied AI engineer with grounded delivery evidence" in report.markdown
    assert "Built production ML APIs using Python and Docker." in report.markdown
    assert "Grounded output." in report.plain_text
