import json
from dataclasses import asdict
from typing import Any

from src.openai_service import OpenAIService
from src.schemas import ResumeDocument


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


def _coerce_entry_list(value: Any, allowed_keys: list[str], *, limit: int = 12) -> list[dict[str, str | list[str]]]:
    if not isinstance(value, list):
        return []

    entries: list[dict[str, str | list[str]]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        normalized: dict[str, str | list[str]] = {}
        for key in allowed_keys:
            raw_value = item.get(key)
            if key == "links":
                normalized[key] = _coerce_string_list(raw_value, limit=6)
            else:
                normalized[key] = _coerce_string(raw_value)

        if any(
            normalized.get(key)
            for key in allowed_keys
            if key != "links"
        ):
            entries.append(normalized)
        if len(entries) >= limit:
            break

    return entries


def _build_resume_llm_parser_prompt(resume_document: ResumeDocument) -> dict[str, Any]:
    contract = {
        "full_name": "string",
        "location": "string",
        "contact_lines": "array of strings with only true contact details",
        "summary": "string summary grounded in the resume text",
        "skills": "array of strings",
        "experience": (
            "array of objects with keys title, organization, location, start, end, description"
        ),
        "projects": (
            "array of objects with keys title, organization, start, end, description, links"
        ),
        "education": (
            "array of objects with keys institution, degree, field_of_study, start, end"
        ),
        "certifications": "array of strings",
        "source_signals": "array of short grounded notes about what was found in the resume",
    }
    contract_lines = "\n".join(
        '- "{key}": {description}'.format(key=key, description=description)
        for key, description in contract.items()
    )
    system_prompt = (
        "You are an extraction-only resume parser. "
        "Convert extracted resume text into a grounded JSON candidate snapshot. "
        "Use only details present in the provided resume text. "
        "Do not invent employers, projects, metrics, dates, or skills. "
        "Leave fields blank instead of guessing. "
        "Keep project names exactly when possible. "
        "Do not place project links in contact_lines. "
        "Separate projects from work experience whenever the resume treats them as projects. "
        "Return JSON only with exactly these top-level keys:\n"
        f"{contract_lines}"
    )
    user_prompt = (
        "Resume metadata:\n"
        + json.dumps(
            {
                "filetype": resume_document.filetype,
                "source": resume_document.source,
            },
            indent=2,
        )
        + "\n\nExtracted resume text:\n"
        + str(resume_document.text or "")
    )
    return {
        "system": system_prompt,
        "user": user_prompt,
        "expected_keys": list(contract.keys()),
    }


class ResumeLLMParserService:
    def __init__(self, openai_service: OpenAIService | None = None):
        self._openai_service = openai_service or OpenAIService()

    def is_available(self) -> bool:
        return bool(self._openai_service and self._openai_service.is_available())

    def parse(
        self,
        resume_document: ResumeDocument,
        *,
        max_completion_tokens: int = 2600,
    ) -> dict[str, Any]:
        if not isinstance(resume_document, ResumeDocument):
            raise TypeError("resume_document must be a ResumeDocument instance.")
        if not self.is_available():
            raise RuntimeError("OpenAI is not configured for experimental LLM resume parsing.")

        prompt = _build_resume_llm_parser_prompt(resume_document)
        payload = self._openai_service.run_json_prompt(
            prompt["system"],
            prompt["user"],
            expected_keys=prompt["expected_keys"],
            task_name="profile",
            max_completion_tokens=max_completion_tokens,
            metadata={
                "parser_mode": "experimental_resume_snapshot",
                "filetype": resume_document.filetype,
            },
            allow_output_budget_retry=False,
        )
        return {
            "full_name": _coerce_string(payload.get("full_name")),
            "location": _coerce_string(payload.get("location")),
            "contact_lines": _coerce_string_list(payload.get("contact_lines"), limit=8),
            "summary": _coerce_string(payload.get("summary")),
            "skills": _coerce_string_list(payload.get("skills"), limit=40),
            "experience": _coerce_entry_list(
                payload.get("experience"),
                ["title", "organization", "location", "start", "end", "description"],
                limit=16,
            ),
            "projects": _coerce_entry_list(
                payload.get("projects"),
                ["title", "organization", "start", "end", "description", "links"],
                limit=16,
            ),
            "education": _coerce_entry_list(
                payload.get("education"),
                ["institution", "degree", "field_of_study", "start", "end"],
                limit=8,
            ),
            "certifications": _coerce_string_list(payload.get("certifications"), limit=16),
            "source_signals": _coerce_string_list(payload.get("source_signals"), limit=12),
        }


def serialize_deterministic_profile(profile: Any) -> dict[str, Any]:
    return asdict(profile)
