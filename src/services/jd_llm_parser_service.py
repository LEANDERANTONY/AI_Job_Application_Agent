"""LLM-based job-description parser service.

Mirrors `ResumeLLMParserService` for the JD side: takes raw JD text,
asks the LLM to extract structured fields (title / location / salary /
experience requirement / hard skills / soft skills / must-haves /
nice-to-haves), returns a coerced dict.

The deterministic ``build_job_description_from_text`` parser uses
regex + a 158-item HARD_SKILL_KEYWORDS taxonomy, which scores ~0.78 on
our 15-fixture test set with location and salary at 33% pass rates.
This LLM service is the analogue to the resume LLM parser and gets
called as the primary path in ``build_job_description_from_text_auto``.
"""

from __future__ import annotations

import re
from typing import Any

from src.openai_service import OpenAIService


# Section-header strings the LLM sometimes echoes as a list item when
# the JD's headings sit immediately above a bullet block (e.g. the
# n8n "AI Product Builder" listing ends Must-Haves with the literal
# label "REQUIREMENTS / MUST-HAVES"). Anything matching this pattern
# after normalizing whitespace / punctuation is dropped from
# must_haves / nice_to_haves.
_SECTION_LABEL_ARTIFACT = re.compile(
    r"^(requirements?|must[\s\-_/]?haves?|nice[\s\-_/]?to[\s\-_/]?haves?|"
    r"qualifications?|preferred(?:\s+qualifications?)?|good\s+signals?|"
    r"good\s+to\s+have|bonus(?:\s+points?)?|"
    # "What you'll do" / "What we're looking for" / "What we look for" /
    # "What we want" — heading-style phrases the LLM sometimes echoes
    # as a list item. Accepts straight + smart apostrophes, optional
    # contraction ('re / 'll / are / will), an operative verb, and a
    # trailing "for" / "in" preposition.
    r"what\s+(?:we|you)(?:['’](?:re|ll|s)|\s+(?:are|will))?"
    r"(?:\s+(?:looking|look|need|want|do))(?:\s+(?:for|in|at))?"
    r")[\s:.\-]*$",
    re.IGNORECASE,
)

# Benefits / perks vocabulary the LLM sometimes swept into
# nice_to_haves when a "Benefits" block sits adjacent to the
# "Nice to have" block in the JD. These are compensation, not
# job-requirement signal — they don't belong in either list because
# matching against them produces nonsense ("candidate has 401k").
_BENEFIT_KEYWORDS = (
    "vacation", " pto ", "(pto)", "paid time off", "parental leave",
    "maternity leave", "paternity leave", "health insurance",
    "medical insurance", "dental insurance", "vision insurance",
    "medical, dental", "dental, vision", "health, dental",
    "health coverage", "medical coverage", " hsa ", "(hsa)",
    "health savings", "401(k)", "401k", " 401 k ", "retirement plan",
    "stock options", "equity grant", "rsu", " esop ",
    "wellness stipend", "wellness benefit", "gym membership",
    "free lunch", "snacks", "remote stipend", "home office stipend",
    "commuter benefit", "transit benefit", "life insurance",
    "disability insurance",
)


def _is_section_label_artifact(text: str) -> bool:
    return bool(_SECTION_LABEL_ARTIFACT.match(text.strip()))


def _looks_like_benefit(text: str) -> bool:
    # Pad with spaces so the substring scan treats abbreviation tokens
    # like ' pto ' / ' 401k ' as whole-word matches instead of matching
    # inside e.g. 'computational tools'.
    haystack = " " + text.strip().lower() + " "
    return any(keyword in haystack for keyword in _BENEFIT_KEYWORDS)


def _coerce_string(value: Any) -> str:
    return str(value or "").strip()


def _coerce_string_list(
    value: Any,
    *,
    limit: int = 24,
    drop_section_labels: bool = False,
    drop_benefits: bool = False,
) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _coerce_string(item)
        normalized = text.lower()
        if not text or normalized in seen:
            continue
        if drop_section_labels and _is_section_label_artifact(text):
            # LLM echoed a section header (e.g. "REQUIREMENTS",
            # "MUST-HAVES") as a list item — silently drop instead of
            # surfacing as a requirement.
            continue
        if drop_benefits and _looks_like_benefit(text):
            # Compensation / perks crept into a requirements list.
            # Drop instead of matching against the candidate's
            # qualifications, which would produce nonsense signal.
            continue
        cleaned.append(text)
        seen.add(normalized)
        if len(cleaned) >= limit:
            break
    return cleaned


def _build_jd_llm_parser_prompt(jd_text: str) -> dict[str, Any]:
    contract = {
        "title": "string — the role's job title (e.g. 'Senior Software Engineer'); "
                 "ignore preamble like 'Job Posting · Posted 3 days ago'",
        "location": "string — the work location (city + state/country, or 'Remote'); "
                    "if multiple locations are listed, return the first or 'Remote' when applicable; "
                    "leave blank if not stated",
        "salary": "string — the salary or compensation range as written in the JD (e.g. "
                  "'$180,000 - $240,000', '€95,000 - €130,000'); leave blank if not stated",
        "experience_requirement": "string — the minimum experience requirement as written "
                                  "(e.g. '5+ years', 'at least 7 years', 'senior level'); "
                                  "leave blank if not stated",
        "hard_skills": "array of strings — programming languages, frameworks, libraries, "
                       "platforms, tools (e.g. Python, PostgreSQL, Kubernetes, Mixpanel, "
                       "Snowplow). Include ALL technical skills mentioned, even niche ones "
                       "not in common taxonomies. Do NOT include soft skills.",
        "soft_skills": "array of strings — people skills, traits, communication abilities "
                       "(e.g. 'communication', 'leadership', 'collaboration')",
        "must_haves": "array of strings — required-experience phrases the JD marks as "
                      "mandatory (e.g. '5+ years building production backend services', "
                      "'BSc in Computer Science'). Each entry should be a distinct line. "
                      "Do NOT echo section headers like 'REQUIREMENTS', 'MUST-HAVES', "
                      "'QUALIFICATIONS' as list items — those are headings, not requirements.",
        "nice_to_haves": "array of strings — preferred / bonus / nice-to-have QUALIFICATIONS "
                         "(extra skills, prior experience, certifications). Do NOT include "
                         "benefits, perks, or compensation (vacation, PTO, parental leave, "
                         "health / medical / dental / vision insurance, HSA, 401(k), stock "
                         "options, RSU, wellness stipend, gym, remote stipend) — those are "
                         "what the company offers the candidate, not what the candidate "
                         "needs to bring.",
    }
    contract_lines = "\n".join(
        '- "{key}": {description}'.format(key=key, description=description)
        for key, description in contract.items()
    )
    system_prompt = (
        "You are an extraction-only job-description parser. "
        "Convert raw job-listing text into a grounded JSON snapshot. "
        "Use only details present in the provided JD text. "
        "Do not invent salary numbers, location, or skills the JD doesn't mention. "
        "Leave fields blank instead of guessing. "
        "Be liberal with hard_skills — capture vendor / niche tool names exactly as written "
        "(e.g. Mixpanel, Snowplow, Klaviyo, Iterable, Datadog, Snowflake) — your job is to "
        "surface every technical-tool reference, not just common languages. "
        "When the JD lists multiple locations separated by bullets / pipes / semicolons, "
        "return the first non-Remote one as the primary location. "
        # Canonicalization: skill output is compared against the resume
        # parser's skill output via string equality on the matching
        # layer. Use the formal canonical name so synonym variants
        # don't silently fall on opposite sides of the match.
        "For skill names, prefer the formal canonical form: write "
        "'PostgreSQL' (not 'Postgres'), 'Kubernetes' (not 'k8s'), "
        "'JavaScript' (not 'JS'), 'TypeScript' (not 'TS'), 'Node.js' "
        "(not 'NodeJS' / 'node js'), 'TensorFlow' (not 'TF'), 'scikit-learn' "
        "(not 'sklearn'). When the JD itself uses a short form, you may keep "
        "the short form if that's the official product name (e.g. 'AWS' is "
        "fine — that's the canonical product name). "
        "Return JSON only with exactly these top-level keys:\n"
        f"{contract_lines}"
    )
    user_prompt = "Job description text:\n" + str(jd_text or "")
    return {
        "system": system_prompt,
        "user": user_prompt,
        "expected_keys": list(contract.keys()),
    }


class JobDescriptionLLMParserService:
    """Parallel to ``ResumeLLMParserService`` — LLM-driven extraction
    of structured JobDescription fields from raw JD text."""

    def __init__(self, openai_service: OpenAIService | None = None):
        self._openai_service = openai_service or OpenAIService()

    def is_available(self) -> bool:
        return bool(self._openai_service and self._openai_service.is_available())

    def parse(
        self,
        jd_text: str,
        # Same failure class the resume parser hit: a long, detailed
        # job description (full responsibilities + a 40-item hard-skill
        # list + must/nice-to-haves) overruns a tight cap, the JSON
        # truncates mid-string, and build_job_description_from_text_auto
        # silently falls back to the lower-fidelity deterministic JD
        # parser. That degraded JD then feeds fit analysis, tailoring,
        # and the cover letter — so the truncation cascades through the
        # whole workflow. max_output_tokens is a ceiling, not a
        # reservation: raising it is free for ordinary JDs.
        *,
        max_completion_tokens: int = 4000,
    ) -> dict[str, Any]:
        if not jd_text or not str(jd_text).strip():
            raise ValueError("Job description text must not be empty.")
        if not self.is_available():
            raise RuntimeError("OpenAI is not configured for LLM JD parsing.")

        prompt = _build_jd_llm_parser_prompt(jd_text)
        payload = self._openai_service.run_json_prompt(
            prompt["system"],
            prompt["user"],
            expected_keys=prompt["expected_keys"],
            task_name="job",
            max_completion_tokens=max_completion_tokens,
            metadata={"parser_mode": "experimental_job_snapshot"},
            # Safety net for the long-tail JD that still overruns the
            # generous base above: auto-retry once at a higher budget
            # rather than silently degrading to the deterministic
            # parser. Rarely fires given the base bump.
            allow_output_budget_retry=True,
        )
        return {
            "title": _coerce_string(payload.get("title")),
            "location": _coerce_string(payload.get("location")),
            "salary": _coerce_string(payload.get("salary")),
            "experience_requirement": _coerce_string(payload.get("experience_requirement")),
            "hard_skills": _coerce_string_list(payload.get("hard_skills"), limit=40),
            "soft_skills": _coerce_string_list(payload.get("soft_skills"), limit=20),
            # must_haves / nice_to_haves get the extra scrub passes:
            # strip section-header artifacts the LLM occasionally echoes
            # as list items, and drop benefit / perk vocabulary that
            # shouldn't be matched against the candidate's skills.
            "must_haves": _coerce_string_list(
                payload.get("must_haves"),
                limit=10,
                drop_section_labels=True,
                drop_benefits=True,
            ),
            "nice_to_haves": _coerce_string_list(
                payload.get("nice_to_haves"),
                limit=10,
                drop_section_labels=True,
                drop_benefits=True,
            ),
        }
