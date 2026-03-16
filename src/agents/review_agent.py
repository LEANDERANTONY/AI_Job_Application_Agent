from src.config import get_openai_max_completion_tokens_for_task
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

from .common import coerce_bool, coerce_string, coerce_string_list, unique_strings


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
                max_completion_tokens=get_openai_max_completion_tokens_for_task("review"),
                task_name="review",
                metadata=prompt.get("metadata"),
            )
            review_output = ReviewAgentOutput(
                approved=coerce_bool(payload.get("approved")),
                grounding_issues=coerce_string_list(
                    payload.get("grounding_issues"), limit=4
                ),
                unresolved_issues=coerce_string_list(
                    payload.get("unresolved_issues"), limit=4
                ),
                revision_requests=coerce_string_list(
                    payload.get("revision_requests"), limit=4
                ),
                final_notes=coerce_string_list(payload.get("final_notes"), limit=3),
                corrected_tailoring=self._coerce_tailoring_output(payload.get("corrected_tailoring")),
                corrected_strategy=self._coerce_strategy_output(payload.get("corrected_strategy")),
            )
            return self._normalize_review_output(review_output)
        return self._fallback(candidate_profile, fit_analysis, tailoring_output, strategy_output)

    @staticmethod
    def _normalize_review_output(review_output: ReviewAgentOutput) -> ReviewAgentOutput:
        unresolved = unique_strings(review_output.unresolved_issues, limit=4)
        corrected_anything = bool(
            review_output.corrected_tailoring or review_output.corrected_strategy
        )
        approved = review_output.approved
        if unresolved:
            approved = False
        elif corrected_anything:
            approved = True
        return ReviewAgentOutput(
            approved=approved,
            grounding_issues=unique_strings(review_output.grounding_issues, limit=4),
            unresolved_issues=unresolved,
            revision_requests=unique_strings(review_output.revision_requests, limit=4),
            final_notes=unique_strings(review_output.final_notes, limit=3),
            corrected_tailoring=review_output.corrected_tailoring,
            corrected_strategy=review_output.corrected_strategy,
        )

    @staticmethod
    def _coerce_tailoring_output(payload):
        if not isinstance(payload, dict):
            return None
        return TailoringAgentOutput(
            professional_summary=coerce_string(payload.get("professional_summary")),
            rewritten_bullets=coerce_string_list(payload.get("rewritten_bullets"), limit=5),
            highlighted_skills=coerce_string_list(payload.get("highlighted_skills"), limit=8),
            cover_letter_themes=coerce_string_list(payload.get("cover_letter_themes"), limit=4),
        )

    @staticmethod
    def _coerce_strategy_output(payload):
        if not isinstance(payload, dict):
            return None
        return StrategyAgentOutput(
            recruiter_positioning=coerce_string(payload.get("recruiter_positioning")),
            cover_letter_talking_points=coerce_string_list(payload.get("cover_letter_talking_points"), limit=4),
            portfolio_project_emphasis=coerce_string_list(payload.get("portfolio_project_emphasis"), limit=4),
        )

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
            unresolved_issues=unique_strings(grounding_issues, limit=4),
            revision_requests=unique_strings(revision_requests, limit=4),
            final_notes=unique_strings(final_notes, limit=3),
            corrected_tailoring=tailoring_output,
            corrected_strategy=strategy_output,
        )
