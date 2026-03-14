import html
import hashlib
import logging
import re
from io import BytesIO

from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode

from src.errors import ExportError
from src.logging_utils import get_logger, log_event
from src.schemas import ApplicationReport


_MARKDOWN = MarkdownIt("commonmark", {"html": False})
LOGGER = get_logger(__name__)


def export_markdown_bytes(report: ApplicationReport) -> bytes:
    return report.markdown.encode("utf-8")


def export_text_bytes(report: ApplicationReport) -> bytes:
    return report.plain_text.encode("utf-8")


def export_pdf_bytes(report: ApplicationReport) -> bytes:
    try:
        return generate_pdf(report.markdown, title=report.title).getvalue()
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
      --shadow: 0 16px 34px rgba(15, 23, 42, 0.08);
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
      box-shadow: var(--shadow);
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
      word-break: break-word;
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


def _generate_pdf_with_playwright(text, title):
    from playwright.sync_api import sync_playwright

    html_document = _build_report_html(text, title=title)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page()
            page.set_content(html_document, wait_until="load")
            page.emulate_media(media="screen")
            pdf_bytes = page.pdf(
                format="A4",
                print_background=True,
                display_header_footer=True,
                header_template="<div></div>",
                footer_template="""
                    <div style="width:100%;font-size:8px;padding:6px 14px 0;color:#64748b;
                                border-top:1px solid #bfdbfe;
                                display:flex;justify-content:space-between;align-items:center;">
                      <span>AI Job Application Agent</span>
                      <span class="pageNumber"></span>
                    </div>
                """,
                margin={
                    "top": "18mm",
                    "right": "14mm",
                    "bottom": "16mm",
                    "left": "14mm",
                },
            )
        finally:
            browser.close()

    return BytesIO(pdf_bytes)


def generate_pdf(text, title="AI Job Application Package"):
    try:
        return _generate_pdf_with_playwright(text, title)
    except Exception as playwright_error:
        log_event(
            LOGGER,
            logging.WARNING,
            "pdf_export_playwright_failed",
            "Playwright PDF export failed; attempting ReportLab fallback.",
            title=title,
            error_type=type(playwright_error).__name__,
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
