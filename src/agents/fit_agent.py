from src.config import get_openai_max_completion_tokens_for_task
from src.prompts import build_fit_agent_prompt
from src.schemas import (
    CandidateProfile,
    FitAnalysis,
    FitAgentOutput,
    JobAgentOutput,
    JobDescription,
    ProfileAgentOutput,
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
        profile_output: ProfileAgentOutput,
        job_output: JobAgentOutput,
    ) -> FitAgentOutput:
        if self._openai_service and self._openai_service.is_available():
            prompt = build_fit_agent_prompt(
                candidate_profile,
                job_description,
                fit_analysis,
                profile_output,
                job_output,
            )
            payload = self._openai_service.run_json_prompt(
                prompt["system"],
                prompt["user"],
                expected_keys=prompt["expected_keys"],
                max_completion_tokens=get_openai_max_completion_tokens_for_task("fit"),
                task_name="fit",
            )
            return FitAgentOutput(
                fit_summary=coerce_string(payload.get("fit_summary")),
                top_matches=coerce_string_list(payload.get("top_matches"), limit=4),
                key_gaps=coerce_string_list(payload.get("key_gaps"), limit=4),
                interview_themes=coerce_string_list(payload.get("interview_themes"), limit=4),
            )
        return self._fallback(fit_analysis, profile_output, job_output)

    @staticmethod
    def _fallback(
        fit_analysis: FitAnalysis,
        profile_output: ProfileAgentOutput,
        job_output: JobAgentOutput,
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
            fit_analysis.strengths + profile_output.evidence_highlights + job_output.priority_skills,
            limit=4,
        )
        key_gaps = unique_strings(
            fit_analysis.gaps + fit_analysis.missing_hard_skills + profile_output.cautions,
            limit=4,
        )
        interview_themes = []
        if fit_analysis.matched_hard_skills:
            interview_themes.append(
                "Prepare concrete stories around " + ", ".join(fit_analysis.matched_hard_skills[:3]) + "."
            )
        if fit_analysis.missing_hard_skills:
            interview_themes.append(
                "Frame a credible upskilling plan for " + ", ".join(fit_analysis.missing_hard_skills[:3]) + "."
            )
        if not interview_themes:
            interview_themes.append("Prepare outcome-focused examples from your strongest recent work.")

        return FitAgentOutput(
            fit_summary=fit_summary,
            top_matches=top_matches,
            key_gaps=key_gaps,
            interview_themes=unique_strings(interview_themes, limit=4),
        )
