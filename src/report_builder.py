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
    mode = "Agent-enhanced" if agent_result else "Deterministic"
    return (
        "{mode} application package for {role} with fit score {score}/100 ({label}).".format(
            mode=mode,
            role=job_description.title or "the target role",
            score=fit_analysis.overall_score,
            label=fit_analysis.readiness_label,
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
            "",
            "### Source Signals",
            render_markdown_list(
                candidate_profile.source_signals,
                "No source signals available.",
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
            "### Must-Have Themes",
            render_markdown_list(requirements.must_haves, "No explicit must-have lines extracted."),
            "",
            "### Nice-To-Have Themes",
            render_markdown_list(
                requirements.nice_to_haves,
                "No explicit nice-to-have lines extracted.",
            ),
        ]
    )


def _build_fit_section(fit_analysis: FitAnalysis) -> str:
    return "\n".join(
        [
            "## Deterministic Fit Analysis",
            "",
            "- Fit Score: {score}/100".format(score=fit_analysis.overall_score),
            "- Readiness: {label}".format(label=fit_analysis.readiness_label),
            "- Experience Signal: {value}".format(value=fit_analysis.experience_signal),
            "",
            "### Matched Hard Skills",
            render_markdown_list(
                fit_analysis.matched_hard_skills,
                "No matched hard-skill evidence found.",
            ),
            "",
            "### Missing Hard Skills",
            render_markdown_list(
                fit_analysis.missing_hard_skills,
                "No hard-skill gaps detected.",
            ),
            "",
            "### Strengths",
            render_markdown_list(fit_analysis.strengths, "No strengths surfaced."),
            "",
            "### Gaps",
            render_markdown_list(fit_analysis.gaps, "No major gaps surfaced."),
            "",
            "### Recommendations",
            render_markdown_list(
                fit_analysis.recommendations,
                "No recommendations available.",
            ),
        ]
    )


def _build_tailoring_section(tailored_draft: TailoredResumeDraft) -> str:
    return "\n".join(
        [
            "## Tailored Resume Guidance",
            "",
            "### Professional Summary Draft",
            tailored_draft.professional_summary or "No professional summary drafted.",
            "",
            "### Highlighted Skills",
            render_markdown_list(
                tailored_draft.highlighted_skills,
                "No highlighted skills prepared.",
            ),
            "",
            "### Priority Bullets",
            render_markdown_list(
                tailored_draft.priority_bullets,
                "No priority bullets prepared.",
            ),
            "",
            "### Gap Mitigation Steps",
            render_markdown_list(
                tailored_draft.gap_mitigation_steps,
                "No gap mitigation steps prepared.",
            ),
        ]
    )


def _build_agent_section(agent_result: Optional[AgentWorkflowResult]) -> str:
    if not agent_result:
        return "\n".join(
            [
                "## Supervised Workflow",
                "",
                "- Status: Not run",
                "- Note: Run the supervised workflow to add profile positioning, fit narrative, tailored wording, and review notes.",
            ]
        )

    return "\n".join(
        [
            "## Supervised Workflow",
            "",
            "- Mode: {value}".format(value=agent_result.mode),
            "- Model: {value}".format(value=agent_result.model),
            "- Review Status: {value}".format(
                value="Approved" if agent_result.review.approved else "Needs Revision"
            ),
            "",
            "### Profile Positioning",
            agent_result.profile.positioning_headline or "No positioning headline produced.",
            "",
            "#### Evidence Highlights",
            render_markdown_list(
                agent_result.profile.evidence_highlights,
                "No evidence highlights produced.",
            ),
            "",
            "#### Job Messaging Guidance",
            render_markdown_list(
                agent_result.job.messaging_guidance,
                "No messaging guidance produced.",
            ),
            "",
            "### Fit Narrative",
            agent_result.fit.fit_summary or "No fit summary produced.",
            "",
            "#### Top Matches",
            render_markdown_list(agent_result.fit.top_matches, "No top matches produced."),
            "",
            "#### Key Gaps",
            render_markdown_list(agent_result.fit.key_gaps, "No key gaps produced."),
            "",
            "#### Interview Themes",
            render_markdown_list(
                agent_result.fit.interview_themes,
                "No interview themes produced.",
            ),
            "",
            "### Tailoring Output",
            agent_result.tailoring.professional_summary
            or "No tailored professional summary produced.",
            "",
            "#### Rewritten Bullets",
            render_markdown_list(
                agent_result.tailoring.rewritten_bullets,
                "No rewritten bullets produced.",
            ),
            "",
            "#### Cover Letter Themes",
            render_markdown_list(
                agent_result.tailoring.cover_letter_themes,
                "No cover letter themes produced.",
            ),
            "",
            "### Application Strategy",
            agent_result.strategy.recruiter_positioning
            if agent_result.strategy
            else "No recruiter positioning produced.",
            "",
            "#### Cover Letter Talking Points",
            render_markdown_list(
                agent_result.strategy.cover_letter_talking_points if agent_result.strategy else [],
                "No cover letter talking points produced.",
            ),
            "",
            "#### Interview Preparation Themes",
            render_markdown_list(
                agent_result.strategy.interview_preparation_themes if agent_result.strategy else [],
                "No interview preparation themes produced.",
            ),
            "",
            "#### Portfolio / Project Emphasis",
            render_markdown_list(
                agent_result.strategy.portfolio_project_emphasis if agent_result.strategy else [],
                "No portfolio or project emphasis produced.",
            ),
            "",
            "### Review Notes",
            "#### Grounding Issues",
            render_markdown_list(
                agent_result.review.grounding_issues,
                "No grounding issues detected.",
            ),
            "",
            "#### Revision Requests",
            render_markdown_list(
                agent_result.review.revision_requests,
                "No revisions requested.",
            ),
            "",
            "#### Final Notes",
            render_markdown_list(agent_result.review.final_notes, "No final notes produced."),
        ]
    )


def _build_next_actions(
    fit_analysis: FitAnalysis,
    agent_result: Optional[AgentWorkflowResult],
) -> str:
    items = []
    if fit_analysis.missing_hard_skills:
        items.append(
            "Tighten evidence around: " + safe_join_strings(fit_analysis.missing_hard_skills, limit=4) + "."
        )
    if not agent_result:
        items.append("Run the supervised workflow before sharing or exporting the package.")
    elif not agent_result.review.approved:
        items.extend(agent_result.review.revision_requests[:2])
    items.append("Export the package and use it to guide resume edits and recruiter outreach.")
    return "\n".join(
        [
            "## Next Actions",
            "",
            render_markdown_list(items, "No next actions available."),
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
            _build_fit_section(fit_analysis),
            _build_tailoring_section(tailored_draft),
            _build_agent_section(agent_result),
            _build_next_actions(fit_analysis, agent_result),
        ]
    ).strip()

    return ApplicationReport(
        title=title,
        filename_stem=filename_stem,
        summary=summary,
        markdown=markdown,
        plain_text=markdown_to_text(markdown, bullet_marker="*"),
    )
