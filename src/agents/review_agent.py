from src.prompts import build_review_agent_prompt
from src.schemas import (
    CandidateProfile,
    FitAnalysis,
    JobDescription,
    ReviewAgentOutput,
    StrategyAgentOutput,
    TailoredResumeDraft,
    TailoringAgentOutput,
)
from src.services.profile_service import build_candidate_context_text

from .common import coerce_bool, coerce_string_list, unique_strings


class ReviewAgent:
    def __init__(self, openai_service=None):
        self._openai_service = openai_service

    def run(
        self,
        candidate_profile: CandidateProfile,
        job_description: JobDescription,
        fit_analysis: FitAnalysis,
        tailored_draft: TailoredResumeDraft,
        tailoring_output: TailoringAgentOutput,
        strategy_output: StrategyAgentOutput = None,
    ) -> ReviewAgentOutput:
        if self._openai_service and self._openai_service.is_available():
            prompt = build_review_agent_prompt(
                candidate_profile,
                job_description,
                fit_analysis,
                tailored_draft,
                tailoring_output,
                strategy_output,
            )
            payload = self._openai_service.run_json_prompt(
                prompt["system"],
                prompt["user"],
                expected_keys=prompt["expected_keys"],
                task_name="review",
            )
            return ReviewAgentOutput(
                approved=coerce_bool(payload.get("approved")),
                grounding_issues=coerce_string_list(
                    payload.get("grounding_issues"), limit=4
                ),
                revision_requests=coerce_string_list(
                    payload.get("revision_requests"), limit=4
                ),
                final_notes=coerce_string_list(payload.get("final_notes"), limit=3),
            )
        return self._fallback(candidate_profile, fit_analysis, tailoring_output, strategy_output)

    @staticmethod
    def _fallback(
        candidate_profile: CandidateProfile,
        fit_analysis: FitAnalysis,
        tailoring_output: TailoringAgentOutput,
        strategy_output: StrategyAgentOutput = None,
    ) -> ReviewAgentOutput:
        candidate_text = build_candidate_context_text(candidate_profile).lower()
        output_text = " ".join(
            [
                tailoring_output.professional_summary,
                " ".join(tailoring_output.rewritten_bullets),
                " ".join(tailoring_output.cover_letter_themes),
                strategy_output.recruiter_positioning if strategy_output else "",
                " ".join(strategy_output.cover_letter_talking_points) if strategy_output else "",
                " ".join(strategy_output.interview_preparation_themes) if strategy_output else "",
                " ".join(strategy_output.portfolio_project_emphasis) if strategy_output else "",
            ]
        ).lower()
        grounding_issues = []

        for skill in fit_analysis.missing_hard_skills:
            if skill.lower() in output_text and skill.lower() not in candidate_text:
                grounding_issues.append(
                    "Output references {skill} without clear evidence in the source profile.".format(
                        skill=skill
                    )
                )

        revision_requests = []
        if grounding_issues:
            revision_requests.append(
                "Replace unsupported skill references with transferable, evidence-backed wording."
            )
        if not tailoring_output.rewritten_bullets:
            revision_requests.append("Add stronger tailored bullets before exporting the package.")

        final_notes = []
        if not grounding_issues:
            final_notes.append("No obvious unsupported claims were detected in the fallback review.")
        if fit_analysis.missing_hard_skills:
            final_notes.append(
                "Keep missing-skill language framed as learning trajectory, not as completed experience."
            )

        return ReviewAgentOutput(
            approved=not grounding_issues,
            grounding_issues=unique_strings(grounding_issues, limit=4),
            revision_requests=unique_strings(revision_requests, limit=4),
            final_notes=unique_strings(final_notes, limit=3),
        )
