from src.config import get_openai_max_completion_tokens_for_task
from src.prompts import build_job_agent_prompt
from src.schemas import JobAgentOutput, JobDescription

from .common import coerce_string, coerce_string_list, unique_strings


class JobAgent:
    def __init__(self, openai_service=None):
        self._openai_service = openai_service

    def run(self, job_description: JobDescription) -> JobAgentOutput:
        if self._openai_service and self._openai_service.is_available():
            prompt = build_job_agent_prompt(job_description)
            payload = self._openai_service.run_json_prompt(
                prompt["system"],
                prompt["user"],
                expected_keys=prompt["expected_keys"],
                max_completion_tokens=get_openai_max_completion_tokens_for_task("job"),
                task_name="job",
            )
            return JobAgentOutput(
                requirement_summary=coerce_string(payload.get("requirement_summary")),
                priority_skills=coerce_string_list(payload.get("priority_skills"), limit=6),
                must_have_themes=coerce_string_list(payload.get("must_have_themes"), limit=4),
                messaging_guidance=coerce_string_list(
                    payload.get("messaging_guidance"), limit=4
                ),
            )
        return self._fallback(job_description)

    @staticmethod
    def _fallback(job_description: JobDescription) -> JobAgentOutput:
        requirements = job_description.requirements
        summary_parts = [
            "{title} role".format(title=job_description.title or "Target"),
        ]
        if requirements.hard_skills:
            summary_parts.append(
                "prioritizing " + ", ".join(requirements.hard_skills[:4])
            )
        if requirements.experience_requirement:
            summary_parts.append("with " + requirements.experience_requirement)

        must_have_themes = requirements.must_haves[:3]
        if not must_have_themes and requirements.hard_skills:
            must_have_themes = [
                "Demonstrate evidence for " + ", ".join(requirements.hard_skills[:3]) + "."
            ]

        messaging_guidance = []
        if requirements.hard_skills:
            messaging_guidance.append(
                "Mirror the JD's core technical vocabulary: "
                + ", ".join(requirements.hard_skills[:4])
                + "."
            )
        if requirements.soft_skills:
            messaging_guidance.append(
                "Support soft-skill language with outcomes: "
                + ", ".join(requirements.soft_skills[:3])
                + "."
            )
        if job_description.location:
            messaging_guidance.append(
                "Keep location alignment visible for " + job_description.location + "."
            )

        return JobAgentOutput(
            requirement_summary=" ".join(unique_strings(summary_parts, limit=3)) + ".",
            priority_skills=unique_strings(requirements.hard_skills[:6]),
            must_have_themes=unique_strings(must_have_themes, limit=4),
            messaging_guidance=unique_strings(messaging_guidance, limit=4),
        )
