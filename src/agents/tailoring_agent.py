from src.config import get_openai_max_completion_tokens_for_task
from src.prompts import build_tailoring_agent_prompt
from src.schemas import (
    CandidateProfile,
    FitAnalysis,
    JobDescription,
    TailoredResumeDraft,
    TailoringAgentOutput,
)

from .common import coerce_string, coerce_string_list, unique_strings


class TailoringAgent:
    def __init__(self, openai_service=None):
        self._openai_service = openai_service

    def run(
        self,
        candidate_profile: CandidateProfile,
        job_description: JobDescription,
        fit_analysis: FitAnalysis,
        tailored_draft: TailoredResumeDraft,
    ) -> TailoringAgentOutput:
        if self._openai_service and self._openai_service.is_available():
            prompt = build_tailoring_agent_prompt(
                candidate_profile,
                job_description,
                fit_analysis,
                tailored_draft,
            )
            payload = self._openai_service.run_json_prompt(
                prompt["system"],
                prompt["user"],
                expected_keys=prompt["expected_keys"],
                max_completion_tokens=get_openai_max_completion_tokens_for_task("tailoring"),
                task_name="tailoring",
                metadata=prompt.get("metadata"),
            )
            return TailoringAgentOutput(
                professional_summary=coerce_string(payload.get("professional_summary")),
                rewritten_bullets=coerce_string_list(payload.get("rewritten_bullets"), limit=5),
                highlighted_skills=coerce_string_list(
                    payload.get("highlighted_skills"), limit=8
                ),
                cover_letter_themes=coerce_string_list(
                    payload.get("cover_letter_themes"), limit=4
                ),
            )
        return self._fallback(tailored_draft, fit_analysis)

    @staticmethod
    def _fallback(
        tailored_draft: TailoredResumeDraft,
        fit_analysis: FitAnalysis,
    ) -> TailoringAgentOutput:
        """Deterministic fallback when the LLM is unavailable. Reads the
        structured FitAnalysis directly — no FitAgent narration step
        needed.  ``matched_hard_skills`` and ``gaps`` are the same
        signals the previous fallback derived from FitAgentOutput."""
        base_summary = tailored_draft.professional_summary
        rewritten_bullets = unique_strings(tailored_draft.priority_bullets, limit=5)
        highlighted_skills = unique_strings(tailored_draft.highlighted_skills, limit=8)

        cover_letter_themes: list[str] = []
        if fit_analysis.matched_hard_skills:
            cover_letter_themes.append(
                "Lead with alignment on "
                + ", ".join(fit_analysis.matched_hard_skills[:2])
                + "."
            )
        if fit_analysis.gaps:
            cover_letter_themes.append(
                "Acknowledge growth areas while emphasizing grounded adjacent evidence."
            )

        return TailoringAgentOutput(
            professional_summary=base_summary,
            rewritten_bullets=rewritten_bullets,
            highlighted_skills=highlighted_skills,
            cover_letter_themes=unique_strings(cover_letter_themes, limit=4),
        )
