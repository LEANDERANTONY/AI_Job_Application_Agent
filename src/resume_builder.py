import re
from typing import Iterable, Optional

from src.schemas import (
    AgentWorkflowResult,
    CandidateProfile,
    EducationEntry,
    FitAnalysis,
    JobDescription,
    ResumeExperienceEntry,
    ResumeHeader,
    TailoredResumeArtifact,
    TailoredResumeDraft,
)
from src.utils import dedupe_strings


RESUME_THEMES = {
    "classic_ats": {
        "label": "Classic ATS",
        "tagline": "Single-column, ATS-safe, recruiter-readable structure.",
    },
    "modern_professional": {
        "label": "Modern Professional",
        "tagline": "Cleaner hierarchy with a slightly more polished visual rhythm.",
    },
}


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return normalized or "tailored-resume"


def _safe_join(values: Iterable[str], fallback: str = "N/A", limit: Optional[int] = None) -> str:
    cleaned = []
    seen = set()
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized.lower() not in seen:
            cleaned.append(normalized)
            seen.add(normalized.lower())
    if limit is not None:
        cleaned = cleaned[:limit]
    return ", ".join(cleaned) if cleaned else fallback


def _render_markdown_list(items: Iterable[str], empty_state: str) -> str:
    cleaned = [str(item or "").strip() for item in items if str(item or "").strip()]
    if not cleaned:
        return "- {empty}".format(empty=empty_state)
    return "\n".join("- {item}".format(item=item) for item in cleaned)


def _markdown_to_text(markdown: str) -> str:
    text = re.sub(r"^#{1,6}\s*", "", markdown, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _normalize_date_token(token) -> str:
    if isinstance(token, dict):
        year = token.get("year")
        month = token.get("month")
        if year and month:
            return "{month:02d}/{year}".format(month=int(month), year=int(year))
        if year:
            return str(year)
    return str(token or "").strip()


def _description_to_bullets(description: str) -> list[str]:
    normalized = str(description or "").replace("\r", "\n")
    lines = [line.strip(" -\t") for line in normalized.splitlines() if line.strip()]
    if len(lines) > 1:
        return dedupe_strings(lines[:3])

    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?])\s+", normalized)
        if sentence.strip()
    ]
    return dedupe_strings(sentences[:3])


def _build_header(candidate_profile: CandidateProfile) -> ResumeHeader:
    contact_lines = []
    if candidate_profile.location:
        contact_lines.append(candidate_profile.location)
    return ResumeHeader(
        full_name=candidate_profile.full_name,
        location=candidate_profile.location,
        contact_lines=contact_lines,
    )


def _build_experience_entries(
    candidate_profile: CandidateProfile,
    tailored_draft: TailoredResumeDraft,
    agent_result: Optional[AgentWorkflowResult],
) -> list[ResumeExperienceEntry]:
    rewritten_bullets = (
        list(agent_result.resume_generation.experience_bullets)
        if agent_result and agent_result.resume_generation
        else list(agent_result.tailoring.rewritten_bullets) if agent_result else []
    )
    fallback_bullets = list(tailored_draft.priority_bullets)
    experience_entries = []

    for index, experience in enumerate(candidate_profile.experience[:4]):
        bullets = []
        if index < len(rewritten_bullets):
            bullets.append(rewritten_bullets[index])
        bullets.extend(_description_to_bullets(experience.description))
        if not bullets and index < len(fallback_bullets):
            bullets.append(fallback_bullets[index])
        experience_entries.append(
            ResumeExperienceEntry(
                title=experience.title or "Relevant Experience",
                organization=experience.organization,
                location=experience.location,
                start=_normalize_date_token(experience.start),
                end=_normalize_date_token(experience.end),
                bullets=dedupe_strings(bullets[:3]),
            )
        )

    return experience_entries


def _build_change_log(
    job_description: JobDescription,
    tailored_draft: TailoredResumeDraft,
    agent_result: Optional[AgentWorkflowResult],
    theme: str,
) -> list[str]:
    theme_label = RESUME_THEMES.get(theme, RESUME_THEMES["classic_ats"])["label"]
    items = [
        "Tailored the resume toward {role}.".format(
            role=job_description.title or tailored_draft.target_role or "the target role"
        ),
        "Applied the {theme} template for a consistent export layout.".format(theme=theme_label),
    ]
    if tailored_draft.highlighted_skills:
        items.append(
            "Emphasized skills aligned to the JD: {skills}.".format(
                skills=", ".join(tailored_draft.highlighted_skills[:4])
            )
        )
    if agent_result and agent_result.review_history:
        items.append(
            "Used {count} review pass(es) before generating the final resume draft.".format(
                count=len(agent_result.review_history)
            )
        )
    elif agent_result:
        items.append("Used supervised agent output to strengthen summary and bullet wording.")
    return dedupe_strings(items)


def _build_validation_notes(
    candidate_profile: CandidateProfile,
    fit_analysis: FitAnalysis,
    agent_result: Optional[AgentWorkflowResult],
) -> list[str]:
    notes = []
    if fit_analysis.missing_hard_skills:
        notes.append(
            "Review whether missing JD skills such as {skills} should be addressed manually with real evidence only.".format(
                skills=", ".join(fit_analysis.missing_hard_skills[:4])
            )
        )
    if not candidate_profile.experience:
        notes.append("Experience sections are thin because the resume input exposed limited structured work history.")
    if agent_result and not agent_result.review.approved:
        notes.extend(agent_result.review.revision_requests[:2])
    if not notes:
        notes.append("Generated content stays grounded in the current resume profile and should still be reviewed before submission.")
    return dedupe_strings(notes)


def _build_resume_markdown(
    header: ResumeHeader,
    job_description: JobDescription,
    professional_summary: str,
    highlighted_skills: list[str],
    experience_entries: list[ResumeExperienceEntry],
    education_entries: list[EducationEntry],
    certifications: list[str],
    change_log: list[str],
    validation_notes: list[str],
    theme: str,
) -> str:
    theme_config = RESUME_THEMES.get(theme, RESUME_THEMES["classic_ats"])
    subtitle_parts = [part for part in [job_description.title, header.location] if part]
    header_block = ["# " + (header.full_name or "Candidate")] 
    if subtitle_parts:
        header_block.append("**" + " | ".join(subtitle_parts) + "**")
    if header.contact_lines:
        header_block.append(_safe_join(header.contact_lines, fallback=""))

    experience_blocks = []
    for entry in experience_entries:
        role_line = entry.title
        if entry.organization:
            role_line += " - " + entry.organization
        date_parts = [part for part in [entry.start, entry.end] if part]
        if date_parts:
            role_line += " ({dates})".format(dates=" - ".join(date_parts))
        experience_blocks.append(
            "\n".join(
                [
                    "### " + role_line,
                    _render_markdown_list(entry.bullets, "No grounded bullets available."),
                ]
            )
        )

    education_lines = []
    for education in education_entries[:4]:
        line = education.institution or "Education"
        details = [part for part in [education.degree, education.field_of_study] if part]
        if details:
            line += " - " + ", ".join(details)
        date_parts = [part for part in [education.start, education.end] if part]
        if date_parts:
            line += " ({dates})".format(dates=" - ".join(date_parts))
        education_lines.append(line)

    return "\n\n".join(
        [
            "\n".join(part for part in header_block if part),
            theme_config["tagline"],
            "## Professional Summary\n\n" + (professional_summary or "No professional summary generated."),
            "## Core Skills\n\n" + _render_markdown_list(highlighted_skills, "No highlighted skills generated."),
            "## Professional Experience\n\n" + ("\n\n".join(experience_blocks) if experience_blocks else "No structured experience entries were inferred from the current resume."),
            "## Education\n\n" + _render_markdown_list(education_lines, "No education entries available."),
            "## Certifications\n\n" + _render_markdown_list(certifications, "No certifications listed."),
            "## Change Summary\n\n" + _render_markdown_list(change_log, "No change summary available."),
            "## Validation Notes\n\n" + _render_markdown_list(validation_notes, "No validation notes available."),
        ]
    ).strip()


def build_tailored_resume_artifact(
    candidate_profile: CandidateProfile,
    job_description: JobDescription,
    fit_analysis: FitAnalysis,
    tailored_draft: TailoredResumeDraft,
    agent_result: Optional[AgentWorkflowResult] = None,
    theme: str = "classic_ats",
) -> TailoredResumeArtifact:
    if agent_result and agent_result.resume_generation and agent_result.resume_generation.template_hint:
        theme = agent_result.resume_generation.template_hint
    professional_summary = (
        agent_result.resume_generation.professional_summary
        if agent_result and agent_result.resume_generation and agent_result.resume_generation.professional_summary
        else agent_result.tailoring.professional_summary
        if agent_result and agent_result.tailoring.professional_summary
        else tailored_draft.professional_summary
    )
    highlighted_skills = dedupe_strings(
        (agent_result.resume_generation.highlighted_skills if agent_result and agent_result.resume_generation else [])
        + (agent_result.tailoring.highlighted_skills if agent_result else [])
        + tailored_draft.highlighted_skills
        + fit_analysis.matched_hard_skills,
    )[:8]
    header = _build_header(candidate_profile)
    experience_entries = _build_experience_entries(candidate_profile, tailored_draft, agent_result)
    change_log = _build_change_log(job_description, tailored_draft, agent_result, theme)
    validation_notes = _build_validation_notes(candidate_profile, fit_analysis, agent_result)
    title = "{name} - {role} Tailored Resume".format(
        name=candidate_profile.full_name or "Candidate",
        role=job_description.title or "Target Role",
    )
    filename_stem = _slugify(
        "{candidate}-{role}-tailored-resume".format(
            candidate=candidate_profile.full_name or "candidate",
            role=job_description.title or "target-role",
        )
    )
    markdown = _build_resume_markdown(
        header,
        job_description,
        professional_summary,
        highlighted_skills,
        experience_entries,
        candidate_profile.education,
        candidate_profile.certifications,
        change_log,
        validation_notes,
        theme,
    )
    summary = "Tailored resume draft for {role} using the {theme} template.".format(
        role=job_description.title or "the target role",
        theme=RESUME_THEMES.get(theme, RESUME_THEMES["classic_ats"])["label"],
    )
    return TailoredResumeArtifact(
        title=title,
        filename_stem=filename_stem,
        summary=summary,
        markdown=markdown,
        plain_text=_markdown_to_text(markdown),
        theme=theme,
        header=header,
        target_role=job_description.title,
        professional_summary=professional_summary,
        highlighted_skills=highlighted_skills,
        experience_entries=experience_entries,
        education_entries=list(candidate_profile.education),
        certifications=list(candidate_profile.certifications),
        change_log=change_log,
        validation_notes=validation_notes,
    )