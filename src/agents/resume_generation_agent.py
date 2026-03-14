from src.prompts import build_resume_generation_agent_prompt
from src.schemas import (
    CandidateProfile,
    FitAnalysis,
    JobDescription,
    ResumeGenerationAgentOutput,
    ReviewAgentOutput,
    StrategyAgentOutput,
    TailoredResumeDraft,
    TailoringAgentOutput,
)

from .common import coerce_string, coerce_string_list, unique_strings


class ResumeGenerationAgent:
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
        review_output: ReviewAgentOutput = None,
    ) -> ResumeGenerationAgentOutput:
        if self._openai_service and self._openai_service.is_available():
            prompt = build_resume_generation_agent_prompt(
                candidate_profile,
                job_description,
                fit_analysis,
                tailored_draft,
                tailoring_output,
                strategy_output,
                review_output,
            )
            payload = self._openai_service.run_json_prompt(
                prompt["system"],
                prompt["user"],
                expected_keys=prompt["expected_keys"],
                task_name="resume_generation",
            )
            return ResumeGenerationAgentOutput(
                professional_summary=coerce_string(payload.get("professional_summary")),
                highlighted_skills=coerce_string_list(payload.get("highlighted_skills"), limit=8),
                experience_bullets=coerce_string_list(payload.get("experience_bullets"), limit=6),
                section_order=coerce_string_list(payload.get("section_order"), limit=6),
                template_hint=coerce_string(payload.get("template_hint"), default="classic_ats"),
            )
        return self._fallback(fit_analysis, tailored_draft, tailoring_output)

    @staticmethod
    def _fallback(
        fit_analysis: FitAnalysis,
        tailored_draft: TailoredResumeDraft,
        tailoring_output: TailoringAgentOutput,
    ) -> ResumeGenerationAgentOutput:
        section_order = ["Professional Summary", "Core Skills", "Professional Experience", "Education"]
        return ResumeGenerationAgentOutput(
            professional_summary=tailoring_output.professional_summary or tailored_draft.professional_summary,
            highlighted_skills=unique_strings(
                tailoring_output.highlighted_skills + tailored_draft.highlighted_skills + fit_analysis.matched_hard_skills,
                limit=8,
            ),
            experience_bullets=unique_strings(
                tailoring_output.rewritten_bullets + tailored_draft.priority_bullets,
                limit=6,
            ),
            section_order=section_order,
            template_hint="classic_ats",
        )