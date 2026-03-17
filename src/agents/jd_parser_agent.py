from src.config import get_openai_max_completion_tokens_for_task
from src.prompts import build_jd_parser_agent_prompt
from src.schemas import JDParserAgentOutput, JobDescription, JobRequirements

from .common import coerce_string, coerce_string_list, unique_strings


class JDParserAgent:
    def __init__(self, openai_service=None):
        self._openai_service = openai_service

    def run(self, job_description: JobDescription) -> JobDescription:
        if self._openai_service and self._openai_service.is_available():
            prompt = build_jd_parser_agent_prompt(job_description)
            payload = self._openai_service.run_json_prompt(
                prompt["system"],
                prompt["user"],
                expected_keys=prompt["expected_keys"],
                max_completion_tokens=get_openai_max_completion_tokens_for_task("jd_parser"),
                task_name="jd_parser",
                metadata=prompt.get("metadata"),
            )
            verified = JDParserAgentOutput(
                title=coerce_string(payload.get("title"), default=job_description.title),
                location=coerce_string(payload.get("location"), default=job_description.location or ""),
                hard_skills=coerce_string_list(payload.get("hard_skills")),
                soft_skills=coerce_string_list(payload.get("soft_skills")),
                experience_requirement=coerce_string(
                    payload.get("experience_requirement"),
                    default=job_description.requirements.experience_requirement or "",
                ),
                must_haves=coerce_string_list(payload.get("must_haves")),
                nice_to_haves=coerce_string_list(payload.get("nice_to_haves")),
                verification_notes=coerce_string_list(payload.get("verification_notes"), limit=4),
            )
            return JobDescription(
                title=verified.title or job_description.title,
                raw_text=job_description.raw_text,
                cleaned_text=job_description.cleaned_text,
                location=verified.location or job_description.location,
                requirements=JobRequirements(
                    hard_skills=verified.hard_skills or job_description.requirements.hard_skills,
                    soft_skills=verified.soft_skills or job_description.requirements.soft_skills,
                    experience_requirement=verified.experience_requirement or job_description.requirements.experience_requirement,
                    must_haves=verified.must_haves or job_description.requirements.must_haves,
                    nice_to_haves=verified.nice_to_haves or job_description.requirements.nice_to_haves,
                ),
                parsing_notes=unique_strings(
                    list(job_description.parsing_notes)
                    + (["JD parser agent reviewed and corrected the structured requirements."] if verified.verification_notes else [])
                    + verified.verification_notes,
                    limit=12,
                ),
            )
        return job_description