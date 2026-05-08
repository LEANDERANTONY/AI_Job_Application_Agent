from src.resume_builder import (
    _normalize_section_name,
    _resolve_section_order,
    build_tailored_resume_artifact,
    compute_section_order,
)
from src.schemas import (
    AgentWorkflowResult,
    CandidateProfile,
    EducationEntry,
    ProjectEntry,
    ResumeGenerationAgentOutput,
    ResumeDocument,
    ReviewAgentOutput,
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
                "leander@example.com | +91 99999 99999 | github.com/leander-antony\n"
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
    assert "## Validation Notes" not in artifact.markdown
    assert "Machine Learning Engineer" not in artifact.markdown.split("## Professional Summary", 1)[0]
    assert artifact.change_log
    assert artifact.validation_notes
    assert "leander@example.com" in artifact.header.contact_lines
    assert "+91 99999 99999" in artifact.header.contact_lines


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
        tailoring=TailoringAgentOutput(
            professional_summary="Agent-enhanced tailored summary.",
            rewritten_bullets=["Built production ML APIs using Python and Docker."],
            highlighted_skills=["Python", "SQL", "Docker"],
            cover_letter_themes=["Hands-on delivery fit."],
        ),
        review=ReviewAgentOutput(
            approved=True,
            grounding_issues=[],
            unresolved_issues=[],
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
        theme="classic_ats",
    )

    assert artifact.theme == "classic_ats"
    assert artifact.professional_summary == "Agent-enhanced tailored summary."
    assert "Built production ML APIs using Python and Docker." in artifact.markdown
    assert any("review pass" in entry.lower() or "agent" in entry.lower() for entry in artifact.change_log)
    assert "leander@example.com" in artifact.header.contact_lines
    assert "+91 99999 99999" in artifact.header.contact_lines
    assert "https://github.com/leander-antony" in artifact.header.contact_lines


def test_build_tailored_resume_artifact_always_uses_classic_theme():
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
        tailoring=TailoringAgentOutput(
            professional_summary="Agent-enhanced tailored summary.",
            rewritten_bullets=["Built production ML APIs using Python and Docker."],
            highlighted_skills=["Python", "SQL", "Docker"],
            cover_letter_themes=["Hands-on delivery fit."],
        ),
        review=ReviewAgentOutput(
            approved=True,
            grounding_issues=[],
            unresolved_issues=[],
            revision_requests=[],
            final_notes=["Grounded output."],
        ),
        resume_generation=ResumeGenerationAgentOutput(
            professional_summary="Final resume summary.",
            highlighted_skills=["Python", "SQL"],
            experience_bullets=["Built production ML APIs using Python and Docker."],
            section_order=["Professional Summary", "Core Skills", "Professional Experience"],
            template_hint="classic_ats",
        ),
    )

    artifact = build_tailored_resume_artifact(
        candidate_profile,
        job_description,
        fit_analysis,
        tailored_draft,
        agent_result=agent_result,
        theme="custom_resume_theme",
    )

    assert artifact.theme == "classic_ats"
    assert artifact.summary == "Tailored resume draft for Machine Learning Engineer, ready to review and export."


# ---------------------------------------------------------------------------
# section_order helpers
# ---------------------------------------------------------------------------


def _profile(*, experience=None, projects=None, publications=None) -> CandidateProfile:
    return CandidateProfile(
        full_name="Test Candidate",
        experience=list(experience or []),
        projects=list(projects or []),
        publications=list(publications or []),
        education=[EducationEntry(institution="Test U")],
    )


def _exp(title="Engineer", organization="Acme") -> WorkExperience:
    return WorkExperience(title=title, organization=organization)


def _proj(name="Project") -> ProjectEntry:
    return ProjectEntry(name=name)


def test_compute_section_order_routes_student_to_education_first():
    profile = _profile(experience=[], projects=[_proj(), _proj(), _proj()])

    order = compute_section_order(profile)

    # Student / no-history path: education leads, projects follow,
    # experience after.
    assert order[:3] == ["summary", "education", "projects"]
    assert order.index("experience") > order.index("projects")


def test_compute_section_order_routes_academic_when_publications_high():
    profile = _profile(
        experience=[_exp("Postdoc"), _exp("Professor")],
        publications=["P1", "P2", "P3", "P4", "P5"],
    )

    order = compute_section_order(profile)

    # Academic path: education + publications high before experience.
    assert order[:3] == ["summary", "education", "publications"]
    assert order.index("experience") > order.index("publications")


def test_compute_section_order_keeps_senior_industry_with_few_publications_on_professional_path():
    profile = _profile(
        experience=[_exp() for _ in range(5)],
        publications=["Talk 1", "Talk 2", "Talk 3"],
    )

    order = compute_section_order(profile)

    # Senior with 3 talks (not 5+ academic-shape) stays on standard
    # professional path: experience leads after summary, then skills.
    assert order[:3] == ["summary", "experience", "skills"]


def test_compute_section_order_routes_career_switcher_to_skills_and_projects_first():
    profile = _profile(
        experience=[_exp(title="Mechanical Engineer"), _exp(title="Engineer")],
        projects=[_proj(), _proj(), _proj()],
    )

    order = compute_section_order(profile)

    # Career switcher path: skills lead, then projects as proof, then
    # experience.
    assert order[:3] == ["summary", "skills", "projects"]
    assert order.index("experience") > order.index("projects")


def test_compute_section_order_default_professional_path_for_standard_resume():
    profile = _profile(experience=[_exp(), _exp(), _exp()])

    order = compute_section_order(profile)

    # Modern recruiter-readable resumes lead with Experience for
    # candidates who have work history.
    assert order[:3] == ["summary", "experience", "skills"]


def test_normalize_section_name_handles_common_aliases():
    assert _normalize_section_name("Professional Summary") == "summary"
    assert _normalize_section_name("Core Skills") == "skills"
    assert _normalize_section_name("PROFESSIONAL EXPERIENCE") == "experience"
    assert _normalize_section_name("Selected Publications") == "publications"
    assert _normalize_section_name("Licensure & Certifications") == "certifications"
    # Unknown sections return None so callers can decide policy.
    assert _normalize_section_name("Random Unknown Section") is None


def test_resolve_section_order_ignores_agent_output_and_uses_helper():
    """The agent's section_order field is ignored — we always use
    compute_section_order(profile). In practice the LLM picked
    'experience first' for every profile shape (including students
    and career switchers), which is wrong; the deterministic helper
    has all the structural signal it needs."""
    profile = _profile(experience=[], projects=[_proj(), _proj()])
    agent_result = AgentWorkflowResult(
        mode="openai",
        model="test",
        tailoring=TailoringAgentOutput(),
        review=ReviewAgentOutput(approved=True),
        resume_generation=ResumeGenerationAgentOutput(
            professional_summary="x",
            # Agent emits 'experience first' (its default) — we should
            # ignore this and pick the student path based on
            # exp_count == 0.
            section_order=["Professional Summary", "Professional Experience", "Core Skills"],
        ),
    )

    order = _resolve_section_order(profile, agent_result)

    # Student path overrides the agent's experience-first preference
    # because the candidate has no work history to lead with.
    assert order[:3] == ["summary", "education", "projects"]


def test_resolve_section_order_uses_compute_when_agent_skipped_it():
    profile = _profile(experience=[], projects=[_proj(), _proj()])
    agent_result = AgentWorkflowResult(
        mode="openai",
        model="test",
        tailoring=TailoringAgentOutput(),
        review=ReviewAgentOutput(approved=True),
        resume_generation=ResumeGenerationAgentOutput(
            professional_summary="x",
            section_order=[],  # agent skipped it
        ),
    )

    order = _resolve_section_order(profile, agent_result)

    assert order[:2] == ["summary", "education"]


def test_build_tailored_resume_artifact_renders_markdown_in_section_order_for_student():
    candidate_profile = CandidateProfile(
        full_name="Aanya Sharma",
        location="Bengaluru, India",
        skills=["Python", "Go", "Docker"],
        experience=[],  # student: no work history
        education=[EducationEntry(institution="IIT Bombay", degree="B.Tech")],
        projects=[
            ProjectEntry(name="DistKV", bullets=["Built a Raft-based KV store"]),
            ProjectEntry(name="Search Indexer", bullets=["Sub-1ms autocomplete"]),
        ],
    )
    job_description = build_job_description_from_text(
        "Software Engineer\nRequired: Python, Docker.\n"
    )
    fit_analysis = build_fit_analysis(candidate_profile, job_description)
    tailored_draft = build_tailored_resume_draft(
        candidate_profile, job_description, fit_analysis
    )

    artifact = build_tailored_resume_artifact(
        candidate_profile,
        job_description,
        fit_analysis,
        tailored_draft,
    )

    # Education must precede Projects must precede Core Skills in the
    # rendered markdown for the student path.
    md = artifact.markdown
    assert md.index("## Education") < md.index("## Projects")
    assert md.index("## Projects") < md.index("## Core Skills")
    assert artifact.section_order[:3] == ["summary", "education", "projects"]
