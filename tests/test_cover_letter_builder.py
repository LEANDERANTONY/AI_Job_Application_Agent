from src.cover_letter_builder import build_cover_letter_artifact
from src.schemas import (
    AgentWorkflowResult,
    CoverLetterAgentOutput,
    FitAgentOutput,
    ReviewAgentOutput,
    StrategyAgentOutput,
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
                "leander@example.com\n"
                "Python SQL Docker communication\n"
                "Built production ML applications."
            ),
            filetype="TXT",
            source="uploaded",
        )
    )
    profile.contact_lines = ["leander@example.com", "+91 99999 99999"]
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


def test_build_cover_letter_artifact_uses_agentic_signals_when_available():
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
        fit=FitAgentOutput(
            fit_summary="Strong fit overall with one cloud gap.",
            top_matches=["Python", "SQL", "Docker"],
            key_gaps=["AWS"],
        ),
        tailoring=TailoringAgentOutput(
            professional_summary="Grounded tailored summary.",
            rewritten_bullets=["Built production ML APIs using Python and Docker."],
            highlighted_skills=["Python", "SQL", "Docker"],
            cover_letter_themes=["Show evidence of shipping recruiter-ready ML tooling."],
        ),
        strategy=StrategyAgentOutput(
            recruiter_positioning="Position the candidate as an implementation-first ML engineer.",
            cover_letter_talking_points=["Lead with production API delivery evidence."],
            portfolio_project_emphasis=["Highlight shipped ML API work."],
        ),
        review=ReviewAgentOutput(
            approved=True,
            grounding_issues=[],
            unresolved_issues=[],
            revision_requests=[],
            final_notes=["Grounded output."],
        ),
        cover_letter=CoverLetterAgentOutput(
            greeting="Dear Hiring Team",
            opening_paragraph="I am excited to apply for the Machine Learning Engineer role with grounded production evidence.",
            body_paragraphs=[
                "Lead with production API delivery evidence.",
                "Show evidence of shipping recruiter-ready ML tooling.",
            ],
            closing_paragraph="I would welcome the opportunity to discuss how my experience can support your team.",
            signoff="Sincerely",
            signature_name="Leander Antony",
        ),
    )

    artifact = build_cover_letter_artifact(
        candidate_profile,
        job_description,
        fit_analysis,
        tailored_draft,
        agent_result=agent_result,
    )

    assert artifact.title == "Leander Antony - Machine Learning Engineer Cover Letter"
    assert artifact.filename_stem == "leander-antony-machine-learning-engineer-cover-letter"
    assert "Dear Hiring Team," in artifact.markdown
    assert "Lead with production API delivery evidence." in artifact.markdown
    assert "Show evidence of shipping recruiter-ready ML tooling." in artifact.markdown
    assert "I am excited to apply for the Machine Learning Engineer role with grounded production evidence." in artifact.markdown
    assert "Sincerely" in artifact.plain_text


def test_build_cover_letter_artifact_falls_back_to_workflow_outputs_without_agent_result():
    candidate_profile = _build_profile()
    job_description = _build_job()
    fit_analysis = build_fit_analysis(candidate_profile, job_description)
    tailored_draft = build_tailored_resume_draft(
        candidate_profile,
        job_description,
        fit_analysis,
    )

    artifact = build_cover_letter_artifact(
        candidate_profile,
        job_description,
        fit_analysis,
        tailored_draft,
    )

    assert "Machine Learning Engineer" in artifact.markdown
    assert "Leander Antony" in artifact.markdown
    assert "Thank you for your time and consideration." in artifact.markdown
    assert artifact.summary.startswith("Grounded cover letter draft")