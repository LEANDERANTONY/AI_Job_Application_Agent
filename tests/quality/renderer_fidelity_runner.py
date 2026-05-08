"""Tier-2 renderer-fidelity test runner.

Builds a handful of synthetic artifacts (TailoredResumeArtifact and
CoverLetterArtifact) that exercise normal, special-character, long,
and minimal content shapes. For each artifact, renders to HTML and
PDF, extracts the rendered text, and verifies every input string
round-trips into both surfaces. Repeats per theme so a fix to one
theme can't silently regress the other.

The renderer is deterministic — these tests catch two failure modes:

  1. String losses (HTML escaping bugs, line-truncation, whitespace
     collapse, pagination dropping content).
  2. Theme regressions (a CSS change to one theme accidentally
     breaking the other).

Usage:
    python tests/quality/renderer_fidelity_runner.py
    python tests/quality/renderer_fidelity_runner.py --json out.json

Run-time is ~3-5 seconds for 6 fixtures × 2 themes (resume) +
2 fixtures × 2 themes (cover letter). PDFs are rendered through
WeasyPrint locally.
"""

from __future__ import annotations

import argparse
import html as html_module
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from src.exporters import (
    build_cover_letter_preview_html,
    build_resume_preview_html,
    export_pdf_bytes,
)
from src.schemas import (
    CoverLetterArtifact,
    EducationEntry,
    ProjectEntry,
    ResumeExperienceEntry,
    ResumeHeader,
    TailoredResumeArtifact,
)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


@dataclass
class ResumeFixture:
    name: str
    artifact: TailoredResumeArtifact
    expected_strings: list[str] = field(default_factory=list)
    notes: str = ""


@dataclass
class CoverLetterFixture:
    name: str
    artifact: CoverLetterArtifact
    expected_strings: list[str] = field(default_factory=list)
    notes: str = ""


def _basic_resume(theme: str) -> ResumeFixture:
    artifact = TailoredResumeArtifact(
        title="Jane Engineer - Senior SWE Tailored Resume",
        filename_stem="jane-engineer-senior-swe",
        summary="A grounded resume for the role.",
        markdown="",
        plain_text="",
        theme=theme,
        header=ResumeHeader(
            full_name="Jane Engineer",
            location="Brooklyn, NY",
            contact_lines=[
                "jane.engineer@example.com",
                "+1 (212) 555-0182",
                "linkedin.com/in/janeengineer",
                "github.com/janee",
            ],
        ),
        target_role="Senior Software Engineer",
        professional_summary=(
            "Senior engineer with eight years of experience building "
            "high-throughput backend services at scale. Strong on system "
            "design and post-mortem culture."
        ),
        highlighted_skills=[
            "Python",
            "Go",
            "Distributed Systems",
            "PostgreSQL",
            "Kubernetes",
            "Kafka",
            "AWS",
            "Terraform",
        ],
        experience_entries=[
            ResumeExperienceEntry(
                title="Senior Software Engineer",
                organization="Acme Corp",
                location="New York, NY",
                start="2022",
                end="Present",
                bullets=[
                    "Owned the order-fulfillment microservice handling 2M orders per month.",
                    "Cut p99 latency by 40 percent via consistent-hash sharding.",
                    "Mentored three junior engineers through their first on-call rotations.",
                ],
            ),
            ResumeExperienceEntry(
                title="Software Engineer",
                organization="Foo Inc",
                location="Remote",
                start="2018",
                end="2022",
                bullets=[
                    "Built the billing service in Go on Postgres.",
                    "Migrated 2M MAU off legacy MySQL with zero downtime.",
                ],
            ),
        ],
        education_entries=[
            EducationEntry(
                institution="Cornell University",
                degree="Bachelor of Science",
                field_of_study="Computer Science",
                start="2014",
                end="2018",
            ),
        ],
        certifications=[
            "AWS Certified Solutions Architect (Associate)",
            "Certified Kubernetes Administrator",
        ],
        project_entries=[
            ProjectEntry(
                name="DistKV",
                description="Raft-based distributed key-value store.",
                bullets=["Sub-3ms p99 latency under 50k QPS."],
                technologies=["Go", "gRPC"],
                link="github.com/jane/distkv",
            ),
        ],
        publication_entries=[
            "Engineer, J. (2024). On consistent hashing in geo-distributed caches. SIGOPS Workshop 2024.",
        ],
    )
    expected: list[str] = [
        "Jane Engineer",
        "Brooklyn, NY",
        "jane.engineer@example.com",
        "+1 (212) 555-0182",
        "linkedin.com/in/janeengineer",
        "github.com/janee",
        "Senior engineer with eight years",
        "post-mortem culture",
        "Python",
        "Distributed Systems",
        "PostgreSQL",
        "Senior Software Engineer",
        "Acme Corp",
        "New York, NY",
        "2022",
        "Present",
        "Owned the order-fulfillment microservice",
        "p99 latency by 40 percent",
        "Mentored three junior engineers",
        "Software Engineer",
        "Foo Inc",
        "Remote",
        "Built the billing service in Go on Postgres",
        "Migrated 2M MAU off legacy MySQL",
        "Cornell University",
        "Bachelor of Science",
        "Computer Science",
        "AWS Certified Solutions Architect",
        "Certified Kubernetes Administrator",
        "DistKV",
        "Raft-based distributed key-value store",
        "Sub-3ms p99 latency under 50k QPS",
        "github.com/jane/distkv",
        "On consistent hashing in geo-distributed caches",
    ]
    return ResumeFixture(
        name="basic-{}".format(theme),
        artifact=artifact,
        expected_strings=expected,
        notes="Normal-length artifact with every section populated.",
    )


def _special_chars_resume(theme: str) -> ResumeFixture:
    """Tests HTML escaping of <, >, &, ", ', accented chars, em-dashes,
    percent / dollar signs in bullets and headers."""
    artifact = TailoredResumeArtifact(
        title="Niño O'Brien - Sr Eng Tailored Resume",
        filename_stem="nino-obrien-sr-eng",
        summary="Edge case resume.",
        markdown="",
        plain_text="",
        theme=theme,
        header=ResumeHeader(
            full_name="Niño O'Brien-Müller",
            location="São Paulo, Brasil",
            contact_lines=[
                "nino.obrien@example.com",
                "+55 11 9 8765-4321",
            ],
        ),
        professional_summary=(
            "Engineer who shipped a checkout flow improving conversion "
            "by 22% (from 3.4% → 4.2%) and reduced infra cost by $1.2M/year. "
            'Co-author of the "Service Mesh Boundaries" RFC.'
        ),
        highlighted_skills=[
            "C++",
            "C#",
            ".NET",
            "Go (1.21+)",
            "k8s",
        ],
        experience_entries=[
            ResumeExperienceEntry(
                title="Staff Engineer (L7)",
                organization="<acme>/</acme>",
                location="Remote",
                start="2020",
                end="Present",
                bullets=[
                    "Cut p99 from 240ms → 45ms while doubling throughput (2.4×).",
                    'Authored the "Adversary-in-the-Middle" detection playbook.',
                    "Owned <500ms SLA for >2M users; achieved 99.97% uptime.",
                    "Reduced cloud spend $1.2M ($340/customer-month) via right-sizing.",
                ],
            ),
        ],
        education_entries=[
            EducationEntry(
                institution="Universidade de São Paulo",
                degree="B.S.",
                field_of_study="Engenharia da Computação",
                start="2015",
                end="2019",
            ),
        ],
        certifications=["AWS Certified — DevOps Engineer (Professional)"],
        project_entries=[],
        publication_entries=[],
    )
    expected = [
        "Niño O'Brien-Müller",
        "São Paulo, Brasil",
        "nino.obrien@example.com",
        "+55 11 9 8765-4321",
        "improving conversion by 22%",
        "(from 3.4% → 4.2%)",
        "$1.2M/year",
        '"Service Mesh Boundaries" RFC',
        "C++",
        "C#",
        ".NET",
        "Go (1.21+)",
        "Staff Engineer (L7)",
        "<acme>/</acme>",
        "Remote",
        "Cut p99 from 240ms → 45ms",
        "doubling throughput (2.4×)",
        '"Adversary-in-the-Middle" detection playbook',
        "<500ms SLA for >2M users",
        "achieved 99.97% uptime",
        "$1.2M ($340/customer-month)",
        "Universidade de São Paulo",
        "Engenharia da Computação",
        "AWS Certified — DevOps Engineer",
    ]
    return ResumeFixture(
        name="special-chars-{}".format(theme),
        artifact=artifact,
        expected_strings=expected,
        notes="HTML escaping + Unicode + currency / percent / arrows / quotes / parens.",
    )


def _long_content_resume(theme: str) -> ResumeFixture:
    """Five experience entries with dense bullets — tests pagination
    doesn't silently drop content past page 1."""
    experience_entries: list[ResumeExperienceEntry] = []
    for index, (title, org) in enumerate(
        [
            ("Senior Software Engineer", "Acme Corp"),
            ("Software Engineer", "Foo Inc"),
            ("Backend Engineer", "Bar Labs"),
            ("Junior Engineer", "Baz Co"),
            ("Software Engineering Intern", "Qux Group"),
        ]
    ):
        bullets = [
            "Bullet 1 at {org}: an unusually long bullet that exceeds 100 characters by including specific quantitative metrics like 12.3% lift and 4.5M users.".format(org=org),
            "Bullet 2 at {org}: shipped feature X to N users".format(org=org),
            "Bullet 3 at {org}: led migration of system Y from A to B".format(org=org),
        ]
        experience_entries.append(
            ResumeExperienceEntry(
                title=title,
                organization=org,
                location="Remote",
                start=str(2024 - 2 * index - 2),
                end=str(2024 - 2 * index),
                bullets=bullets,
            )
        )

    artifact = TailoredResumeArtifact(
        title="Long CV - Senior SWE Tailored Resume",
        filename_stem="long-cv",
        summary="Long CV.",
        markdown="",
        plain_text="",
        theme=theme,
        header=ResumeHeader(
            full_name="Long Curriculum",
            location="Seattle, WA",
            contact_lines=["long@example.com"],
        ),
        professional_summary="Engineer with a long history.",
        highlighted_skills=["Python", "Go"],
        experience_entries=experience_entries,
        education_entries=[
            EducationEntry(
                institution="Stanford University",
                degree="M.S.",
                field_of_study="CS",
                start="2010",
                end="2012",
            ),
        ],
        certifications=[],
        project_entries=[],
        publication_entries=[],
    )
    expected = [
        "Long Curriculum",
        "Seattle, WA",
        "Senior Software Engineer",
        "Acme Corp",
        "Software Engineer",
        "Foo Inc",
        "Backend Engineer",
        "Bar Labs",
        "Junior Engineer",
        "Baz Co",
        "Software Engineering Intern",
        "Qux Group",
        # Last-entry-on-page-2 bullets — these would be silently lost
        # if pagination dropped them.
        "shipped feature X to N users",
        "led migration of system Y from A to B",
        "Stanford University",
    ]
    return ResumeFixture(
        name="long-content-{}".format(theme),
        artifact=artifact,
        expected_strings=expected,
        notes="Five jobs × three bullets — checks pagination doesn't drop late content.",
    )


def _minimal_resume(theme: str) -> ResumeFixture:
    """Only the required sections (header, summary, skills, education)
    populated. Experience / Projects / Publications / Certifications
    are empty and SHOULD be dropped from the output (not rendered as
    'No X listed.' filler)."""
    artifact = TailoredResumeArtifact(
        title="Minimal Resume",
        filename_stem="minimal",
        summary="",
        markdown="",
        plain_text="",
        theme=theme,
        header=ResumeHeader(
            full_name="Min Imal",
            location="",
            contact_lines=["min@example.com"],
        ),
        professional_summary="A short summary.",
        highlighted_skills=["Python"],
        experience_entries=[],
        education_entries=[
            EducationEntry(
                institution="MIT",
                degree="B.S.",
                field_of_study="CS",
                start="2020",
                end="2024",
            ),
        ],
        certifications=[],
        project_entries=[],
        publication_entries=[],
    )
    expected = [
        "Min Imal",
        "min@example.com",
        "A short summary",
        "Python",
        "MIT",
        "B.S.",
    ]
    forbidden = [
        # Empty optional sections must be DROPPED — these strings
        # appear only when their section renders.
        "<h2>Experience</h2>",
        "<h2>Projects</h2>",
        "<h2>Publications</h2>",
        "<h2>Certifications</h2>",
    ]
    fixture = ResumeFixture(
        name="minimal-{}".format(theme),
        artifact=artifact,
        expected_strings=expected,
        notes="Empty Experience/Projects/Publications/Certifications must drop, not render placeholder filler.",
    )
    fixture.forbidden_strings = forbidden  # type: ignore[attr-defined]
    return fixture


def _basic_cover_letter(theme: str) -> CoverLetterFixture:
    artifact = CoverLetterArtifact(
        title="Cover Letter — Senior Software Engineer at Acme",
        filename_stem="cover-letter",
        summary="",
        plain_text="",
        theme=theme,
        markdown=(
            "**Jane Engineer**\n"
            "Brooklyn, NY | jane.engineer@example.com | +1 (212) 555-0182\n\n"
            "# Senior Software Engineer Application\n\n"
            "**Senior Software Engineer at Acme**\n\n"
            "---\n\n"
            "Dear Hiring Manager,\n\n"
            "I am writing to apply for the Senior Software Engineer role on the platform team. "
            "Across eight years building distributed systems, I have shipped low-latency services that "
            "serve millions of users a day, and I would bring that ownership instinct to Acme.\n\n"
            "In my current role, I own the cache layer that fronts the highest-traffic API. After "
            "a redesign around consistent-hash sharding, I cut p99 from 12ms to under 3ms while "
            "doubling the workload it could absorb.\n\n"
            "I would welcome the chance to talk about how that experience maps onto the work your "
            "team is taking on.\n\n"
            "Sincerely,\n\n"
            "Jane Engineer"
        ),
    )
    # The cover letter renderer DELIBERATELY strips the first H1 from
    # the markdown body (it would duplicate the page title). So
    # expectations focus on (a) the page title from artifact.title,
    # (b) the bold "Senior Software Engineer at Acme" subtitle which
    # is a separate paragraph, and (c) the body paragraphs / signoff.
    expected = [
        "Jane Engineer",
        "Brooklyn, NY",
        "jane.engineer@example.com",
        "Cover Letter",  # from artifact.title page header
        "Senior Software Engineer at Acme",  # bold subtitle in body
        "Dear Hiring Manager",
        "Across eight years building distributed systems",
        "ownership instinct to Acme",
        "consistent-hash sharding",
        "p99 from 12ms to under 3ms",
        "doubling the workload it could absorb",
        "Sincerely",
    ]
    return CoverLetterFixture(
        name="cover-basic-{}".format(theme),
        artifact=artifact,
        expected_strings=expected,
        notes="Standard cover letter — multiple paragraphs, signoff, header. Body H1 stripping is intentional (de-dupes with page title).",
    )


def _special_chars_cover_letter(theme: str) -> CoverLetterFixture:
    artifact = CoverLetterArtifact(
        title="Cover Letter — Niño O'Brien at <acme>",
        filename_stem="cover-letter-special",
        summary="",
        plain_text="",
        theme=theme,
        markdown=(
            "**Niño O'Brien-Müller**\n"
            "São Paulo, Brasil | nino@example.com\n\n"
            "# Engineer Application\n\n"
            "**Senior Engineer at Acme**\n\n"
            "---\n\n"
            "Dear Hiring Manager,\n\n"
            "I am applying for the role at Acme. In my last project I "
            "delivered a 22% lift (3.4% → 4.2%) on checkout conversion and "
            "reduced infra cost by $1.2M/year. I'm also the co-author of "
            'the "Service Mesh Boundaries" RFC adopted across the org.\n\n'
            "I'd love to discuss how this maps to your team's priorities.\n\n"
            "Sincerely,\n\n"
            "Niño O'Brien-Müller"
        ),
    )
    # Body H1 stripping is intentional. Title comes from artifact.title.
    expected = [
        "Niño O'Brien-Müller",
        "São Paulo, Brasil",
        "nino@example.com",
        "Senior Engineer at Acme",  # bold subtitle in body
        "delivered a 22% lift (3.4% → 4.2%)",
        "reduced infra cost by $1.2M/year",
        '"Service Mesh Boundaries" RFC',
        "Sincerely",
    ]
    return CoverLetterFixture(
        name="cover-special-chars-{}".format(theme),
        artifact=artifact,
        expected_strings=expected,
        notes="HTML escaping + unicode + arrows + quotes in cover-letter prose. Body H1 stripping is intentional.",
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    import pypdfium2 as pdfium  # local import: heavy dependency

    pieces: list[str] = []
    with pdfium.PdfDocument(pdf_bytes) as doc:
        for page_index in range(len(doc)):
            page = doc[page_index]
            text_page = page.get_textpage()
            try:
                pieces.append(text_page.get_text_range())
            finally:
                text_page.close()
    return "\n".join(pieces)


def _normalise(text: str) -> str:
    """Collapse whitespace so 'foo  bar' and 'foo bar' compare equal."""
    return " ".join(text.split())


def _string_present(needle: str, *haystacks: str) -> bool:
    """A needle is 'present' if any normalised haystack contains the
    normalised needle, OR contains the HTML-escaped form. Matches
    both raw text in PDF extraction and the escaped form embedded in
    HTML."""
    needle_norm = _normalise(needle)
    needle_escaped = _normalise(html_module.escape(needle))
    for haystack in haystacks:
        haystack_norm = _normalise(haystack)
        if needle_norm in haystack_norm or needle_escaped in haystack_norm:
            return True
    return False


def _check_fixture(
    name: str,
    expected_strings: list[str],
    forbidden_strings: list[str],
    html_text: str,
    pdf_text: str,
) -> dict:
    expected_results: list[dict] = []
    for needle in expected_strings:
        in_html = _string_present(needle, html_text)
        in_pdf = _string_present(needle, pdf_text)
        expected_results.append(
            {
                "needle": needle,
                "in_html": in_html,
                "in_pdf": in_pdf,
                "ok": in_html and in_pdf,
            }
        )
    forbidden_results: list[dict] = []
    for needle in forbidden_strings:
        present = needle in html_text
        forbidden_results.append({"needle": needle, "present": present, "ok": not present})

    expected_passes = sum(1 for r in expected_results if r["ok"])
    forbidden_passes = sum(1 for r in forbidden_results if r["ok"])
    return {
        "name": name,
        "expected_total": len(expected_results),
        "expected_passes": expected_passes,
        "forbidden_total": len(forbidden_results),
        "forbidden_passes": forbidden_passes,
        "expected": expected_results,
        "forbidden": forbidden_results,
        "html_chars": len(html_text),
        "pdf_chars": len(pdf_text),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path, default=None, help="Write full results to JSON.")
    args = parser.parse_args()

    fixtures: list[dict] = []

    for theme in ["classic_ats", "professional_neutral"]:
        for builder in [
            _basic_resume,
            _special_chars_resume,
            _long_content_resume,
            _minimal_resume,
        ]:
            fixture = builder(theme)
            html_text = build_resume_preview_html(fixture.artifact)
            pdf_bytes = export_pdf_bytes(fixture.artifact)
            pdf_text = _extract_pdf_text(pdf_bytes)
            forbidden = list(getattr(fixture, "forbidden_strings", []))
            result = _check_fixture(
                fixture.name,
                fixture.expected_strings,
                forbidden,
                html_text,
                pdf_text,
            )
            result["kind"] = "resume"
            result["theme"] = theme
            result["notes"] = fixture.notes
            fixtures.append(result)

        for builder in [_basic_cover_letter, _special_chars_cover_letter]:
            cl_fixture = builder(theme)
            html_text = build_cover_letter_preview_html(cl_fixture.artifact)
            pdf_bytes = export_pdf_bytes(cl_fixture.artifact)
            pdf_text = _extract_pdf_text(pdf_bytes)
            result = _check_fixture(
                cl_fixture.name,
                cl_fixture.expected_strings,
                [],
                html_text,
                pdf_text,
            )
            result["kind"] = "cover_letter"
            result["theme"] = theme
            result["notes"] = cl_fixture.notes
            fixtures.append(result)

    # ---------- Report ----------
    print()
    print("=" * 78)
    print("Tier-2 renderer fidelity scorecard")
    print("=" * 78)
    print(f"{'Fixture':<40}{'HTML+PDF':<14}{'Forbidden':<14}{'Result':<10}")
    print("-" * 78)
    overall_pass = True
    for entry in fixtures:
        expected_score = "{} / {}".format(entry["expected_passes"], entry["expected_total"])
        forbidden_score = (
            "{} / {}".format(entry["forbidden_passes"], entry["forbidden_total"])
            if entry["forbidden_total"]
            else "n/a"
        )
        all_expected = entry["expected_passes"] == entry["expected_total"]
        all_forbidden = entry["forbidden_passes"] == entry["forbidden_total"]
        ok = all_expected and all_forbidden
        if not ok:
            overall_pass = False
        flag = "[ok]" if ok else "[FAIL]"
        print(f"{entry['name']:<40}{expected_score:<14}{forbidden_score:<14}{flag:<10}")

    failures = [e for e in fixtures if e["expected_passes"] < e["expected_total"] or e["forbidden_passes"] < e["forbidden_total"]]
    if failures:
        print()
        print("=" * 78)
        print("Failure detail")
        print("=" * 78)
        for entry in failures:
            print()
            print(f"--- {entry['name']} ({entry['kind']}, theme={entry['theme']}) ---")
            for r in entry["expected"]:
                if not r["ok"]:
                    where = []
                    if not r["in_html"]:
                        where.append("HTML")
                    if not r["in_pdf"]:
                        where.append("PDF")
                    print("  MISSING in {}: {!r}".format(", ".join(where), r["needle"]))
            for r in entry["forbidden"]:
                if not r["ok"]:
                    print("  PRESENT (forbidden): {!r}".format(r["needle"]))

    print()
    print("=" * 78)
    print("OVERALL: {}".format("PASS" if overall_pass else "FAIL"))
    print("=" * 78)

    if args.json:
        args.json.write_text(json.dumps(fixtures, indent=2), encoding="utf-8")
        print(f"\nWrote full results to {args.json}")

    sys.exit(0 if overall_pass else 1)


if __name__ == "__main__":
    main()
