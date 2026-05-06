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

import json
from typing import Any

from src.openai_service import OpenAIService


def _coerce_string(value: Any) -> str:
    return str(value or "").strip()


def _coerce_string_list(value: Any, *, limit: int = 24) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _coerce_string(item)
        normalized = text.lower()
        if not text or normalized in seen:
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
                      "'BSc in Computer Science'). Each entry should be a distinct line.",
        "nice_to_haves": "array of strings — preferred / bonus / nice-to-have qualifications",
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
        *,
        max_completion_tokens: int = 2200,
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
            allow_output_budget_retry=False,
        )
        return {
            "title": _coerce_string(payload.get("title")),
            "location": _coerce_string(payload.get("location")),
            "salary": _coerce_string(payload.get("salary")),
            "experience_requirement": _coerce_string(payload.get("experience_requirement")),
            "hard_skills": _coerce_string_list(payload.get("hard_skills"), limit=40),
            "soft_skills": _coerce_string_list(payload.get("soft_skills"), limit=20),
            "must_haves": _coerce_string_list(payload.get("must_haves"), limit=10),
            "nice_to_haves": _coerce_string_list(payload.get("nice_to_haves"), limit=10),
        }
