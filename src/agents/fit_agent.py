from src.config import get_openai_max_completion_tokens_for_task
from src.prompts import build_fit_agent_prompt
from src.schemas import (
    CandidateProfile,
    FitAnalysis,
    FitAgentOutput,
    JobDescription,
)

from .common import coerce_string, coerce_string_list, unique_strings


class FitAgent:
    def __init__(self, openai_service=None):
        self._openai_service = openai_service

    def run(
        self,
        candidate_profile: CandidateProfile,
        job_description: JobDescription,
        fit_analysis: FitAnalysis,
    ) -> FitAgentOutput:
        if self._openai_service and self._openai_service.is_available():
            prompt = build_fit_agent_prompt(
                candidate_profile,
                job_description,
                fit_analysis,
            )
            payload = self._openai_service.run_json_prompt(
                prompt["system"],
                prompt["user"],
                expected_keys=prompt["expected_keys"],
                max_completion_tokens=get_openai_max_completion_tokens_for_task("fit"),
                task_name="fit",
                metadata=prompt.get("metadata"),
            )
            return FitAgentOutput(
                fit_summary=coerce_string(payload.get("fit_summary")),
                top_matches=coerce_string_list(payload.get("top_matches"), limit=4),
                key_gaps=coerce_string_list(payload.get("key_gaps"), limit=4),
            )
        return self._fallback(fit_analysis, candidate_profile, job_description)

    @staticmethod
    def _fallback(
        fit_analysis: FitAnalysis,
        candidate_profile: CandidateProfile,
        job_description: JobDescription,
    ) -> FitAgentOutput:
        fit_summary = (
            "{label} for {role} with a score of {score}/100. {experience}".format(
                label=fit_analysis.readiness_label,
                role=fit_analysis.target_role or "the target role",
                score=fit_analysis.overall_score,
                experience=fit_analysis.experience_signal,
            )
        )
        top_matches = unique_strings(
            fit_analysis.strengths + fit_analysis.matched_hard_skills + candidate_profile.skills,
            limit=4,
        )
        key_gaps = unique_strings(
            fit_analysis.gaps + fit_analysis.missing_hard_skills + fit_analysis.missing_soft_skills,
            limit=4,
        )

        return FitAgentOutput(
            fit_summary=fit_summary,
            top_matches=top_matches,
            key_gaps=key_gaps,
        )
