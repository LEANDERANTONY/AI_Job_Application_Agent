from src.report_builder import build_application_report
from src.resume_builder import build_tailored_resume_artifact
from src.schemas import (
    AgentWorkflowResult,
    FitAgentOutput,
    JobAgentOutput,
    ProfileAgentOutput,
    ResumeDocument,
    ReviewAgentOutput,
    StrategyAgentOutput,
    TailoringAgentOutput,
    WorkExperience,
)
from src.services.fit_service import build_fit_analysis
from src.services.job_service import build_job_description_from_text
from src.services.profile_service import build_candidate_profile_from_resume
from src.services.tailoring_service import build_tailored_resume_draft


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


def test_build_tailored_resume_artifact_includes_sections_and_notes():
    candidate_profile = _build_profile()
    job_description = _build_job()
    fit_analysis = build_fit_analysis(candidate_profile, job_description)
    tailored_draft = build_tailored_resume_draft(
        candidate_profile,
        job_description,
        fit_analysis,
    )

    artifact = build_tailored_resume_artifact(
        candidate_profile,
        job_description,
        fit_analysis,
        tailored_draft,
    )

    assert artifact.title == "Leander Antony - Machine Learning Engineer Tailored Resume"
    assert artifact.theme == "classic_ats"
    assert "## Professional Summary" in artifact.markdown
    assert "## Professional Experience" in artifact.markdown
    assert "## Change Summary" in artifact.markdown
    assert artifact.change_log
    assert artifact.validation_notes


def test_build_tailored_resume_artifact_prefers_agent_output_when_available():
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
            professional_summary="Agent-enhanced tailored summary.",
            rewritten_bullets=["Built production ML APIs using Python and Docker."],
            highlighted_skills=["Python", "SQL", "Docker"],
            cover_letter_themes=["Hands-on delivery fit."],
        ),
        strategy=StrategyAgentOutput(
            recruiter_positioning="Position the candidate as an implementation-first ML engineer.",
            cover_letter_talking_points=["Lead with production API delivery evidence."],
            interview_preparation_themes=["Production delivery"],
            portfolio_project_emphasis=["Highlight shipped ML API work."],
        ),
        review=ReviewAgentOutput(
            approved=True,
            grounding_issues=[],
            revision_requests=[],
            final_notes=["Grounded output."],
        ),
    )

    artifact = build_tailored_resume_artifact(
        candidate_profile,
        job_description,
        fit_analysis,
        tailored_draft,
        agent_result=agent_result,
        theme="modern_professional",
    )

    assert artifact.theme == "modern_professional"
    assert artifact.professional_summary == "Agent-enhanced tailored summary."
    assert "Built production ML APIs using Python and Docker." in artifact.markdown
    assert any("review pass" in entry.lower() or "agent" in entry.lower() for entry in artifact.change_log)