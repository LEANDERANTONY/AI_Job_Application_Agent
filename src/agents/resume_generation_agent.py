import re

from src.config import get_openai_max_completion_tokens_for_task
from src.prompts import build_resume_generation_agent_prompt
from src.schemas import (
    CandidateProfile,
    FitAnalysis,
    JobDescription,
    ResumeGenerationAgentOutput,
    ReviewAgentOutput,
    TailoredResumeDraft,
    TailoringAgentOutput,
)

from .common import coerce_string, coerce_string_list, unique_strings


_RESUME_SELF_REFERENCE_RE = re.compile(
    r"\b(i|me|my|mine|myself|he|his|him|himself|she|her|hers|herself|the candidate|this candidate)\b",
    re.IGNORECASE,
)


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
        review_output: ReviewAgentOutput = None,
    ) -> ResumeGenerationAgentOutput:
        if self._openai_service and self._openai_service.is_available():
            prompt = build_resume_generation_agent_prompt(
                candidate_profile,
                job_description,
                fit_analysis,
                tailored_draft,
                tailoring_output,
                review_output,
            )
            payload = self._openai_service.run_json_prompt(
                prompt["system"],
                prompt["user"],
                expected_keys=prompt["expected_keys"],
                max_completion_tokens=get_openai_max_completion_tokens_for_task(
                    "resume_generation"
                ),
                task_name="resume_generation",
                metadata=prompt.get("metadata"),
            )
            output = ResumeGenerationAgentOutput(
                professional_summary=coerce_string(payload.get("professional_summary")),
                highlighted_skills=coerce_string_list(payload.get("highlighted_skills"), limit=8),
                experience_bullets=coerce_string_list(payload.get("experience_bullets"), limit=6),
                section_order=coerce_string_list(payload.get("section_order"), limit=6),
                template_hint="classic_ats",
            )
            if self._contains_self_reference(candidate_profile, output):
                return self._fallback(fit_analysis, tailored_draft, tailoring_output)
            return output
        return self._fallback(fit_analysis, tailored_draft, tailoring_output)

    @staticmethod
    def _contains_self_reference(
        candidate_profile: CandidateProfile,
        resume_output: ResumeGenerationAgentOutput,
    ) -> bool:
        text_blocks = [resume_output.professional_summary, *resume_output.experience_bullets]
        combined_text = " ".join(str(block or "").strip() for block in text_blocks if str(block or "").strip())
        if not combined_text:
            return False
        candidate_name = str(candidate_profile.full_name or "").strip()
        if candidate_name and candidate_name.lower() in combined_text.lower():
            return True
        return _RESUME_SELF_REFERENCE_RE.search(combined_text) is not None

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
