from src.config import get_openai_max_completion_tokens_for_task
from src.prompts import build_review_agent_prompt
from src.schemas import (
    CandidateProfile,
    FitAnalysis,
    JobDescription,
    ReviewAgentOutput,
    TailoredResumeDraft,
    TailoringAgentOutput,
)
from src.schemas_llm_outputs import ReviewOutput, TailoringOutput
from src.services.profile_service import build_candidate_context_text

from .common import coerce_bool, coerce_string, coerce_string_list, unique_strings


class ReviewAgent:
    def __init__(
        self, openai_service=None, *, model_override=None, reasoning_override=None
    ):
        self._openai_service = openai_service
        # See TailoringAgent for the rationale. When premium=True and
        # the user's tier supports it (Pro / Business), the
        # orchestrator passes gpt-5.5 here; otherwise None and the
        # default `OPENAI_MODEL_ROUTING["review"]` (gpt-5.4) wins.
        self._model_override = model_override
        # ADR-028 Decision 2: a premium run upgrades review's MODEL to
        # gpt-5.5 (above) AND its reasoning effort to "high" — the A/B
        # showed gpt-5.5 only beats free gpt-5.4 at high reasoning.
        # None on standard/free runs → routed default ("medium").
        self._reasoning_override = reasoning_override

    def run(
        self,
        candidate_profile: CandidateProfile,
        job_description: JobDescription,
        fit_analysis: FitAnalysis,
        tailored_draft: TailoredResumeDraft,
        tailoring_output: TailoringAgentOutput,
    ) -> ReviewAgentOutput:
        if self._openai_service and self._openai_service.is_available():
            prompt = build_review_agent_prompt(
                candidate_profile,
                job_description,
                fit_analysis,
                tailored_draft,
                tailoring_output,
            )
            # Schema-strict path: ``corrected_tailoring`` arrives as a
            # nested Pydantic object (or None) — we no longer have to
            # check ``isinstance(payload, dict)`` because the schema
            # constrains it at generation time. The legacy
            # ``run_json_prompt`` branch is kept for test fakes that
            # haven't been migrated.
            if hasattr(self._openai_service, "run_structured_prompt"):
                structured = self._openai_service.run_structured_prompt(
                    prompt["system"],
                    prompt["user"],
                    response_model=ReviewOutput,
                    max_completion_tokens=get_openai_max_completion_tokens_for_task("review"),
                    task_name="review",
                    model=self._model_override,
                    reasoning_effort=self._reasoning_override,
                    metadata=prompt.get("metadata"),
                )
            else:
                payload = self._openai_service.run_json_prompt(
                    prompt["system"],
                    prompt["user"],
                    expected_keys=prompt["expected_keys"],
                    max_completion_tokens=get_openai_max_completion_tokens_for_task("review"),
                    task_name="review",
                    model=self._model_override,
                    reasoning_effort=self._reasoning_override,
                    metadata=prompt.get("metadata"),
                )
                structured = ReviewOutput.model_validate(payload)
            review_output = ReviewAgentOutput(
                approved=coerce_bool(structured.approved),
                grounding_issues=coerce_string_list(
                    structured.grounding_issues, limit=4
                ),
                unresolved_issues=coerce_string_list(
                    structured.unresolved_issues, limit=4
                ),
                revision_requests=coerce_string_list(
                    structured.revision_requests, limit=4
                ),
                final_notes=coerce_string_list(structured.final_notes, limit=3),
                corrected_tailoring=self._coerce_tailoring_output(structured.corrected_tailoring),
            )
            return self._normalize_review_output(review_output)
        return self._fallback(candidate_profile, fit_analysis, tailoring_output)

    @staticmethod
    def _normalize_review_output(review_output: ReviewAgentOutput) -> ReviewAgentOutput:
        unresolved = unique_strings(review_output.unresolved_issues, limit=4)
        corrected_anything = bool(review_output.corrected_tailoring)
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
        )

    @staticmethod
    def _coerce_tailoring_output(structured):
        """Convert the Pydantic ``TailoringOutput`` (or None) into the
        downstream ``TailoringAgentOutput`` dataclass.

        Accepts a plain dict too so existing tests that pass a raw
        payload (legacy run_json_prompt return shape) keep working
        during the migration. The dataclass-side post-processing
        (``coerce_string_list`` etc.) preserves the previous truncation
        behavior.
        """
        if structured is None:
            return None
        if isinstance(structured, TailoringOutput):
            return TailoringAgentOutput(
                professional_summary=coerce_string(structured.professional_summary),
                rewritten_bullets=coerce_string_list(structured.rewritten_bullets, limit=5),
                highlighted_skills=coerce_string_list(structured.highlighted_skills, limit=8),
                cover_letter_themes=coerce_string_list(structured.cover_letter_themes, limit=4),
            )
        if isinstance(structured, dict):
            return TailoringAgentOutput(
                professional_summary=coerce_string(structured.get("professional_summary")),
                rewritten_bullets=coerce_string_list(structured.get("rewritten_bullets"), limit=5),
                highlighted_skills=coerce_string_list(structured.get("highlighted_skills"), limit=8),
                cover_letter_themes=coerce_string_list(structured.get("cover_letter_themes"), limit=4),
            )
        return None

    @staticmethod
    def _fallback(
        candidate_profile: CandidateProfile,
        fit_analysis: FitAnalysis,
        tailoring_output: TailoringAgentOutput,
    ) -> ReviewAgentOutput:
        candidate_text = build_candidate_context_text(candidate_profile).lower()
        output_text = " ".join(
            [
                tailoring_output.professional_summary,
                " ".join(tailoring_output.rewritten_bullets),
                " ".join(tailoring_output.cover_letter_themes),
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
        )
