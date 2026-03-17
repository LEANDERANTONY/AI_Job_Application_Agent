from typing import Optional

from src.schemas import (
    AgentWorkflowResult,
    ApplicationReport,
    CandidateProfile,
    FitAnalysis,
    JobDescription,
    TailoredResumeDraft,
)
from src.utils import markdown_to_text, render_markdown_list, safe_join_strings, slugify_text


def _review_status_label(review) -> str:
    if not review:
        return "Unknown"
    if review.approved and (getattr(review, "corrected_tailoring", None) or getattr(review, "corrected_strategy", None)):
        return "Approved After Corrections"
    if review.approved:
        return "Approved"
    return "Needs Revision"


def _build_title(candidate_profile: CandidateProfile, job_description: JobDescription) -> str:
    candidate_name = candidate_profile.full_name or "Candidate"
    role = job_description.title or "Target Role"
    return "{candidate} - {role} Application Package".format(
        candidate=candidate_name,
        role=role,
    )


def _build_summary(
    candidate_profile: CandidateProfile,
    job_description: JobDescription,
    fit_analysis: FitAnalysis,
    agent_result: Optional[AgentWorkflowResult],
) -> str:
    role = job_description.title or "the target role"
    if agent_result:
        return (
            "Application strategy for {role}, summarizing grounded findings, positioning guidance, and evidence-backed priorities for this role.".format(
                role=role,
            )
        )
    return (
        "Application strategy for {role}, organizing the current resume and job signals into a focused findings and positioning brief.".format(
            role=role,
        )
    )


def _build_candidate_section(candidate_profile: CandidateProfile) -> str:
    return "\n".join(
        [
            "## Candidate Snapshot",
            "",
            "- Name: {value}".format(value=candidate_profile.full_name or "Not inferred"),
            "- Location: {value}".format(value=candidate_profile.location or "Not inferred"),
            "- Source: {value}".format(value=candidate_profile.source or "Unknown"),
            "- Skills: {value}".format(
                value=safe_join_strings(candidate_profile.skills, fallback="No explicit skills detected", limit=10)
            ),
            "- Experience Entries: {value}".format(value=len(candidate_profile.experience)),
            "- Certifications: {value}".format(
                value=safe_join_strings(candidate_profile.certifications, fallback="None listed", limit=6)
            ),
        ]
    )


def _build_job_section(job_description: JobDescription) -> str:
    requirements = job_description.requirements
    return "\n".join(
        [
            "## Target Role",
            "",
            "- Title: {value}".format(value=job_description.title or "Unknown"),
            "- Location: {value}".format(value=job_description.location or "N/A"),
            "- Experience Requirement: {value}".format(
                value=requirements.experience_requirement or "N/A"
            ),
            "- Hard Skills: {value}".format(
                value=safe_join_strings(requirements.hard_skills, fallback="None extracted", limit=10)
            ),
            "- Soft Skills: {value}".format(
                value=safe_join_strings(requirements.soft_skills, fallback="None extracted", limit=8)
            ),
            "",
            "### Priority Requirements",
            render_markdown_list(requirements.must_haves, "No explicit must-have lines extracted."),
            "",
            "### Additional Signals",
            render_markdown_list(
                requirements.nice_to_haves,
                "No explicit nice-to-have lines extracted.",
            ),
        ]
    )


def _build_findings_section(
    tailored_draft: TailoredResumeDraft,
    agent_result: Optional[AgentWorkflowResult],
) -> str:
    if not agent_result:
        return "\n".join(
            [
                "## Findings",
                "",
                "- Status: Drafted from the current resume and role inputs",
                "- Note: This version reflects the currently available evidence and positioning signals.",
                "",
                "### How To Address Gaps",
                render_markdown_list(
                    tailored_draft.gap_mitigation_steps,
                    "No gap mitigation steps prepared.",
                ),
            ]
        )

    return "\n".join(
        [
            "## Findings",
            "",
            "### Fit Summary",
            agent_result.fit.fit_summary or "No fit summary produced.",
            "",
            "### Top Matches",
            render_markdown_list(agent_result.fit.top_matches, "No top matches produced."),
            "",
            "### Key Gaps",
            render_markdown_list(agent_result.fit.key_gaps, "No key gaps produced."),
            "",
            "### How To Address Gaps",
            render_markdown_list(
                tailored_draft.gap_mitigation_steps,
                "No gap mitigation steps prepared.",
            ),
            "",
            "### Tailored Summary",
            agent_result.tailoring.professional_summary
            or "No tailored professional summary produced.",
            "",
            "### What To Emphasize",
            render_markdown_list(
                agent_result.tailoring.cover_letter_themes,
                "No messaging priorities produced.",
            ),
        ]
    )


def _build_strategy_section(agent_result: Optional[AgentWorkflowResult]) -> str:
    if not agent_result:
        return "\n".join(
            [
                "## Application Strategy",
                "",
                "Current positioning guidance is based on the available resume and role evidence.",
            ]
        )

    return "\n".join(
        [
            "## Application Strategy",
            "",
            agent_result.strategy.recruiter_positioning
            if agent_result.strategy
            else "No recruiter positioning produced.",
            "",
            "### Cover Letter Talking Points",
            render_markdown_list(
                agent_result.strategy.cover_letter_talking_points if agent_result.strategy else [],
                "No cover letter talking points produced.",
            ),
            "",
            "### Portfolio / Project Emphasis",
            render_markdown_list(
                agent_result.strategy.portfolio_project_emphasis if agent_result.strategy else [],
                "No portfolio or project emphasis produced.",
            ),
        ]
    )


def build_application_report(
    candidate_profile: CandidateProfile,
    job_description: JobDescription,
    fit_analysis: FitAnalysis,
    tailored_draft: TailoredResumeDraft,
    agent_result: Optional[AgentWorkflowResult] = None,
) -> ApplicationReport:
    title = _build_title(candidate_profile, job_description)
    summary = _build_summary(candidate_profile, job_description, fit_analysis, agent_result)
    filename_stem = slugify_text(
        "{candidate}-{role}".format(
            candidate=candidate_profile.full_name or "candidate",
            role=job_description.title or "target-role",
        ),
        fallback="application-package",
    )

    markdown = "\n\n".join(
        [
            "# " + title,
            summary,
            _build_candidate_section(candidate_profile),
            _build_job_section(job_description),
            _build_findings_section(tailored_draft, agent_result),
            _build_strategy_section(agent_result),
        ]
    ).strip()

    return ApplicationReport(
        title=title,
        filename_stem=filename_stem,
        summary=summary,
        markdown=markdown,
        plain_text=markdown_to_text(markdown, bullet_marker="*"),
    )
