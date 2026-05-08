import re
from typing import Optional

from src.schemas import (
    AgentWorkflowResult,
    CandidateProfile,
    EducationEntry,
    FitAnalysis,
    JobDescription,
    ProjectEntry,
    ResumeExperienceEntry,
    ResumeHeader,
    TailoredResumeArtifact,
    TailoredResumeDraft,
)
from src.utils import (
    dedupe_strings,
    markdown_to_text,
    render_markdown_list,
    safe_join_strings,
    slugify_text,
)


RESUME_THEMES = {
    "classic_ats": {
        "label": "Standard Resume",
        "tagline": "Single-column, ATS-safe, recruiter-readable structure.",
    },
    "professional_neutral": {
        "label": "Professional Neutral",
        "tagline": "Single-column, ATS-safe, recruiter-readable structure.",
    },
}


def _resolve_resume_theme(theme: str, agent_result: Optional[AgentWorkflowResult]) -> str:
    """Validate the requested theme and fall back to classic_ats if the
    name is unknown. The agent_result hook stays in the signature so a
    future agent can override the theme based on JD signals; for now
    the user picks per-document on the frontend."""
    if theme in RESUME_THEMES:
        return theme
    return "classic_ats"


# Canonical section identifiers used in TailoredResumeArtifact.section_order.
# The exporter renders sections in this order and the resume_builder
# helpers honor the same vocabulary.
CANONICAL_SECTIONS: tuple[str, ...] = (
    "summary",
    "skills",
    "experience",
    "projects",
    "education",
    "publications",
    "certifications",
)


# Display-name -> canonical-name aliases. The LLM typically emits
# display names like "Professional Experience" or "Core Skills"; this
# lets us normalise them before honoring the order. Anything not in
# this map is lowercased and stripped of leading qualifiers
# ('professional', 'core', 'technical', 'selected') as a last-resort
# fallback.
_SECTION_NAME_ALIASES: dict[str, str] = {
    "summary": "summary",
    "professional summary": "summary",
    "executive summary": "summary",
    "objective": "summary",
    "about": "summary",
    "skills": "skills",
    "core skills": "skills",
    "technical skills": "skills",
    "key skills": "skills",
    "experience": "experience",
    "professional experience": "experience",
    "work experience": "experience",
    "leadership experience": "experience",
    "clinical experience": "experience",
    "academic appointments": "experience",
    "projects": "projects",
    "selected projects": "projects",
    "personal projects": "projects",
    "education": "education",
    "academic background": "education",
    "publications": "publications",
    "selected publications": "publications",
    "papers": "publications",
    "certifications": "certifications",
    "licenses": "certifications",
    "licensure & certifications": "certifications",
    "certifications & licenses": "certifications",
}


def _normalize_section_name(name: str) -> Optional[str]:
    """Map a display section name to its canonical id, or None if no
    canonical match exists.

    Tries the alias map first, then a permissive fallback that strips
    common qualifier prefixes ('professional', 'core', 'selected')
    and re-checks the alias map. Returns None on no match so callers
    can decide whether to drop the entry or accept it as-is.
    """
    if not name:
        return None
    normalized = " ".join(str(name).lower().split())
    if normalized in _SECTION_NAME_ALIASES:
        return _SECTION_NAME_ALIASES[normalized]
    # Strip a single leading qualifier and retry (handles 'core skills'
    # -> 'skills' even if the alias map lookup missed for some reason).
    for prefix in ("professional ", "core ", "technical ", "selected ", "key "):
        if normalized.startswith(prefix):
            stripped = normalized[len(prefix):]
            if stripped in _SECTION_NAME_ALIASES:
                return _SECTION_NAME_ALIASES[stripped]
            if stripped in CANONICAL_SECTIONS:
                return stripped
    if normalized in CANONICAL_SECTIONS:
        return normalized
    return None


def compute_section_order(candidate_profile: CandidateProfile) -> list[str]:
    """Pick a canonical section order based on the candidate's profile
    shape.

    Heuristics (intentionally simple — the LLM agent can override
    this when it has more context):

    - 5+ publications -> academic CV path: education + publications high.
      The threshold is deliberately high; senior industry engineers
      often have 2-4 conference talks / blog posts that shouldn't flip
      them onto the academic path.
    - 0 work experience -> student / no-history path: education up,
      projects up, experience after
    - 2+ projects with at least 1 work entry -> career-switcher / proof-
      heavy path: skills + projects up to lead with target-role evidence
    - everything else -> standard professional: experience after summary
      and skills

    The 'summary' section always leads when present. Tail sections
    (publications, certifications) appear at the end when not promoted
    earlier so they render after the primary narrative.
    """
    exp_count = len(candidate_profile.experience or [])
    proj_count = len(candidate_profile.projects or [])
    pub_count = len(candidate_profile.publications or [])

    if pub_count >= 5:
        return [
            "summary",
            "education",
            "publications",
            "experience",
            "skills",
            "projects",
            "certifications",
        ]

    if exp_count == 0:
        return [
            "summary",
            "education",
            "projects",
            "skills",
            "experience",
            "publications",
            "certifications",
        ]

    if proj_count >= 2:
        return [
            "summary",
            "skills",
            "projects",
            "experience",
            "education",
            "publications",
            "certifications",
        ]

    # Standard professional path: experience leads. Modern recruiter-
    # readable resumes (Indeed, LinkedIn, The Muse, Career Karma) all
    # converge on Experience as the primary signal once the candidate
    # has work history; Skills as a keyword-dense band right after.
    return [
        "summary",
        "experience",
        "skills",
        "projects",
        "education",
        "publications",
        "certifications",
    ]


def _resolve_section_order(
    candidate_profile: CandidateProfile,
    agent_result: Optional[AgentWorkflowResult],
) -> list[str]:
    """Pick the section order based on candidate-profile shape.

    The deterministic helper compute_section_order(profile) is
    authoritative because the decision is purely structural — it
    depends on signals (work history count, projects count,
    publications count) the LLM has no extra context for. In
    practice the LLM agent picks 'experience first' for every
    profile shape, which is wrong for students (no experience),
    academics (publications belong up top), and career switchers
    (skills + projects are the proof). So we ignore the agent's
    section_order field and always use the deterministic helper.

    The agent_result parameter stays in the signature so a future
    agent step that DOES have extra signal (e.g. a JD-aware
    reorder agent) can override it. None today.
    """
    return compute_section_order(candidate_profile)
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
    return ResumeHeader(
        full_name=candidate_profile.full_name,
        location=candidate_profile.location,
        contact_lines=dedupe_strings(candidate_profile.contact_lines),
    )


def _build_project_entries(candidate_profile: CandidateProfile) -> list[ProjectEntry]:
    """Pass project entries from the parsed profile through to the
    tailored artifact. Currently the workflow does not re-tailor
    project bullets per JD — the schema and renderer are wired up so
    that capability can be added later without further migrations."""
    cleaned: list[ProjectEntry] = []
    for project in (candidate_profile.projects or [])[:6]:
        bullets = dedupe_strings(
            list(project.bullets or [])
            + (_description_to_bullets(project.description) if project.description and not project.bullets else [])
        )[:4]
        cleaned.append(
            ProjectEntry(
                name=project.name or "Project",
                description=project.description if not bullets else "",
                bullets=bullets,
                technologies=list(project.technologies or [])[:8],
                start=project.start,
                end=project.end,
                link=project.link,
            )
        )
    return cleaned


def _build_publication_entries(candidate_profile: CandidateProfile) -> list[str]:
    return dedupe_strings(
        [str(item or "").strip() for item in candidate_profile.publications if str(item or "").strip()]
    )[:12]


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
    items = [
        "Tailored the resume toward {role}.".format(
            role=job_description.title or tailored_draft.target_role or "the target role"
        ),
        "Used the standard ATS-friendly layout for export.",
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
        unresolved_issues = getattr(agent_result.review, "unresolved_issues", []) or []
        revision_requests = getattr(agent_result.review, "revision_requests", []) or []
        notes.extend((unresolved_issues or revision_requests)[:2])
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
    project_entries: list[ProjectEntry] | None = None,
    publication_entries: list[str] | None = None,
    section_order: list[str] | None = None,
) -> str:
    theme_config = RESUME_THEMES.get(theme, RESUME_THEMES["classic_ats"])
    header_block = ["# " + (header.full_name or "Candidate")]
    personal_details = [part for part in [header.location] + list(header.contact_lines) if part]
    if personal_details:
        header_block.append(safe_join_strings(personal_details, fallback=""))

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
                    render_markdown_list(entry.bullets, "No grounded bullets available."),
                ]
            )
        )

    project_blocks: list[str] = []
    for project in project_entries or []:
        title_line = project.name or "Project"
        date_parts = [part for part in [project.start, project.end] if part]
        if date_parts:
            title_line += " ({dates})".format(dates=" - ".join(date_parts))
        block_lines = ["### " + title_line]
        if project.description:
            block_lines.append(project.description)
        if project.bullets:
            block_lines.append(render_markdown_list(project.bullets, ""))
        if project.technologies:
            block_lines.append("*Tech:* " + ", ".join(project.technologies))
        if project.link:
            block_lines.append("*Link:* " + project.link)
        project_blocks.append("\n".join(part for part in block_lines if part))

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

    # Summary / Core Skills / Education always render even when the
    # underlying data is sparse — Summary because the workflow always
    # generates one (a placeholder there is a useful failure signal),
    # Skills and Education because both are user-supplied content the
    # resume requires. Experience, Projects, Publications, and
    # Certifications drop entirely when empty — students / early-
    # career candidates may have any combination of these, and a
    # placeholder reads worse than the absence.
    cert_values = [item for item in certifications if str(item or "").strip()]
    pub_values = [item for item in (publication_entries or []) if str(item or "").strip()]

    section_blocks: dict[str, str | None] = {
        "summary": "## Professional Summary\n\n" + (professional_summary or "No professional summary generated."),
        "skills": "## Core Skills\n\n" + render_markdown_list(highlighted_skills, "No highlighted skills generated."),
        "experience": (
            "## Professional Experience\n\n" + "\n\n".join(experience_blocks)
            if experience_blocks
            else None
        ),
        "projects": (
            "## Projects\n\n" + "\n\n".join(project_blocks)
            if project_blocks
            else None
        ),
        "education": "## Education\n\n" + render_markdown_list(education_lines, "No education entries available."),
        "publications": (
            "## Publications\n\n" + render_markdown_list(pub_values, "")
            if pub_values
            else None
        ),
        "certifications": (
            "## Certifications\n\n" + render_markdown_list(cert_values, "")
            if cert_values
            else None
        ),
    }

    # Default to the standard professional order when the caller
    # didn't supply one — keeps tests + legacy callers working.
    order = list(section_order) if section_order else [
        "summary",
        "skills",
        "experience",
        "projects",
        "education",
        "publications",
        "certifications",
    ]

    sections: list[str] = [
        "\n".join(part for part in header_block if part),
        theme_config["tagline"],
    ]
    seen: set[str] = set()
    for name in order:
        if name in seen:
            continue
        seen.add(name)
        block = section_blocks.get(name)
        if block:
            sections.append(block)
    # Always trail with Change Summary regardless of order.
    sections.append("## Change Summary\n\n" + render_markdown_list(change_log, "No change summary available."))

    return "\n\n".join(sections).strip()


def build_tailored_resume_artifact(
    candidate_profile: CandidateProfile,
    job_description: JobDescription,
    fit_analysis: FitAnalysis,
    tailored_draft: TailoredResumeDraft,
    agent_result: Optional[AgentWorkflowResult] = None,
    theme: str = "classic_ats",
) -> TailoredResumeArtifact:
    theme = _resolve_resume_theme(theme, agent_result)
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
    project_entries = _build_project_entries(candidate_profile)
    publication_entries = _build_publication_entries(candidate_profile)
    change_log = _build_change_log(job_description, tailored_draft, agent_result, theme)
    validation_notes = _build_validation_notes(candidate_profile, fit_analysis, agent_result)
    section_order = _resolve_section_order(candidate_profile, agent_result)
    title = "{name} - {role} Tailored Resume".format(
        name=candidate_profile.full_name or "Candidate",
        role=job_description.title or "Target Role",
    )
    filename_stem = slugify_text(
        "{candidate}-{role}-tailored-resume".format(
            candidate=candidate_profile.full_name or "candidate",
            role=job_description.title or "target-role",
        ),
        fallback="tailored-resume",
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
        project_entries=project_entries,
        publication_entries=publication_entries,
        section_order=section_order,
    )
    summary = "Tailored resume draft for {role}, ready to review and export.".format(
        role=job_description.title or "the target role",
    )
    return TailoredResumeArtifact(
        title=title,
        filename_stem=filename_stem,
        summary=summary,
        markdown=markdown,
        plain_text=markdown_to_text(markdown, strip_bold=True),
        theme=theme,
        header=header,
        target_role=job_description.title,
        professional_summary=professional_summary,
        highlighted_skills=highlighted_skills,
        experience_entries=experience_entries,
        education_entries=list(candidate_profile.education),
        certifications=list(candidate_profile.certifications),
        project_entries=project_entries,
        publication_entries=publication_entries,
        section_order=section_order,
        change_log=change_log,
        validation_notes=validation_notes,
    )
