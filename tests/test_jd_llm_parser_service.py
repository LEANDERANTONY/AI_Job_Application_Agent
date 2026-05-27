"""Tests for `src/services/jd_llm_parser_service.py`.

Two layers of behavior are pinned here:

  * The LLM call's `run_json_prompt` kwargs — output budget + retry
    safety net. A tight cap with retry disabled used to truncate
    detailed JDs and silently degrade build_job_description_from_text
    _auto into the deterministic fallback, which then cascaded
    through fit analysis, tailoring, and the cover letter.

  * The deterministic scrub passes between the LLM payload and the
    JobDescription handed back to the caller:
      - `_is_section_label_artifact` drops "REQUIREMENTS" /
        "MUST-HAVES" / "QUALIFICATIONS" / etc. that the model
        occasionally echoes as list items because the JD's headings
        were inlined adjacent to a bullet block (the n8n "AI Product
        Builder" listing tripped this).
      - `_looks_like_benefit` drops compensation / perks vocabulary
        (vacation, PTO, parental leave, medical/dental/vision, HSA,
        401(k), stock options, wellness stipend) that some LLM passes
        swept into `nice_to_haves` when a "Benefits" block sat right
        above the "Nice to have" block. Benefits are what the company
        offers, not what the candidate brings — matching against
        them produces nonsense signal.
      - `_coerce_string_list(drop_section_labels=, drop_benefits=)` —
        the public knob the parser uses on must_haves / nice_to_haves.

The full-fidelity LLM call itself isn't exercised here — that's
covered by `tests/quality/jd_parser_quality_runner.py` against
fixtures.
"""
from __future__ import annotations

from src.services.jd_llm_parser_service import (
    JobDescriptionLLMParserService,
    _coerce_string_list,
    _is_section_label_artifact,
    _looks_like_benefit,
)


class _RecordingOpenAIService:
    """Captures the run_json_prompt kwargs so we can assert the JD
    parser asks for enough output budget + keeps the retry net."""

    def __init__(self):
        self.kwargs = None

    def is_available(self):
        return True

    def run_json_prompt(self, *args, **kwargs):
        self.kwargs = kwargs
        return {
            "title": "AI Engineer",
            "location": "",
            "salary": "",
            "experience_requirement": "",
            "hard_skills": [],
            "soft_skills": [],
            "must_haves": [],
            "nice_to_haves": [],
        }


def test_jd_parser_requests_generous_budget_and_enables_retry():
    """Regression (mirror of the resume-parser fix): a detailed JD
    (full responsibilities + a long hard-skill list + must/nice-to-
    haves) truncated the JSON under a tight cap with budget-retry
    disabled, so build_job_description_from_text_auto silently fell
    back to the lower-fidelity deterministic JD parser. That degraded
    JD then feeds fit analysis, tailoring, and the cover letter — the
    truncation cascades. The parser must request a generous ceiling
    AND keep the auto-retry safety net.

    Bumped to >=6000 on 2026-05-27 alongside the JD path unification:
    paste / upload / load-from-search now ALL route through this
    parser, so dense JDs (n8n-style with 40+ skills + verbose
    benefits block) are routine. 6000 absorbs those in one call
    without firing the retry path.
    """
    recorder = _RecordingOpenAIService()
    service = JobDescriptionLLMParserService(openai_service=recorder)

    service.parse("Senior AI Engineer — lots of requirements ...")

    assert recorder.kwargs is not None
    assert recorder.kwargs["max_completion_tokens"] >= 6000
    assert recorder.kwargs["allow_output_budget_retry"] is True


def test_section_label_artifact_matches_common_headers():
    samples = [
        "REQUIREMENTS",
        "Must-Haves",
        "MUST HAVES",
        "must_haves",
        "Nice to have",
        "Nice-to-haves",
        "Qualifications:",
        "PREFERRED",
        "Good signals",
        "Good to have",
        "Bonus",
        "Bonus points",
        "What you'll do",
        "What we're looking for",
    ]
    for sample in samples:
        assert _is_section_label_artifact(sample), sample


def test_section_label_artifact_leaves_real_requirements_alone():
    samples = [
        "5+ years building production backend services",
        "BSc in Computer Science",
        "Strong English communication",
        "Experience with PostgreSQL at scale",
        # 'requirement' (singular noun, not a heading) embedded in a
        # sentence shouldn't false-positive.
        "Experience meeting product requirement docs",
    ]
    for sample in samples:
        assert not _is_section_label_artifact(sample), sample


def test_looks_like_benefit_matches_compensation_vocab():
    samples = [
        "Unlimited vacation",
        "Generous PTO",
        "Paid time off",
        "Parental leave",
        "Health, dental and vision insurance",
        "Medical, dental, vision coverage",
        "HSA contribution",
        "401(k) match",
        "401k retirement plan",
        "Stock options and RSU grants",
        "Monthly wellness stipend",
        "Home office stipend",
        "Commuter benefit",
    ]
    for sample in samples:
        assert _looks_like_benefit(sample), sample


def test_looks_like_benefit_leaves_real_requirements_alone():
    samples = [
        "Experience designing scalable APIs",
        "Comfort with Python and Django",
        "Track record shipping production ML systems",
        "Strong analytical and product-thinking skills",
        # "stock" appears (not stock options) — shouldn't match.
        "Familiarity with stock-management systems",
    ]
    for sample in samples:
        assert not _looks_like_benefit(sample), sample


def test_coerce_string_list_drops_artifacts_and_benefits_when_enabled():
    raw = [
        "5+ years building production backend services",
        "REQUIREMENTS",
        "MUST-HAVES",
        "BSc in Computer Science",
        "Unlimited PTO",
        "401(k) match",
        "Strong English communication",
        "",
        "5+ years building production backend services",  # duplicate
    ]
    cleaned = _coerce_string_list(
        raw, limit=20, drop_section_labels=True, drop_benefits=True
    )
    assert cleaned == [
        "5+ years building production backend services",
        "BSc in Computer Science",
        "Strong English communication",
    ]


def test_coerce_string_list_default_behavior_unchanged():
    # Without the new flags the function should behave exactly as
    # before: dedupe + strip + drop empties, but pass headers /
    # benefits through. The hard_skills / soft_skills call sites rely
    # on this — a tool name like "401k Plan SDK" (yes, hypothetical)
    # shouldn't get killed by the benefits filter on the skills list.
    raw = ["Python", "REQUIREMENTS", "Unlimited PTO", "", "python"]
    cleaned = _coerce_string_list(raw)
    assert cleaned == ["Python", "REQUIREMENTS", "Unlimited PTO"]
