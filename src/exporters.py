import html
import hashlib
import logging
import os
import re
import sys
import warnings
import zipfile
from io import BytesIO

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode

from src.errors import ExportError
from src.logging_utils import get_logger, log_event
from src.schemas import ApplicationReport, CoverLetterArtifact, ProjectEntry, TailoredResumeArtifact


_MARKDOWN = MarkdownIt("commonmark", {"html": False})
LOGGER = get_logger(__name__)
_WEASYPRINT_DLL_HANDLE = None


def _configure_weasyprint_windows_runtime():
    global _WEASYPRINT_DLL_HANDLE

    if sys.platform != "win32" or _WEASYPRINT_DLL_HANDLE is not None:
        return

    candidate_dirs = []
    env_dirs = os.getenv("WEASYPRINT_DLL_DIRECTORIES", "")
    if env_dirs:
        candidate_dirs.extend(path for path in env_dirs.split(os.pathsep) if path)
    candidate_dirs.append(r"C:\msys64\mingw64\bin")

    for dll_dir in candidate_dirs:
        if not os.path.isdir(dll_dir):
            continue
        try:
            os.environ["WEASYPRINT_DLL_DIRECTORIES"] = dll_dir
            _WEASYPRINT_DLL_HANDLE = os.add_dll_directory(dll_dir)
            log_event(
                LOGGER,
                logging.INFO,
                "weasyprint_windows_runtime_configured",
                "Configured the WeasyPrint Windows DLL search path.",
                dll_directory=dll_dir,
            )
            return
        except (AttributeError, FileNotFoundError, OSError):
            continue


def export_markdown_bytes(report: ApplicationReport | CoverLetterArtifact | TailoredResumeArtifact) -> bytes:
    return report.markdown.encode("utf-8")


def export_text_bytes(report: ApplicationReport | CoverLetterArtifact | TailoredResumeArtifact) -> bytes:
    return report.plain_text.encode("utf-8")


def export_pdf_bytes(report: ApplicationReport | CoverLetterArtifact | TailoredResumeArtifact) -> bytes:
    try:
        theme = getattr(report, "theme", None)
        document_kind = (
            "tailored_resume"
            if isinstance(report, TailoredResumeArtifact)
            else "cover_letter"
            if isinstance(report, CoverLetterArtifact)
            else "report"
        )
        artifact = report if isinstance(report, TailoredResumeArtifact) else None
        return generate_pdf(
            report.markdown,
            title=report.title,
            theme=theme,
            document_kind=document_kind,
            artifact=artifact,
        ).getvalue()
    except ExportError as error:
        log_event(
            LOGGER,
            logging.ERROR,
            "pdf_export_failed",
            "PDF export failed.",
            report_title=report.title,
            filename_stem=report.filename_stem,
            error_type=type(error).__name__,
            details=error.details,
        )
        raise


def build_resume_preview_html(artifact: TailoredResumeArtifact) -> str:
    return _build_resume_html(
        artifact.markdown,
        title=artifact.title,
        theme=artifact.theme,
        artifact=artifact,
    )


def build_report_preview_html(report: ApplicationReport) -> str:
    return _build_report_html(report.markdown, title=report.title)


def build_cover_letter_preview_html(artifact: CoverLetterArtifact) -> str:
    return _build_cover_letter_html(
        artifact.markdown,
        title=artifact.title,
        theme=getattr(artifact, "theme", "classic_ats"),
    )


def export_zip_bundle_bytes(file_map: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename, payload in file_map.items():
            archive.writestr(filename, payload)
    return buffer.getvalue()


def _paragraph_text(text):
    return html.escape(text or "")


def _style_report_intro_block(body_html: str) -> str:
    match = re.match(
        r"\s*(<h1>.*?</h1>)(\s*<p>.*?</p>)?",
        body_html or "",
        flags=re.DOTALL,
    )
    if not match:
        return body_html

    intro_html = "".join(part for part in match.groups() if part)
    wrapped_intro = '<section class="report-intro">{content}</section>'.format(content=intro_html)
    return (body_html or "").replace(match.group(0), wrapped_intro, 1)


def _split_application_report_title(title: str) -> tuple[str, str]:
    normalized_title = str(title or "AI Job Application Package").strip() or "AI Job Application Package"
    if " - " in normalized_title and normalized_title.lower().endswith(" application package"):
        name, role_with_suffix = normalized_title.split(" - ", 1)
        role = role_with_suffix[: -len(" Application Package")].strip()
        return name.strip() or normalized_title, role or ""
    return normalized_title, ""


def _style_report_intro_block_with_header(body_html: str, title: str) -> str:
    match = re.match(
        r"\s*(<h1>.*?</h1>)(\s*<p>.*?</p>)?",
        body_html or "",
        flags=re.DOTALL,
    )
    if not match:
        return body_html

    header_title, header_subtitle = _split_application_report_title(title)
    intro_parts = ['<h1>{title}</h1>'.format(title=html.escape(header_title))]
    if header_subtitle:
        intro_parts.append(
            '<p class="report-intro-role">{subtitle}</p>'.format(subtitle=html.escape(header_subtitle))
        )
    if match.group(2):
        intro_parts.append(match.group(2).strip())
    wrapped_intro = '<section class="report-intro">{content}</section>'.format(content="".join(intro_parts))
    return (body_html or "").replace(match.group(0), wrapped_intro, 1)


def _style_cover_letter_body(body_html: str) -> str:
    styled_body = re.sub(
        r"\s*<h1>.*?</h1>",
        "",
        body_html or "",
        count=1,
        flags=re.DOTALL,
    ).strip()
    greeting_match = re.search(r"<p>.*?</p>", styled_body, flags=re.DOTALL)
    if greeting_match:
        greeting_html = '<div class="cover-letter-greeting-break"></div>{content}'.format(
            content=greeting_match.group(0)
        )
        styled_body = styled_body.replace(greeting_match.group(0), greeting_html, 1)
    signoff_match = re.search(r"<p>([^<]+),\s*([^<]+)</p>\s*$", styled_body, flags=re.DOTALL)
    if signoff_match:
        signoff_html = '<div class="cover-letter-signoff"><p>{line_one},</p><p>{line_two}</p></div>'.format(
            line_one=html.escape(signoff_match.group(1).strip()),
            line_two=html.escape(signoff_match.group(2).strip()),
        )
        styled_body = re.sub(r"<p>([^<]+),\s*([^<]+)</p>\s*$", signoff_html, styled_body, count=1, flags=re.DOTALL)
    return styled_body


def _split_cover_letter_title(title: str) -> tuple[str, str]:
    normalized_title = str(title or "Cover Letter").strip() or "Cover Letter"
    if " - " in normalized_title and normalized_title.lower().endswith(" cover letter"):
        name, role_with_suffix = normalized_title.split(" - ", 1)
        role = role_with_suffix[: -len(" Cover Letter")].strip()
        return name.strip() or normalized_title, role or "Cover Letter"
    if normalized_title.lower().endswith(" cover letter"):
        headline = normalized_title[: -len(" Cover Letter")].strip()
        return headline or normalized_title, "Cover Letter"
    return normalized_title, ""


_COVER_LETTER_THEME_PALETTES = {
    # Default — warm cream paper + brown accents, matched to the resume
    # classic theme so the two read as a single set of stationery.
    "classic_ats": {
        "ink": "#221912",
        "muted": "#6b5648",
        "accent": "#8f6845",
        "line": "#d7c2af",
        "paper": "#fffdf9",
        "surface": "#fffdfa",
        "strong_color": "#17100b",
        "header_border_width": "3px",
    },
    # Conservative B&W — pure black ink on white paper. Body stays
    # Georgia (serif still feels right for letter prose) but every
    # accent collapses to grayscale.
    "professional_neutral": {
        "ink": "#0a0a0a",
        "muted": "#555555",
        "accent": "#0a0a0a",
        "line": "#bfbfbf",
        "paper": "#ffffff",
        "surface": "#ffffff",
        "strong_color": "#0a0a0a",
        "header_border_width": "2px",
    },
}


def _resolve_cover_letter_palette(theme: str | None) -> dict:
    return _COVER_LETTER_THEME_PALETTES.get(
        theme or "classic_ats", _COVER_LETTER_THEME_PALETTES["classic_ats"]
    )


def _build_cover_letter_html(text, title="Cover Letter", theme="classic_ats"):
    safe_title = html.escape(title or "Cover Letter")
    header_title, header_subtitle = _split_cover_letter_title(title)
    body_html = _style_cover_letter_body(_MARKDOWN.render(text or ""))
    palette = _resolve_cover_letter_palette(theme)

    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <title>{title}</title>
    <style>
        /* Theme-keyed palette: classic_ats keeps the warm-brown letter
           feel; professional_neutral drops to pure black/white/gray for
           conservative recipients while keeping the same Georgia letter
           prose. */
        :root {{
            --ink: {ink};
            --muted: {muted};
            --accent: {accent};
            --line: {line};
            --paper: {paper};
            --surface: {surface};
        }}

        @page {{ size: A4; margin: 0; }}

        * {{ box-sizing: border-box; }}

        body {{
            margin: 0;
            font-family: Georgia, "Times New Roman", serif;
            color: var(--ink);
            background: var(--paper);
            line-height: 1.72;
            font-size: 11.4pt;
        }}

        .cover-letter-shell {{
            width: 100%;
            min-height: 100vh;
            background: var(--surface);
            padding: 18mm 16mm 18mm;
        }}

        .cover-letter-header {{ margin: 0 0 18px; }}

        .cover-letter-title {{
            margin: 0;
            font-size: 17.5pt;
            font-weight: 700;
            letter-spacing: 0.02em;
            color: var(--ink);
        }}

        .cover-letter-role {{
            margin: 4px 0 0;
            font-size: 10.8pt;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: var(--muted);
        }}

        .cover-letter-greeting-break {{
            width: auto;
            border-top: {header_border_width} solid var(--accent);
            margin: 8px -16mm 14px;
        }}

        .cover-letter-signoff p {{ margin: 0 0 6px; }}
        .cover-letter-signoff p:last-child {{ margin-bottom: 0; }}

        p {{ margin: 0 0 12px; }}
        strong {{ color: {strong_color}; }}
        em {{ color: var(--muted); }}
        ul, ol {{ margin: 0 0 12px 1.25rem; padding: 0; }}
        li {{ margin: 0 0 6px; }}
    </style>
</head>
<body>
    <main class="cover-letter-shell">
        <header class="cover-letter-header">
            <h1 class="cover-letter-title">{header_title}</h1>
            {header_subtitle}
        </header>
        {body}
    </main>
</body>
</html>
""".format(
        title=safe_title,
        header_title=html.escape(header_title),
        header_subtitle=(
            '<p class="cover-letter-role">{subtitle}</p>'.format(
                subtitle=html.escape(header_subtitle)
            )
            if header_subtitle
            else ""
        ),
        body=body_html,
        **palette,
    )


def _build_report_html(text, title="AI Job Application Package"):
    body_html = _MARKDOWN.render(text or "")
    body_html = _style_report_intro_block_with_header(body_html, title)
    safe_title = html.escape(title or "AI Job Application Package")

    return """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{title}</title>
  <style>
    :root {{
      --ink: #142033;
      --muted: #5b6b83;
            --accent: #1b2a46;
        --subsection-accent: #4f78b5;
      --accent-strong: #2563eb;
      --line: #d9e0e7;
            --section-line: #1b2a46;
            --paper: #ffffff;
            --surface: #ffffff;
      --surface-soft: #eef4ff;
    }}

    @page {{
      size: A4;
            margin: 0;
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      font-family: "Segoe UI", Arial, sans-serif;
      color: var(--ink);
            background: var(--paper);
      line-height: 1.62;
      font-size: 10.6pt;
    }}

    .report-shell {{
            width: 100%;
            min-height: 100vh;
            background: var(--surface);
            padding: 16mm 14mm 18mm;
    }}

        .report-intro {{
            background: linear-gradient(180deg, #070a10 0%, #0b1220 100%);
            border: 0;
            border-bottom: 1px solid #1b2a46;
            border-radius: 0;
            padding: 16mm 14mm 12mm;
            margin: -16mm -14mm 18px;
        }}

        .report-intro h1 {{
            color: #e8eef8;
            font-size: 17.5pt;
            margin-bottom: 10px;
        }}

        .report-intro-role {{
            margin: -2px 0 10px;
            font-size: 10.8pt;
            letter-spacing: 0.08em;
            text-transform: uppercase;
            color: #cfdced;
        }}

        .report-intro p {{
            color: #cfdced;
        }}

        .report-intro p:last-child {{
            margin-bottom: 0;
        }}

    .report-shell::before {{
            content: none;
    }}

    h1, h2, h3 {{
      color: var(--ink);
      margin-top: 0;
      break-after: avoid;
      page-break-after: avoid;
    }}

    h1 {{
      font-size: 24pt;
      line-height: 1.15;
      margin-bottom: 16px;
      letter-spacing: -0.02em;
    }}

    h2 {{
      font-size: 15pt;
            color: var(--accent);
      margin-top: 22px;
      margin-bottom: 10px;
            padding: 0 14mm 9px;
            margin-left: -14mm;
            margin-right: -14mm;
            border-bottom: 2.5px solid var(--section-line);
    }}

    h3 {{
      font-size: 11.8pt;
      margin-top: 14px;
      margin-bottom: 6px;
            color: var(--subsection-accent);
    }}

    p {{
      margin: 0 0 10px;
    }}

    ul, ol {{
      margin: 0 0 12px 1.3rem;
      padding: 0;
    }}

    li {{
      margin: 0 0 6px;
      break-inside: avoid;
    }}

    strong {{
      color: #0f172a;
    }}

    blockquote {{
      margin: 0 0 12px;
      padding: 8px 12px;
      border-left: 4px solid #93c5fd;
      background: var(--surface-soft);
      border-radius: 0 10px 10px 0;
      color: var(--muted);
    }}

    code {{
      font-family: Consolas, monospace;
      font-size: 0.95em;
      background: #f3f6fb;
      border: 1px solid #dce5f0;
      border-radius: 4px;
      padding: 0.08rem 0.3rem;
    }}

    pre {{
      background: #f3f6fb;
      border: 1px solid #dce5f0;
      border-radius: 10px;
      padding: 12px 14px;
      white-space: pre-wrap;
            overflow-wrap: anywhere;
      overflow: hidden;
      margin: 0 0 12px;
      font-family: Consolas, monospace;
      font-size: 9.4pt;
      line-height: 1.5;
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
      margin: 0 0 12px;
      font-size: 10pt;
    }}

    th, td {{
      border: 1px solid var(--line);
      padding: 8px 9px;
      text-align: left;
      vertical-align: top;
    }}

    th {{
      background: #f8fbff;
      font-weight: 700;
    }}

    hr {{
      border: 0;
            border-top: 2.5px solid var(--section-line);
      margin: 16px 0;
    }}
  </style>
</head>
<body>
  <main class="report-shell">
    {body}
  </main>
</body>
</html>
""".format(title=safe_title, body=body_html)


def _build_resume_section_list(items, empty_state, ordered=False, class_name=""):
    values = [html.escape(str(item or "").strip()) for item in items if str(item or "").strip()]
    if not values:
        return '<p class="resume-empty">{text}</p>'.format(text=html.escape(empty_state))

    tag_name = "ol" if ordered else "ul"
    class_attr = ' class="{name}"'.format(name=class_name) if class_name else ""
    content = "".join("<li>{item}</li>".format(item=value) for value in values)
    return "<{tag}{class_attr}>{content}</{tag}>".format(
        tag=tag_name,
        class_attr=class_attr,
        content=content,
    )


def _build_resume_experience_html(experience_entries):
    if not experience_entries:
        return '<p class="resume-empty">No structured experience entries were available.</p>'

    cards = []
    for entry in experience_entries:
        title = html.escape(entry.title or "Relevant Experience")
        organization = html.escape(entry.organization or "")
        location = html.escape(entry.location or "")
        date_parts = [part for part in [entry.start, entry.end] if part]
        date_text = html.escape(" - ".join(date_parts)) if date_parts else ""
        meta_parts = [part for part in [organization, location] if part]
        bullets_html = _build_resume_section_list(
            entry.bullets,
            "No grounded bullet points were generated for this role.",
            class_name="resume-bullet-list",
        )
        cards.append(
            """
            <article class="resume-experience-card">
                <div class="resume-role-row">
                    <div>
                        <h3>{title}</h3>
                        {meta}
                    </div>
                    {dates}
                </div>
                {bullets}
            </article>
            """.format(
                title=title,
                # Each meta_part was already individually escaped above
                # (organization, location). Joining and re-escaping
                # would double-escape — '<acme>' becomes
                # '&amp;lt;acme&amp;gt;' on the page. Keep the join
                # plain.
                meta=(
                    '<p class="resume-role-meta">{meta}</p>'.format(meta=" | ".join(meta_parts))
                    if meta_parts
                    else ""
                ),
                dates=(
                    '<p class="resume-role-dates">{dates}</p>'.format(dates=date_text)
                    if date_text
                    else ""
                ),
                bullets=bullets_html,
            )
        )
    return "".join(cards)


def _build_resume_projects_html(project_entries: list[ProjectEntry]) -> str:
    if not project_entries:
        return ""
    cards: list[str] = []
    for project in project_entries:
        name = html.escape(project.name or "Project")
        date_parts = [part for part in [project.start, project.end] if part]
        date_text = html.escape(" - ".join(date_parts)) if date_parts else ""
        description = html.escape(project.description or "")
        bullets_html = ""
        if project.bullets:
            bullets_html = _build_resume_section_list(
                project.bullets,
                "",
                class_name="resume-bullet-list",
            )
        meta_parts: list[str] = []
        if project.technologies:
            meta_parts.append(
                "Tech: " + html.escape(", ".join(project.technologies))
            )
        if project.link:
            meta_parts.append("Link: " + html.escape(project.link))
        meta_html = (
            '<p class="resume-role-meta">{meta}</p>'.format(meta=" | ".join(meta_parts))
            if meta_parts
            else ""
        )
        cards.append(
            """
            <article class="resume-project-card">
                <div class="resume-role-row">
                    <div>
                        <h3>{name}</h3>
                        {description}
                    </div>
                    {dates}
                </div>
                {bullets}
                {meta}
            </article>
            """.format(
                name=name,
                description=(
                    '<p class="resume-role-meta">{description}</p>'.format(description=description)
                    if description
                    else ""
                ),
                dates=(
                    '<p class="resume-role-dates">{dates}</p>'.format(dates=date_text)
                    if date_text
                    else ""
                ),
                bullets=bullets_html,
                meta=meta_html,
            )
        )
    return "".join(cards)


def _build_resume_education_html(education_entries):
    if not education_entries:
        return '<p class="resume-empty">No education entries were available.</p>'

    blocks = []
    for entry in education_entries:
        institution = html.escape(entry.institution or "Education")
        degree_parts = [part for part in [entry.degree, entry.field_of_study] if part]
        date_parts = [part for part in [entry.start, entry.end] if part]
        blocks.append(
            """
            <article class="resume-education-card">
                <h3>{institution}</h3>
                {degree}
                {dates}
            </article>
            """.format(
                institution=institution,
                degree=(
                    '<p class="resume-education-meta">{degree}</p>'.format(
                        degree=html.escape(" - ".join(degree_parts))
                    )
                    if degree_parts
                    else ""
                ),
                dates=(
                    '<p class="resume-education-dates">{dates}</p>'.format(
                        dates=html.escape(" - ".join(date_parts))
                    )
                    if date_parts
                    else ""
                ),
            )
        )
    return "".join(blocks)


def _build_resume_contact_inline_html(contact_lines):
    values = [html.escape(str(item or "").strip()) for item in contact_lines if str(item or "").strip()]
    if not values:
        return ""
    return '<p class="resume-contact-inline">{items}</p>'.format(items=" | ".join(values))


def _build_resume_skills_inline_html(skills):
    values = [html.escape(str(item or "").strip()) for item in skills if str(item or "").strip()]
    if not values:
        return '<p class="resume-empty">No highlighted skills were generated.</p>'
    return '<p class="resume-skill-inline">{items}</p>'.format(items=" | ".join(values))


def _build_structured_resume_body_classic(artifact: TailoredResumeArtifact):
    # Summary, Core Skills, Education always render — Summary because
    # the workflow always generates one (placeholder surfaces a
    # failure), Skills and Education because both are user-supplied
    # content the resume requires.
    #
    # Experience, Projects, Publications, Certifications drop entirely
    # when empty: students / early-career candidates may legitimately
    # have any combination of these missing, and a placeholder reads as
    # awkward filler rather than as a useful diagnostic. Internships
    # are modelled as regular Experience entries (no separate
    # Internships section).
    name = html.escape(artifact.header.full_name or artifact.title or "Candidate")
    contact_values = []
    if artifact.header.location:
        contact_values.append(artifact.header.location)
    contact_values.extend(item for item in artifact.header.contact_lines if str(item or "").strip())
    contact_html = _build_resume_contact_inline_html(contact_values)
    skills_html = _build_resume_skills_inline_html(artifact.highlighted_skills)

    experience_entries = list(artifact.experience_entries or [])
    experience_section = ""
    if experience_entries:
        experience_section = """
    <section class="resume-classic-section">
        <h2>Experience</h2>
        {experience}
    </section>
        """.format(experience=_build_resume_experience_html(experience_entries))

    project_entries = list(artifact.project_entries or [])
    projects_section = ""
    if project_entries:
        projects_section = """
    <section class="resume-classic-section">
        <h2>Projects</h2>
        {projects}
    </section>
        """.format(projects=_build_resume_projects_html(project_entries))

    publication_entries = [item for item in (artifact.publication_entries or []) if str(item or "").strip()]
    publications_section = ""
    if publication_entries:
        publications_section = """
    <section class="resume-classic-section">
        <h2>Publications</h2>
        {publications}
    </section>
        """.format(
            publications=_build_resume_section_list(
                publication_entries,
                "",
                class_name="resume-plain-list",
            )
        )

    certifications = [item for item in artifact.certifications if str(item or "").strip()]
    certifications_section = ""
    if certifications:
        certifications_section = """
    <section class="resume-classic-section">
        <h2>Certifications</h2>
        {certifications}
    </section>
        """.format(
            certifications=_build_resume_section_list(
                certifications,
                "",
                class_name="resume-plain-list",
            )
        )

    return """
    <section class="resume-classic-header">
        <h1>{name}</h1>
        {contact_block}
    </section>
    <section class="resume-classic-section resume-classic-section--plain-head">
        <h2>Summary</h2>
        <p class="resume-summary">{summary}</p>
    </section>
    <section class="resume-classic-section resume-classic-section--plain-head">
        <h2>Core Skills</h2>
        {skills}
    </section>
    {experience_section}
    {projects_section}
    <section class="resume-classic-section">
        <h2>Education</h2>
        {education}
    </section>
    {publications_section}
    {certifications_section}
    """.format(
        name=name,
        contact_block=contact_html,
        summary=html.escape(artifact.professional_summary or "No professional summary generated."),
        skills=skills_html,
        experience_section=experience_section,
        projects_section=projects_section,
        education=_build_resume_education_html(artifact.education_entries),
        publications_section=publications_section,
        certifications_section=certifications_section,
    )


_RESUME_THEME_PALETTES = {
    # Default — warm cream paper + brown accents. Editorial pairing:
    # Arial body for scannability + Georgia for the prose-y bits
    # (summary, bullets) to harmonise with the cover letter.
    "classic_ats": {
        "ink": "#221912",
        "muted": "#6b5648",
        "accent": "#8f6845",
        "accent_soft": "rgba(143, 104, 69, 0.10)",
        "line": "#d7c2af",
        "paper": "#fffdf9",
        "surface": "#fffdfa",
        "body_font_family": "Arial, Helvetica, sans-serif",
        "h1_font_family": 'Georgia, "Times New Roman", serif',
        "prose_font_family": 'Georgia, "Times New Roman", serif',
        "prose_line_height": "1.55",
        "header_border_width": "3px",
        "code_bg": "rgba(143, 104, 69, 0.10)",
    },
    # Conservative B&W — pure ATS-template look. Body uses Georgia so
    # the resume reads as the same family as the cover letter (which
    # is also Georgia in both themes); Arial felt cold and template-y
    # at the small sizes this layout uses.
    "professional_neutral": {
        "ink": "#0a0a0a",
        "muted": "#555555",
        "accent": "#0a0a0a",
        "accent_soft": "rgba(0, 0, 0, 0.04)",
        "line": "#bfbfbf",
        "paper": "#ffffff",
        "surface": "#ffffff",
        "body_font_family": 'Georgia, "Times New Roman", serif',
        "h1_font_family": 'Georgia, "Times New Roman", serif',
        "prose_font_family": 'Georgia, "Times New Roman", serif',
        "prose_line_height": "1.55",
        "header_border_width": "2px",
        "code_bg": "rgba(0, 0, 0, 0.04)",
    },
}


def _resolve_resume_palette(theme: str | None) -> dict:
    return _RESUME_THEME_PALETTES.get(
        theme or "classic_ats", _RESUME_THEME_PALETTES["classic_ats"]
    )


def _build_resume_html(text, title="Tailored Resume", theme="classic_ats", artifact: TailoredResumeArtifact | None = None):
    body_html = _MARKDOWN.render(text or "")
    if artifact is not None:
        body_html = _build_structured_resume_body_classic(artifact)
    safe_title = html.escape(title or "Tailored Resume")
    palette = _resolve_resume_palette(theme)

    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <title>{title}</title>
    <style>
        @page {{ size: A4; margin: 0; }}
        /* Theme-keyed palette: classic_ats ships warm-brown + Georgia
           prose so the resume reads as a set with the cover letter;
           professional_neutral collapses to pure black/white/gray with
           all-Arial body for conservative recruiters / B&W printing. */
        :root {{
            --ink: {ink};
            --muted: {muted};
            --accent: {accent};
            --accent-soft: {accent_soft};
            --line: {line};
            --paper: {paper};
            --surface: {surface};
        }}
        * {{ box-sizing: border-box; }}
        html, body {{ margin: 0; padding: 0; }}
        body {{ font-family: {body_font_family}; color: var(--ink); background: var(--paper); font-size: 10.5pt; line-height: 1.5; }}
        /* Editorial pairing: in classic_ats the prose-y parts (summary,
           bullets) shift to Georgia so the resume harmonizes with the
           cover letter; professional_neutral keeps Arial throughout. */
        .resume-summary, .resume-bullet-list li {{ font-family: {prose_font_family}; line-height: {prose_line_height}; }}
        /* min-height keeps short resumes filling a single A4 page;
           overflow-x: hidden prevents the negative-margin h2 trick from
           leaking past the page edge horizontally while letting
           WeasyPrint paginate vertically when the resume runs long. */
        .resume-shell {{ position: relative; min-height: 297mm; background: var(--surface); padding: 13mm 15mm 13mm; overflow-x: hidden; }}
        .resume-experience-card, .resume-education-card, .resume-project-card {{ page-break-inside: avoid; break-inside: avoid; }}
        h2, h3 {{ page-break-after: avoid; break-after: avoid; }}
        .resume-shell::before {{ content: none; }}
        .resume-shell::after {{ content: none; }}
        /* Name is the resume's title — bold, mixed-case, light tracking.
           Font family is theme-keyed so neutral stays all-Arial. */
        h1 {{ font-family: {h1_font_family}; font-size: 22pt; font-weight: 700; margin: 0 0 4px; letter-spacing: -0.005em; color: var(--ink); text-transform: none; }}
        h2 {{ font-size: 10pt; margin: 0 -15mm 6px; text-transform: uppercase; letter-spacing: 0.18em; color: var(--accent); padding: 0 15mm 3px; border-bottom: 2px solid var(--line); }}
        h3 {{ font-size: 10.5pt; margin: 10px 0 4px; color: var(--accent); }}
        p {{ margin: 0 0 6px; }}
        ul {{ margin: 0 0 8px 1rem; padding: 0; }}
        li {{ margin: 0 0 3px; }}
        strong {{ color: var(--ink); }}
        em {{ color: var(--muted); }}
        code {{ background: {code_bg}; border: 1px solid var(--line); border-radius: 4px; padding: 0.08rem 0.28rem; }}
        hr {{ border: 0; border-top: 1px solid var(--line); margin: 14px 0; }}
        blockquote {{ margin: 0 0 10px; padding: 8px 12px; border-left: 4px solid var(--accent); background: var(--accent-soft); color: var(--muted); }}
        .resume-classic-header {{ position: relative; z-index: 1; padding: 0 15mm 10px; margin: 0 -15mm; border-bottom: {header_border_width} solid var(--accent); }}
        .resume-classic-role {{ font-size: 10.2pt; color: var(--muted); text-transform: uppercase; letter-spacing: 0.12em; margin-bottom: 4px; }}
        .resume-contact-inline {{ color: var(--muted); font-size: 9.6pt; line-height: 1.55; max-width: 88%; }}
        .resume-skill-inline {{ color: var(--ink); font-size: 9.8pt; line-height: 1.7; }}
        .resume-classic-section {{ position: relative; z-index: 1; margin-top: 12px; }}
        .resume-classic-section--plain-head h2 {{ border-bottom: 0; padding-bottom: 0; }}
        .resume-experience-card, .resume-project-card {{ background: transparent; border: 0; border-radius: 0; padding: 0; }}
        .resume-education-card {{ background: transparent; border: 0; border-radius: 0; padding: 0; }}
        .resume-role-row {{ display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }}
        .resume-role-row h3, .resume-education-card h3 {{ margin: 0 0 4px; }}
        .resume-role-meta, .resume-role-dates, .resume-education-meta, .resume-education-dates {{ margin: 0; color: var(--muted); font-size: 9.5pt; }}
        .resume-bullet-list, .resume-contact-list, .resume-plain-list {{ margin: 0; padding-left: 1rem; }}
        .resume-empty {{ color: var(--muted); font-style: italic; }}
        .resume-experience-card + .resume-experience-card,
        .resume-project-card + .resume-project-card {{ position: relative; margin-top: 10px; padding-top: 10px; }}
        .resume-experience-card + .resume-experience-card::before,
        .resume-project-card + .resume-project-card::before {{ content: ""; position: absolute; top: 0; left: 12px; right: 12px; border-top: 1px solid var(--line); }}
        .resume-education-card + .resume-education-card {{ margin-top: 10px; }}
        @media all and (max-width: 720px) {{ .resume-classic-header {{ padding: 0 15mm 10px; margin: 0 -15mm; }} .resume-contact-inline {{ max-width: 100%; }} .resume-role-row {{ display: block; }} .resume-role-dates {{ margin-top: 6px; }} }}
    </style>
</head>
<body>
    <main class="resume-shell resume-shell--classic">{body}</main>
</body>
</html>
""".format(title=safe_title, body=body_html, **palette)


def _inline_to_markup(inline_node):
    parts = []
    for child in inline_node.children or []:
        if child.type == "text":
            parts.append(_paragraph_text(child.content))
        elif child.type == "softbreak":
            parts.append(" ")
        elif child.type == "hardbreak":
            parts.append("<br/><br/>")
        elif child.type == "strong":
            parts.append("<b>{text}</b>".format(text=_inline_to_markup(child)))
        elif child.type == "em":
            parts.append("<i>{text}</i>".format(text=_inline_to_markup(child)))
        elif child.type == "code_inline":
            parts.append(
                '<font face="Courier">{text}</font>'.format(
                    text=_paragraph_text(child.content)
                )
            )
        elif child.type == "link":
            href = _paragraph_text((child.attrs or {}).get("href", ""))
            label = _inline_to_markup(child)
            if href:
                parts.append('<link href="{href}">{label}</link>'.format(href=href, label=label))
            else:
                parts.append(label)
        else:
            parts.append(_paragraph_text(child.content))
    return "".join(parts)


def _flatten_list_items(list_node, level=0):
    items = []
    for item_index, item_node in enumerate(list_node.children or [], start=1):
        bullet = "{index}.".format(index=item_index) if list_node.type == "ordered_list" else (
            "-" if level == 0 else "*"
        )
        first_paragraph_rendered = False

        for child in item_node.children or []:
            if child.type == "paragraph":
                items.append(
                    {
                        "kind": "list_paragraph",
                        "level": level,
                        "bullet": bullet if not first_paragraph_rendered else "",
                        "text": _inline_to_markup(child.children[0]) if child.children else "",
                        "continued": first_paragraph_rendered,
                    }
                )
                first_paragraph_rendered = True
            elif child.type in {"bullet_list", "ordered_list"}:
                items.extend(_flatten_list_items(child, level=level + 1))
            elif child.type in {"code_block", "fence"}:
                items.append(
                    {
                        "kind": "code_block",
                        "level": level + 1,
                        "text": child.content.rstrip(),
                    }
                )

    return items


def _parse_markdown_blocks(text):
    root = SyntaxTreeNode(_MARKDOWN.parse(text or ""))
    blocks = []

    for node in root.children or []:
        if node.type == "heading":
            level = int(node.tag[1]) if node.tag.startswith("h") else 2
            title = _inline_to_markup(node.children[0]) if node.children else ""
            block_type = "title" if level == 1 else "heading" if level == 2 else "subheading"
            blocks.append((block_type, title))
            continue

        if node.type == "paragraph":
            content = _inline_to_markup(node.children[0]) if node.children else ""
            blocks.append(("paragraph", content))
            continue

        if node.type in {"bullet_list", "ordered_list"}:
            blocks.append(("list", _flatten_list_items(node)))
            continue

        if node.type in {"code_block", "fence"}:
            blocks.append(("code_block", node.content.rstrip()))
            continue

        if node.type == "hr":
            blocks.append(("rule", ""))

    return blocks


def _generate_pdf_with_reportlab(text, title):
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=r"the load_module\(\) method is deprecated and slated for removal in Python 3.12; use exec_module\(\) instead",
            category=DeprecationWarning,
        )
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.platypus import (
            HRFlowable,
            Paragraph,
            Preformatted,
            SimpleDocTemplate,
            Spacer,
        )
        from reportlab.pdfbase import pdfdoc

    def md5_compat(*args, **kwargs):
        kwargs.pop("usedforsecurity", None)
        return hashlib.md5(*args, **kwargs)

    # Older ReportLab builds still call into pdfdoc.md5 with a
    # usedforsecurity kwarg shape that hashlib.md5 does not accept consistently
    # across runtimes, so we normalize it here for the fallback backend.
    pdfdoc.md5 = md5_compat

    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="ReportTitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=23,
            leading=29,
            textColor=colors.HexColor("#0f172a"),
            alignment=TA_LEFT,
            spaceAfter=16,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SectionHeading",
            parent=styles["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=15,
            leading=20,
            textColor=colors.HexColor("#142033"),
            spaceBefore=12,
            spaceAfter=7,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SubHeading",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=16,
            textColor=colors.HexColor("#1d4ed8"),
            spaceBefore=8,
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="BodyCopy",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=10.3,
            leading=15,
            textColor=colors.HexColor("#1f2937"),
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ListCopy",
            parent=styles["BodyText"],
            fontName="Helvetica",
            fontSize=10.1,
            leading=14.6,
            textColor=colors.HexColor("#1f2937"),
            spaceAfter=4,
        )
    )
    styles.add(
        ParagraphStyle(
            name="CodeBlock",
            parent=styles["Code"],
            fontName="Courier",
            fontSize=8.8,
            leading=10.8,
            textColor=colors.HexColor("#1f2937"),
            backColor=colors.HexColor("#f3f6fb"),
            borderColor=colors.HexColor("#dce5f0"),
            borderWidth=0.6,
            borderPadding=8,
            leftIndent=10,
            rightIndent=10,
            spaceBefore=3,
            spaceAfter=8,
        )
    )

    def list_style(level, continued=False):
        text_indent = 22 + (level * 16)
        return ParagraphStyle(
            name="ListLevel{level}{continued}".format(
                level=level,
                continued="Continued" if continued else "Lead",
            ),
            parent=styles["ListCopy"],
            leftIndent=text_indent,
            bulletIndent=text_indent - 12,
            firstLineIndent=0,
            spaceBefore=0 if continued else 1,
        )

    def render_page(canvas, doc):
        canvas.saveState()
        width, height = letter

        canvas.setStrokeColor(colors.HexColor("#1d4ed8"))
        canvas.setLineWidth(2)
        canvas.line(doc.leftMargin, height - 28, width - doc.rightMargin, height - 28)

        canvas.setStrokeColor(colors.HexColor("#bfdbfe"))
        canvas.setLineWidth(1)
        canvas.line(doc.leftMargin, 30, width - doc.rightMargin, 30)

        canvas.setFont("Helvetica", 8.5)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(doc.leftMargin, 18, "Application Copilot")
        canvas.drawRightString(
            width - doc.rightMargin,
            18,
            "Page {page}".format(page=canvas.getPageNumber()),
        )
        canvas.restoreState()

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=44,
        leftMargin=44,
        topMargin=48,
        bottomMargin=42,
        title=title or "AI Job Application Package",
    )

    flowables = []
    blocks = _parse_markdown_blocks(text)

    for index, (block_type, value) in enumerate(blocks):
        if block_type == "title":
            flowables.append(Paragraph(value, styles["ReportTitle"]))
            flowables.append(
                HRFlowable(
                    width="100%",
                    thickness=1.2,
                    color=colors.HexColor("#cbd5e1"),
                    spaceBefore=0,
                    spaceAfter=10,
                )
            )
            continue

        if block_type == "heading":
            flowables.append(Paragraph(value, styles["SectionHeading"]))
            continue

        if block_type == "subheading":
            flowables.append(Paragraph(value, styles["SubHeading"]))
            continue

        if block_type == "paragraph":
            flowables.append(Paragraph(value, styles["BodyCopy"]))
            continue

        if block_type == "list":
            for item in value:
                if item["kind"] == "list_paragraph":
                    style = list_style(item["level"], continued=item["continued"])
                    if item["bullet"]:
                        flowables.append(
                            Paragraph(item["text"], style, bulletText=item["bullet"])
                        )
                    else:
                        flowables.append(Paragraph(item["text"], style))
                elif item["kind"] == "code_block":
                    code_style = ParagraphStyle(
                        name="NestedCodeLevel{level}".format(level=item["level"]),
                        parent=styles["CodeBlock"],
                        leftIndent=22 + (item["level"] * 16),
                        rightIndent=10,
                    )
                    flowables.append(Preformatted(item["text"], code_style))
            flowables.append(Spacer(1, 6))
            continue

        if block_type == "code_block":
            flowables.append(Preformatted(value, styles["CodeBlock"]))
            continue

        if block_type == "rule" and index != len(blocks) - 1:
            flowables.append(
                HRFlowable(
                    width="100%",
                    thickness=0.8,
                    color=colors.HexColor("#d6dde6"),
                    spaceBefore=2,
                    spaceAfter=8,
                )
            )

    doc.build(flowables, onFirstPage=render_page, onLaterPages=render_page)
    buffer.seek(0)
    return buffer


def _build_pdf_html(text, title, theme=None, document_kind="report"):
    return (
        _build_resume_html(text, title=title, theme=theme or "classic_ats")
        if document_kind == "tailored_resume"
        else _build_cover_letter_html(text, title=title, theme=theme or "classic_ats")
        if document_kind == "cover_letter"
        else _build_report_html(text, title=title)
    )


def _generate_pdf_with_weasyprint(text, title, theme=None, document_kind="report", artifact: TailoredResumeArtifact | None = None):
    _configure_weasyprint_windows_runtime()
    from weasyprint import HTML

    html_document = (
        _build_resume_html(text, title=title, theme=theme or "classic_ats", artifact=artifact)
        if document_kind == "tailored_resume"
        else _build_cover_letter_html(text, title=title, theme=theme or "classic_ats")
        if document_kind == "cover_letter"
        else _build_report_html(text, title=title)
    )

    return BytesIO(HTML(string=html_document).write_pdf())


def _generate_pdf_with_reportlab_fallback(text, title, renderer_error=None):
    if renderer_error is not None:
        log_event(
            LOGGER,
            logging.WARNING,
            "pdf_export_weasyprint_failed",
            "WeasyPrint PDF export failed; attempting ReportLab fallback.",
            title=title,
            error_type=type(renderer_error).__name__,
            details=str(renderer_error),
        )

    try:
        return _generate_pdf_with_reportlab(text, title)
    except Exception as error:
        log_event(
            LOGGER,
            logging.ERROR,
            "pdf_export_reportlab_failed",
            "ReportLab PDF export failed after Playwright fallback.",
            title=title,
            error_type=type(error).__name__,
        )
        raise ExportError(
            "PDF export failed. Try downloading the Markdown package instead.",
            details=str(error),
        ) from error


def generate_pdf(text, title="AI Job Application Package", theme=None, document_kind="report", artifact: TailoredResumeArtifact | None = None):
    try:
        return _generate_pdf_with_weasyprint(text, title, theme=theme, document_kind=document_kind, artifact=artifact)
    except Exception as renderer_error:
        return _generate_pdf_with_reportlab_fallback(text, title, renderer_error=renderer_error)
