from __future__ import annotations

from typing import Any

from src.config import get_openai_max_completion_tokens_for_task
from src.errors import AgentExecutionError
from src.llm_outage import outage_notice
from src.openai_service import OpenAIService
from src.schemas_llm_outputs import JDSummaryOutput
from src.services.job_service import extract_job_summary_sections


def _normalize_section_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    sections = []
    for raw_section in payload.get("sections", []) or []:
        title = str(raw_section.get("title", "") or "").strip()
        items = [
            str(item).strip()
            for item in raw_section.get("items", []) or []
            if str(item).strip()
        ]
        if title and items:
            sections.append({"title": title, "items": items})
    return sections


def generate_job_summary_view(*, openai_service: OpenAIService, job_description, imported_job_posting=None) -> dict[str, Any]:
    deterministic_sections = extract_job_summary_sections(
        job_description.cleaned_text,
        title=job_description.title,
    )
    if not openai_service or not openai_service.is_available():
        return {"mode": "deterministic", "sections": deterministic_sections}

    job_source = ""
    job_url = ""
    if imported_job_posting:
        job_source = str(imported_job_posting.get("source", "") or "").strip()
        job_url = str(imported_job_posting.get("url", "") or "").strip()

    system_prompt = (
        "You rewrite imported job descriptions into a clear, recruiter-style reading summary.\n"
        "Stay strictly grounded in the supplied job description text.\n"
        "Do not add facts, requirements, compensation, or company claims that are not present.\n"
        "Return JSON only with this schema: "
        '{"sections":[{"title":"Overview","items":["..."]}]}\n'
        "Use 2 to 4 sections total.\n"
        "Allowed section titles: Overview, What You Will Work On, What They Are Looking For, Good Signals.\n"
        "Each section should contain 2 to 6 short readable bullet items.\n"
        "Avoid legal boilerplate, equal-opportunity statements, and privacy-policy text unless it is central to the role.\n"
        "Preserve concrete technical requirements and scope."
    )
    user_prompt = (
        "Job title: {title}\n"
        "Location: {location}\n"
        "Source: {source}\n"
        "Job URL: {url}\n"
        "Detected hard skills: {hard_skills}\n"
        "Detected soft skills: {soft_skills}\n"
        "Detected experience signal: {experience}\n\n"
        "Job description text:\n{job_text}"
    ).format(
        title=job_description.title or "Unknown",
        location=job_description.location or "Unknown",
        source=job_source or "Unknown",
        url=job_url or "Unknown",
        hard_skills=", ".join(job_description.requirements.hard_skills) or "None",
        soft_skills=", ".join(job_description.requirements.soft_skills) or "None",
        experience=job_description.requirements.experience_requirement or "Not explicit",
        job_text=job_description.cleaned_text,
    )

    try:
        # Schema-strict path: the summary contract has one top-level key
        # (``sections``) but each item carries title + items. Production
        # uses ``run_structured_prompt`` to constrain the shape at
        # generation time; test fakes that only implement
        # ``run_json_prompt`` still work via the legacy branch.
        if hasattr(openai_service, "run_structured_prompt"):
            structured = openai_service.run_structured_prompt(
                system_prompt,
                user_prompt,
                response_model=JDSummaryOutput,
                task_name="jd_summary",
                max_completion_tokens=get_openai_max_completion_tokens_for_task("jd_summary", fallback=1400),
                metadata={
                    "summary_type": "imported_job_description",
                    "job_source": job_source,
                    "estimated_input_chars": str(len(job_description.cleaned_text)),
                },
            )
            payload = structured.model_dump()
        else:
            payload = openai_service.run_json_prompt(
                system_prompt,
                user_prompt,
                expected_keys=["sections"],
                task_name="jd_summary",
                max_completion_tokens=get_openai_max_completion_tokens_for_task("jd_summary", fallback=1400),
                metadata={
                    "summary_type": "imported_job_description",
                    "job_source": job_source,
                    "estimated_input_chars": str(len(job_description.cleaned_text)),
                },
            )
    except AgentExecutionError as exc:
        # Graceful deterministic summary as before. If the cause was a
        # genuine provider OUTAGE (OpenAIUnavailableError ⊂
        # AgentExecutionError), attach a notice so the analysis screen
        # can tell the user — consistent with the résumé/JD parsers and
        # the pipeline. A plain content AgentExecutionError → no notice
        # (outage_notice returns None), silent as before.
        result = {"mode": "deterministic", "sections": deterministic_sections}
        notice = outage_notice(exc)
        if notice:
            result["service_notice"] = notice
        return result

    ai_sections = _normalize_section_payload(payload)
    if not ai_sections:
        return {"mode": "deterministic", "sections": deterministic_sections}

    return {
        "mode": "ai",
        "sections": ai_sections,
        "model": openai_service.get_usage_snapshot().get("last_response_metadata", {}).get("model"),
    }
