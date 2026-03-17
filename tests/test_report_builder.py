from src.report_builder import build_application_report
from src.schemas import (
    AgentWorkflowResult,
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
    assert "Source Signals" not in report.markdown
    assert "## Tailored Resume Guidance" not in report.markdown
    assert "## Deterministic Fit Analysis" not in report.markdown
    assert "## Findings" in report.markdown
    assert "### How To Address Gaps" in report.markdown
    assert "## Application Strategy" in report.markdown
    assert "Status: Drafted from the current resume and role inputs" in report.markdown
    assert "Application strategy for Machine Learning Engineer" in report.plain_text
    assert "Run the AI-assisted workflow" not in report.plain_text
    assert "## Next Actions" not in report.markdown


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
        fit=FitAgentOutput(
            fit_summary="Strong fit overall with one cloud gap.",
            top_matches=["Python", "SQL", "Docker"],
            key_gaps=["AWS"],
        ),
        tailoring=TailoringAgentOutput(
            professional_summary="Grounded tailored summary.",
            rewritten_bullets=["Built production ML APIs using Python and Docker."],
            highlighted_skills=["Python", "SQL", "Docker"],
            cover_letter_themes=["Hands-on delivery fit."],
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
    )

    report = build_application_report(
        candidate_profile,
        job_description,
        fit_analysis,
        tailored_draft,
        agent_result=agent_result,
    )

    assert "Review Status: Approved" not in report.markdown
    assert "Built production ML APIs using Python and Docker." not in report.markdown
    assert "Position the candidate as an implementation-first ML engineer." in report.markdown
    assert "What To Emphasize" in report.markdown
    assert "Top Matches" in report.markdown
    assert "Key Gaps" in report.markdown
    assert "How To Address Gaps" in report.markdown
    assert "Tailored Summary" in report.markdown
    assert "Deterministic Fit Analysis" not in report.markdown
    assert "## Tailored Resume Guidance" not in report.markdown
    assert "Review Notes" not in report.markdown
    assert "Next Actions" not in report.markdown
    assert "Grounded output." not in report.plain_text
    assert "Application strategy for Machine Learning Engineer" in report.plain_text


def test_build_application_report_marks_approved_after_corrections():
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
        fit=FitAgentOutput(fit_summary="Fit summary."),
        tailoring=TailoringAgentOutput(professional_summary="Corrected summary."),
        strategy=StrategyAgentOutput(recruiter_positioning="Corrected positioning."),
        review=ReviewAgentOutput(
            approved=True,
            grounding_issues=["Original draft overstated regression experience."],
            unresolved_issues=[],
            revision_requests=["Replace unsupported regression references."],
            final_notes=["Safe after correction."],
            corrected_tailoring=TailoringAgentOutput(professional_summary="Corrected summary."),
        ),
    )

    report = build_application_report(
        candidate_profile,
        job_description,
        fit_analysis,
        tailored_draft,
        agent_result=agent_result,
    )

    assert "Approved After Corrections" not in report.markdown
    assert "Issues Found In Incoming Draft" not in report.markdown
    assert "Unresolved Issues" not in report.markdown
    assert "Corrections Applied" not in report.markdown
