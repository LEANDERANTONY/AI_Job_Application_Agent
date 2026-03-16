from src.config import get_openai_max_completion_tokens_for_task
from src.prompts import build_strategy_agent_prompt
from src.schemas import (
    CandidateProfile,
    FitAnalysis,
    FitAgentOutput,
    JobDescription,
    StrategyAgentOutput,
    TailoringAgentOutput,
)

from .common import coerce_string, coerce_string_list, unique_strings


class StrategyAgent:
    def __init__(self, openai_service=None):
        self._openai_service = openai_service

    def run(
        self,
        candidate_profile: CandidateProfile,
        job_description: JobDescription,
        fit_analysis: FitAnalysis,
        fit_output: FitAgentOutput,
        tailoring_output: TailoringAgentOutput,
    ) -> StrategyAgentOutput:
        if self._openai_service and self._openai_service.is_available():
            prompt = build_strategy_agent_prompt(
                candidate_profile,
                job_description,
                fit_analysis,
                fit_output,
                tailoring_output,
            )
            payload = self._openai_service.run_json_prompt(
                prompt["system"],
                prompt["user"],
                expected_keys=prompt["expected_keys"],
                max_completion_tokens=get_openai_max_completion_tokens_for_task("strategy"),
                task_name="strategy",
                metadata=prompt.get("metadata"),
            )
            return StrategyAgentOutput(
                recruiter_positioning=coerce_string(payload.get("recruiter_positioning")),
                cover_letter_talking_points=coerce_string_list(
                    payload.get("cover_letter_talking_points"), limit=4
                ),
                portfolio_project_emphasis=coerce_string_list(
                    payload.get("portfolio_project_emphasis"), limit=4
                ),
            )
        return self._fallback(candidate_profile, job_description, fit_analysis, fit_output)

    @staticmethod
    def _fallback(
        candidate_profile: CandidateProfile,
        job_description: JobDescription,
        fit_analysis: FitAnalysis,
        fit_output: FitAgentOutput,
    ) -> StrategyAgentOutput:
        recruiter_positioning_parts = []
        if job_description.title:
            recruiter_positioning_parts.append(
                "Position the candidate as a grounded fit for {role}".format(
                    role=job_description.title
                )
            )
        if fit_output.top_matches:
            recruiter_positioning_parts.append(
                "Lead with verified strengths in " + ", ".join(fit_output.top_matches[:3]) + "."
            )
        if fit_analysis.missing_hard_skills:
            recruiter_positioning_parts.append(
                "Acknowledge growth areas conservatively instead of overstating direct experience."
            )

        cover_letter_talking_points = []
        if candidate_profile.experience:
            cover_letter_talking_points.append(
                "Open with recent delivery evidence that matches the role's highest-priority needs."
            )
        if fit_output.top_matches:
            cover_letter_talking_points.append(
                "Tie concrete examples to " + ", ".join(fit_output.top_matches[:2]) + "."
            )
        if fit_output.key_gaps:
            cover_letter_talking_points.append(
                "Address gaps like {gaps} with an honest learning trajectory and adjacent evidence.".format(
                    gaps=", ".join(fit_output.key_gaps[:2])
                )
            )

        portfolio_project_emphasis = []
        if candidate_profile.experience:
            for experience in candidate_profile.experience[:2]:
                if experience.title or experience.organization:
                    portfolio_project_emphasis.append(
                        "Emphasize work from {title} at {organization} that proves relevant delivery scope.".format(
                            title=experience.title or "recent experience",
                            organization=experience.organization or "recent organization",
                        )
                    )
        if fit_output.top_matches:
            portfolio_project_emphasis.append(
                "Highlight projects demonstrating " + ", ".join(fit_output.top_matches[:3]) + "."
            )

        return StrategyAgentOutput(
            recruiter_positioning=" ".join(unique_strings(recruiter_positioning_parts, limit=3)),
            cover_letter_talking_points=unique_strings(cover_letter_talking_points, limit=4),
            portfolio_project_emphasis=unique_strings(portfolio_project_emphasis, limit=4),
        )