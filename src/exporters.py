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
from src.schemas import ApplicationReport, TailoredResumeArtifact


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


def export_markdown_bytes(report: ApplicationReport) -> bytes:
    return report.markdown.encode("utf-8")


def export_text_bytes(report: ApplicationReport) -> bytes:
    return report.plain_text.encode("utf-8")


def export_pdf_bytes(report: ApplicationReport) -> bytes:
    try:
        theme = getattr(report, "theme", None)
        document_kind = "tailored_resume" if isinstance(report, TailoredResumeArtifact) else "report"
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


def export_zip_bundle_bytes(file_map: dict[str, bytes]) -> bytes:
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename, payload in file_map.items():
            archive.writestr(filename, payload)
    return buffer.getvalue()


def _paragraph_text(text):
    return html.escape(text or "")


def _build_report_html(text, title="AI Job Application Package"):
    body_html = _MARKDOWN.render(text or "")
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
      --accent: #1d4ed8;
      --accent-strong: #2563eb;
      --line: #d9e0e7;
      --paper: #f7f9fc;
      --surface: #ffffff;
      --surface-soft: #eef4ff;
    }}

    @page {{
      size: A4;
      margin: 18mm 14mm 18mm 14mm;
    }}

    * {{
      box-sizing: border-box;
    }}

    body {{
      margin: 0;
      font-family: "Segoe UI", Arial, sans-serif;
      color: var(--ink);
      background: linear-gradient(180deg, #eef4ff 0%, #f7f9fc 100%);
      line-height: 1.62;
      font-size: 10.6pt;
    }}

    .report-shell {{
      background: var(--surface);
      border: 1px solid rgba(20, 32, 51, 0.08);
      border-radius: 18px;
      padding: 20px 22px 18px;
    }}

    .report-shell::before {{
      content: "";
      display: block;
      height: 5px;
      width: 100%;
      border-radius: 999px;
      background: linear-gradient(90deg, #1d4ed8 0%, #2563eb 55%, #60a5fa 100%);
      margin-bottom: 18px;
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
      margin-top: 22px;
      margin-bottom: 10px;
      padding-bottom: 8px;
      border-bottom: 1px solid var(--line);
    }}

    h3 {{
      font-size: 11.8pt;
      margin-top: 14px;
      margin-bottom: 6px;
      color: var(--accent);
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
      border-top: 1px solid var(--line);
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
                meta=(
                    '<p class="resume-role-meta">{meta}</p>'.format(meta=html.escape(" | ".join(meta_parts)))
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


def _build_structured_resume_body(artifact: TailoredResumeArtifact):
    name = html.escape(artifact.header.full_name or artifact.title or "Candidate")
    subtitle_parts = [part for part in [artifact.target_role, artifact.header.location] if part]
    subtitle = html.escape(" | ".join(subtitle_parts)) if subtitle_parts else ""
    contact_html = _build_resume_section_list(
        artifact.header.contact_lines,
        "Contact details can be added before submission.",
        class_name="resume-contact-list",
    )
    skills_html = _build_resume_section_list(
        artifact.highlighted_skills,
        "No highlighted skills were generated.",
        class_name="resume-skill-list",
    )
    certifications_html = _build_resume_section_list(
        artifact.certifications,
        "No certifications listed.",
        class_name="resume-plain-list",
    )
    validation_html = _build_resume_section_list(
        artifact.validation_notes,
        "No validation notes were generated.",
        class_name="resume-plain-list",
    )
    return """
    <section class="resume-hero">
        <div class="resume-hero-main">
            <h1>{name}</h1>
            {subtitle}
            <div class="resume-summary-card">
                <h2>Professional Summary</h2>
                <p>{summary}</p>
            </div>
        </div>
        <aside class="resume-hero-side">
            <div class="resume-side-card">
                <h2>Contact</h2>
                {contact}
            </div>
            <div class="resume-side-card">
                <h2>Core Skills</h2>
                {skills}
            </div>
        </aside>
    </section>
    <section class="resume-section">
        <h2>Professional Experience</h2>
        {experience}
    </section>
    <section class="resume-grid">
        <div class="resume-section">
            <h2>Education</h2>
            {education}
        </div>
        <div class="resume-section">
            <h2>Certifications</h2>
            {certifications}
            <h2>Validation Notes</h2>
            {validation}
        </div>
    </section>
    """.format(
        name=name,
        subtitle=(
            '<p class="resume-subtitle">{subtitle}</p>'.format(subtitle=subtitle)
            if subtitle
            else ""
        ),
        summary=html.escape(artifact.professional_summary or "No professional summary generated."),
        contact=contact_html,
        skills=skills_html,
        experience=_build_resume_experience_html(artifact.experience_entries),
        education=_build_resume_education_html(artifact.education_entries),
        certifications=certifications_html,
        validation=validation_html,
    )


def _build_resume_html(text, title="Tailored Resume", theme="classic_ats", artifact: TailoredResumeArtifact | None = None):
    body_html = _build_structured_resume_body(artifact) if artifact is not None else _MARKDOWN.render(text or "")
    safe_title = html.escape(title or "Tailored Resume")

    if theme == "modern_professional":
        return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <title>{title}</title>
    <style>
        @page {{ size: A4; margin: 12mm 12mm 14mm 12mm; }}
        :root {{
            --ink: #2b2118;
            --muted: #766555;
            --accent: #a06b44;
            --accent-soft: #ead8c8;
            --paper: #f6efe8;
            --line: #d8c3b0;
            --surface: #fffaf6;
        }}
        * {{ box-sizing: border-box; }}
        body {{ margin: 0; font-family: Georgia, "Times New Roman", serif; color: var(--ink); background: var(--paper); font-size: 10.2pt; line-height: 1.56; }}
        .resume-shell {{ background: var(--surface); border: 1px solid rgba(160, 107, 68, 0.18); padding: 24px 26px 20px; }}
        .resume-shell::before {{ content: ""; display: block; height: 8px; border-radius: 999px; background: linear-gradient(90deg, #c89b77 0%, #a06b44 60%, #7f5539 100%); margin-bottom: 18px; }}
        h1 {{ font-size: 24pt; letter-spacing: 0.03em; margin: 0 0 8px; text-transform: uppercase; color: #2d1f14; }}
        h2 {{ font-size: 10pt; text-transform: uppercase; letter-spacing: 0.24em; color: var(--accent); margin: 20px 0 8px; padding-bottom: 5px; border-bottom: 1px solid var(--line); }}
        h3 {{ font-size: 11pt; margin: 12px 0 5px; color: #4d3526; }}
        p {{ margin: 0 0 9px; }}
        ul {{ margin: 0 0 10px 1rem; padding: 0; }}
        li {{ margin: 0 0 4px; }}
        strong {{ color: #2d1f14; }}
        em {{ color: var(--muted); }}
        code {{ background: #f2e7dc; border: 1px solid #e1cfbf; border-radius: 4px; padding: 0.08rem 0.28rem; }}
        hr {{ border: 0; border-top: 1px solid var(--line); margin: 16px 0; }}
        blockquote {{ margin: 0 0 10px; padding: 8px 12px; border-left: 4px solid #c89b77; background: var(--accent-soft); color: #5d493b; }}
        .resume-hero {{ display: grid; grid-template-columns: minmax(0, 2.1fr) minmax(220px, 0.9fr); gap: 18px; align-items: start; }}
        .resume-subtitle {{ margin: 0 0 12px; color: var(--muted); font-size: 10.4pt; font-style: italic; }}
        .resume-summary-card, .resume-side-card, .resume-experience-card, .resume-education-card {{ background: rgba(255, 250, 246, 0.96); border: 1px solid rgba(160, 107, 68, 0.12); border-radius: 14px; padding: 12px 14px; }}
        .resume-side-card + .resume-side-card {{ margin-top: 12px; }}
        .resume-grid {{ display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(0, 0.9fr); gap: 16px; }}
        .resume-role-row {{ display: flex; justify-content: space-between; gap: 14px; align-items: flex-start; }}
        .resume-role-row h3, .resume-education-card h3 {{ margin: 0 0 4px; }}
        .resume-role-meta, .resume-role-dates, .resume-education-meta, .resume-education-dates {{ margin: 0; color: var(--muted); font-size: 9.4pt; }}
        .resume-bullet-list, .resume-contact-list, .resume-plain-list {{ margin: 0; padding-left: 1rem; }}
        .resume-skill-list {{ list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 8px; }}
        .resume-skill-list li {{ background: #f2e7dc; border: 1px solid #e1cfbf; border-radius: 999px; padding: 0.3rem 0.55rem; margin: 0; font-size: 9.3pt; }}
        .resume-empty {{ color: var(--muted); font-style: italic; }}
        .resume-section + .resume-section {{ margin-top: 16px; }}
        .resume-experience-card + .resume-experience-card, .resume-education-card + .resume-education-card {{ margin-top: 12px; }}
        @media all and (max-width: 720px) {{ .resume-hero, .resume-grid {{ grid-template-columns: 1fr; }} .resume-role-row {{ display: block; }} .resume-role-dates {{ margin-top: 6px; }} }}
    </style>
</head>
<body>
    <main class="resume-shell resume-shell--modern">{body}</main>
</body>
</html>
""".format(title=safe_title, body=body_html)

    return """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8" />
    <title>{title}</title>
    <style>
        @page {{ size: A4; margin: 12mm 12mm 14mm 12mm; }}
        :root {{
            --ink: #10213f;
            --muted: #4f678c;
            --accent: #2563eb;
            --accent-soft: #dbeafe;
            --line: #bfd6f7;
            --surface: #ffffff;
        }}
        * {{ box-sizing: border-box; }}
        body {{ margin: 0; font-family: Arial, Helvetica, sans-serif; color: var(--ink); background: #f7fbff; font-size: 10pt; line-height: 1.48; }}
        .resume-shell {{ position: relative; background: var(--surface); border: 1px solid rgba(37, 99, 235, 0.14); padding: 18px 18px 18px 24px; }}
        .resume-shell::before {{ content: ""; position: absolute; top: 0; left: 0; bottom: 0; width: 7px; background: linear-gradient(180deg, #60a5fa 0%, #2563eb 60%, #1d4ed8 100%); }}
        h1 {{ font-size: 22pt; margin: 0 0 6px; letter-spacing: 0.02em; color: #0f172a; text-transform: uppercase; }}
        h2 {{ font-size: 10.6pt; margin: 18px 0 8px; text-transform: uppercase; letter-spacing: 0.14em; color: var(--accent); padding-bottom: 4px; border-bottom: 1px solid var(--line); }}
        h3 {{ font-size: 10.5pt; margin: 10px 0 4px; color: #17356a; }}
        p {{ margin: 0 0 8px; }}
        ul {{ margin: 0 0 8px 1rem; padding: 0; }}
        li {{ margin: 0 0 3px; }}
        strong {{ color: #0f172a; }}
        em {{ color: var(--muted); }}
        code {{ background: #eef5ff; border: 1px solid #d3e5ff; border-radius: 4px; padding: 0.08rem 0.28rem; }}
        hr {{ border: 0; border-top: 1px solid var(--line); margin: 14px 0; }}
        blockquote {{ margin: 0 0 10px; padding: 8px 12px; border-left: 4px solid var(--accent); background: var(--accent-soft); color: #24497b; }}
        .resume-hero {{ display: grid; grid-template-columns: minmax(0, 1.9fr) minmax(200px, 0.95fr); gap: 16px; align-items: start; }}
        .resume-subtitle {{ margin: 0 0 10px; color: var(--muted); font-size: 10pt; }}
        .resume-summary-card, .resume-side-card, .resume-experience-card, .resume-education-card {{ background: #ffffff; border: 1px solid rgba(37, 99, 235, 0.10); border-radius: 12px; padding: 11px 12px; }}
        .resume-side-card + .resume-side-card {{ margin-top: 10px; }}
        .resume-grid {{ display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(0, 0.9fr); gap: 14px; }}
        .resume-role-row {{ display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }}
        .resume-role-row h3, .resume-education-card h3 {{ margin: 0 0 4px; }}
        .resume-role-meta, .resume-role-dates, .resume-education-meta, .resume-education-dates {{ margin: 0; color: var(--muted); font-size: 9.2pt; }}
        .resume-bullet-list, .resume-contact-list, .resume-plain-list {{ margin: 0; padding-left: 1rem; }}
        .resume-skill-list {{ list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 6px; }}
        .resume-skill-list li {{ background: #eef5ff; border: 1px solid #d3e5ff; border-radius: 999px; padding: 0.28rem 0.52rem; margin: 0; font-size: 9pt; }}
        .resume-empty {{ color: var(--muted); font-style: italic; }}
        .resume-section + .resume-section {{ margin-top: 15px; }}
        .resume-experience-card + .resume-experience-card, .resume-education-card + .resume-education-card {{ margin-top: 10px; }}
        @media all and (max-width: 720px) {{ .resume-hero, .resume-grid {{ grid-template-columns: 1fr; }} .resume-role-row {{ display: block; }} .resume-role-dates {{ margin-top: 6px; }} }}
    </style>
</head>
<body>
    <main class="resume-shell resume-shell--classic">{body}</main>
</body>
</html>
""".format(title=safe_title, body=body_html)


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
        canvas.drawString(doc.leftMargin, 18, "AI Job Application Agent")
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
        else _build_report_html(text, title=title)
    )


def _generate_pdf_with_weasyprint(text, title, theme=None, document_kind="report", artifact: TailoredResumeArtifact | None = None):
    _configure_weasyprint_windows_runtime()
    from weasyprint import HTML

    html_document = (
        _build_resume_html(text, title=title, theme=theme or "classic_ats", artifact=artifact)
        if document_kind == "tailored_resume"
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
