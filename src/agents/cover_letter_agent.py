import re

from src.config import get_openai_max_completion_tokens_for_task
from src.prompts import build_cover_letter_agent_prompt
from src.schemas import (
    CandidateProfile,
    CoverLetterAgentOutput,
    FitAnalysis,
    JobDescription,
    ResumeGenerationAgentOutput,
    ReviewAgentOutput,
    TailoredResumeDraft,
    TailoringAgentOutput,
)

from .common import coerce_string, coerce_string_list, unique_strings


_THIRD_PERSON_SELF_REFERENCE_RE = re.compile(r"\b(he|his|him|she|her)\b", re.IGNORECASE)
_CANDIDATE_LABEL_RE = re.compile(r"\b(the candidate|this candidate)\b", re.IGNORECASE)


class CoverLetterAgent:
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
        resume_generation_output: ResumeGenerationAgentOutput = None,
    ) -> CoverLetterAgentOutput:
        if self._openai_service and self._openai_service.is_available():
            prompt = build_cover_letter_agent_prompt(
                candidate_profile,
                job_description,
                fit_analysis,
                tailored_draft,
                tailoring_output,
                review_output,
                resume_generation_output,
            )
            payload = self._openai_service.run_json_prompt(
                prompt["system"],
                prompt["user"],
                expected_keys=prompt["expected_keys"],
                max_completion_tokens=get_openai_max_completion_tokens_for_task("cover_letter"),
                task_name="cover_letter",
                metadata=prompt.get("metadata"),
            )
            output = CoverLetterAgentOutput(
                greeting=coerce_string(payload.get("greeting"), default="Dear Hiring Team"),
                opening_paragraph=coerce_string(payload.get("opening_paragraph")),
                body_paragraphs=coerce_string_list(payload.get("body_paragraphs"), limit=3),
                closing_paragraph=coerce_string(payload.get("closing_paragraph")),
                signoff=coerce_string(payload.get("signoff"), default="Sincerely"),
                signature_name=coerce_string(payload.get("signature_name"), default=candidate_profile.full_name or "Candidate"),
            )
            if self._contains_third_person_self_reference(candidate_profile, output):
                return self._fallback(
                    candidate_profile,
                    job_description,
                    fit_analysis,
                    tailored_draft,
                    tailoring_output,
                    resume_generation_output,
                )
            return output
        return self._fallback(
            candidate_profile,
            job_description,
            fit_analysis,
            tailored_draft,
            tailoring_output,
            resume_generation_output,
        )

    @staticmethod
    def _contains_third_person_self_reference(
        candidate_profile: CandidateProfile,
        cover_letter_output: CoverLetterAgentOutput,
    ) -> bool:
        text_blocks = [
            cover_letter_output.opening_paragraph,
            *cover_letter_output.body_paragraphs,
            cover_letter_output.closing_paragraph,
        ]
        combined_text = " ".join(str(block or "").strip() for block in text_blocks if str(block or "").strip())
        if not combined_text:
            return False
        candidate_name = str(candidate_profile.full_name or "").strip()
        if candidate_name and candidate_name.lower() in combined_text.lower():
            return True
        if _CANDIDATE_LABEL_RE.search(combined_text):
            return True
        return _THIRD_PERSON_SELF_REFERENCE_RE.search(combined_text) is not None

    @staticmethod
    def _fallback(
        candidate_profile: CandidateProfile,
        job_description: JobDescription,
        fit_analysis: FitAnalysis,
        tailored_draft: TailoredResumeDraft,
        tailoring_output: TailoringAgentOutput,
        resume_generation_output: ResumeGenerationAgentOutput = None,
    ) -> CoverLetterAgentOutput:
        role = job_description.title or tailored_draft.target_role or "the role"
        summary = (
            resume_generation_output.professional_summary
            if resume_generation_output and resume_generation_output.professional_summary
            else tailoring_output.professional_summary or tailored_draft.professional_summary
        )
        highlighted_skills = unique_strings(
            (resume_generation_output.highlighted_skills if resume_generation_output else [])
            + tailoring_output.highlighted_skills
            + tailored_draft.highlighted_skills
            + fit_analysis.matched_hard_skills,
            limit=4,
        )
        talking_points = unique_strings(
            tailoring_output.cover_letter_themes,
            limit=3,
        )
        opening = (
            "I am excited to apply for the {role} role. {summary} My background aligns well with the role's emphasis on {skills}."
        ).format(
            role=role,
            summary=summary,
            skills=", ".join(highlighted_skills) or "relevant experience",
        ).strip()
        body_paragraphs = []
        if candidate_profile.experience:
            latest_role = candidate_profile.experience[0]
            body_paragraphs.append(
                "Most recently, I worked as {title} at {organization}, where I built evidence-backed experience that maps to the priorities in this job description.".format(
                    title=latest_role.title or "a contributor",
                    organization=latest_role.organization or "a recent team",
                )
            )
        if fit_analysis.experience_signal:
            body_paragraphs.append(fit_analysis.experience_signal)
        body_paragraphs.extend(talking_points)
        return CoverLetterAgentOutput(
            greeting="Dear Hiring Team",
            opening_paragraph=opening,
            body_paragraphs=unique_strings(body_paragraphs, limit=3),
            closing_paragraph=(
                "I would welcome the opportunity to discuss how my experience can support your team's priorities for {role}. Thank you for your time and consideration."
            ).format(role=role),
            signoff="Sincerely",
            signature_name=candidate_profile.full_name or "Candidate",
        )
