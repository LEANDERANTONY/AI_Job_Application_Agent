from typing import Optional

from src.schemas import (
    AgentWorkflowResult,
    CandidateProfile,
    CoverLetterArtifact,
    CoverLetterAgentOutput,
    FitAnalysis,
    JobDescription,
    TailoredResumeDraft,
)
from src.utils import dedupe_strings, markdown_to_text, safe_join_strings, slugify_text


def _format_output_block(text: str) -> str:
    normalized = " ".join(str(text or "").strip().split())
    return normalized


def _build_agent_generated_markdown(
    title: str,
    contact_line: str,
    cover_letter_output: CoverLetterAgentOutput,
) -> str:
    parts = ["# " + title]
    if contact_line:
        parts.extend([contact_line, ""])
    if cover_letter_output.greeting:
        parts.append(cover_letter_output.greeting.rstrip(",") + ",")
    if cover_letter_output.opening_paragraph:
        parts.append(_format_output_block(cover_letter_output.opening_paragraph))
    for paragraph in cover_letter_output.body_paragraphs:
        normalized = _format_output_block(paragraph)
        if normalized:
            parts.append(normalized)
    if cover_letter_output.closing_paragraph:
        parts.append(_format_output_block(cover_letter_output.closing_paragraph))
    signoff_lines = [item for item in [cover_letter_output.signoff, cover_letter_output.signature_name] if str(item or "").strip()]
    if signoff_lines:
        parts.append("\n".join(signoff_lines))
    return "\n\n".join(part.strip() for part in parts if str(part or "").strip())


def _final_tailoring_summary(
    tailored_draft: TailoredResumeDraft,
    agent_result: Optional[AgentWorkflowResult],
) -> str:
    if agent_result and agent_result.resume_generation and agent_result.resume_generation.professional_summary:
        return agent_result.resume_generation.professional_summary
    if agent_result and agent_result.tailoring and agent_result.tailoring.professional_summary:
        return agent_result.tailoring.professional_summary
    return tailored_draft.professional_summary


def _cover_letter_points(
    fit_analysis: FitAnalysis,
    tailored_draft: TailoredResumeDraft,
    agent_result: Optional[AgentWorkflowResult],
) -> list[str]:
    agent_points = []
    if agent_result and agent_result.strategy:
        agent_points.extend(agent_result.strategy.cover_letter_talking_points)
    if agent_result:
        agent_points.extend(agent_result.tailoring.cover_letter_themes)

    fallback_points = [
        *fit_analysis.strengths,
        *tailored_draft.priority_bullets,
        *tailored_draft.gap_mitigation_steps,
    ]
    return dedupe_strings(agent_points + fallback_points)[:4]


def _format_sentence(text: str) -> str:
    normalized = " ".join(str(text or "").strip().split())
    if not normalized:
        return ""
    if normalized[-1] not in ".!?":
        normalized += "."
    return normalized


def _opening_paragraph(
    job_description: JobDescription,
    tailored_draft: TailoredResumeDraft,
    agent_result: Optional[AgentWorkflowResult],
) -> str:
    role = job_description.title or tailored_draft.target_role or "the role"
    summary = _format_sentence(_final_tailoring_summary(tailored_draft, agent_result))
    skills = []
    if agent_result and agent_result.resume_generation:
        skills.extend(agent_result.resume_generation.highlighted_skills)
    if agent_result:
        skills.extend(agent_result.tailoring.highlighted_skills)
    skills.extend(tailored_draft.highlighted_skills)
    skills.extend(job_description.requirements.hard_skills)
    skills_text = safe_join_strings(dedupe_strings(skills), limit=4, fallback="relevant experience")
    if summary:
        return (
            "Dear Hiring Team,\n\n"
            "I am excited to apply for the {role} role. {summary} My background aligns well with the role's emphasis on {skills}."
        ).format(role=role, summary=summary, skills=skills_text)
    return (
        "Dear Hiring Team,\n\n"
        "I am excited to apply for the {role} role, bringing grounded experience that aligns with the role's emphasis on {skills}."
    ).format(role=role, skills=skills_text)


def _evidence_paragraph(
    candidate_profile: CandidateProfile,
    fit_analysis: FitAnalysis,
    tailored_draft: TailoredResumeDraft,
    agent_result: Optional[AgentWorkflowResult],
) -> str:
    points = _cover_letter_points(fit_analysis, tailored_draft, agent_result)
    latest_role = candidate_profile.experience[0] if candidate_profile.experience else None
    role_context = ""
    if latest_role:
        role_context = "Most recently, I worked as {title} at {organization}.".format(
            title=latest_role.title or "a contributor",
            organization=latest_role.organization or "a recent team",
        )
    experience_signal = _format_sentence(fit_analysis.experience_signal)
    lead_point = _format_sentence(points[0]) if points else ""
    parts = [part for part in [role_context, experience_signal, lead_point] if part]
    if not parts:
        return "My experience shows consistent delivery against the practical requirements described in the job description."
    return " ".join(parts)


def _alignment_paragraph(
    fit_analysis: FitAnalysis,
    tailored_draft: TailoredResumeDraft,
    agent_result: Optional[AgentWorkflowResult],
) -> str:
    points = _cover_letter_points(fit_analysis, tailored_draft, agent_result)
    if not points:
        return "I would bring a practical, evidence-backed approach to the role while keeping the application grounded in demonstrated work."
    formatted_points = []
    for point in points[1:3]:
        sentence = _format_sentence(point)
        if sentence:
            formatted_points.append(sentence)
    return " ".join(formatted_points) or "I would bring a practical, evidence-backed approach to the role while keeping the application grounded in demonstrated work."


def _closing_paragraph(candidate_profile: CandidateProfile, job_description: JobDescription) -> str:
    role = job_description.title or "the role"
    candidate_name = candidate_profile.full_name or "Candidate"
    return (
        "I would welcome the opportunity to discuss how my experience can support your team's priorities for {role}. "
        "Thank you for your time and consideration.\n\nSincerely,\n\n{name}"
    ).format(role=role, name=candidate_name)


def build_cover_letter_artifact(
    candidate_profile: CandidateProfile,
    job_description: JobDescription,
    fit_analysis: FitAnalysis,
    tailored_draft: TailoredResumeDraft,
    agent_result: Optional[AgentWorkflowResult] = None,
) -> CoverLetterArtifact:
    role = job_description.title or tailored_draft.target_role or "Target Role"
    title = "{name} - {role} Cover Letter".format(
        name=candidate_profile.full_name or "Candidate",
        role=role,
    )
    filename_stem = slugify_text(
        "{candidate}-{role}-cover-letter".format(
            candidate=candidate_profile.full_name or "candidate",
            role=role,
        ),
        fallback="cover-letter",
    )
    contact_line = safe_join_strings(
        [candidate_profile.location, *candidate_profile.contact_lines],
        fallback="",
    )
    markdown_parts = ["# " + title]
    if agent_result and agent_result.cover_letter:
        markdown = _build_agent_generated_markdown(title, contact_line, agent_result.cover_letter)
        summary = "Cover letter draft for {role}, generated by the approved cover letter agent and packaged for export.".format(
            role=role,
        )
        return CoverLetterArtifact(
            title=title,
            filename_stem=filename_stem,
            summary=summary,
            markdown=markdown,
            plain_text=markdown_to_text(markdown, strip_bold=True),
        )
    if contact_line:
        markdown_parts.extend([contact_line, ""])
    markdown_parts.extend(
        [
            _opening_paragraph(job_description, tailored_draft, agent_result),
            _evidence_paragraph(candidate_profile, fit_analysis, tailored_draft, agent_result),
            _alignment_paragraph(fit_analysis, tailored_draft, agent_result),
            _closing_paragraph(candidate_profile, job_description),
        ]
    )
    markdown = "\n\n".join(part.strip() for part in markdown_parts if str(part or "").strip())
    summary = "Grounded cover letter draft for {role}, assembled from the current resume, JD, and workflow outputs.".format(
        role=role,
    )
    return CoverLetterArtifact(
        title=title,
        filename_stem=filename_stem,
        summary=summary,
        markdown=markdown,
        plain_text=markdown_to_text(markdown, strip_bold=True),
    )