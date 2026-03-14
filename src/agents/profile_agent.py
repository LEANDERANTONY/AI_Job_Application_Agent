from src.prompts import build_profile_agent_prompt
from src.schemas import CandidateProfile, ProfileAgentOutput

from .common import coerce_string, coerce_string_list, unique_strings


class ProfileAgent:
    def __init__(self, openai_service=None):
        self._openai_service = openai_service

    def run(self, candidate_profile: CandidateProfile) -> ProfileAgentOutput:
        if self._openai_service and self._openai_service.is_available():
            prompt = build_profile_agent_prompt(candidate_profile)
            payload = self._openai_service.run_json_prompt(
                prompt["system"],
                prompt["user"],
                expected_keys=prompt["expected_keys"],
                task_name="profile",
            )
            return ProfileAgentOutput(
                positioning_headline=coerce_string(payload.get("positioning_headline")),
                evidence_highlights=coerce_string_list(
                    payload.get("evidence_highlights"), limit=4
                ),
                strengths=coerce_string_list(payload.get("strengths"), limit=4),
                cautions=coerce_string_list(payload.get("cautions"), limit=3),
            )
        return self._fallback(candidate_profile)

    @staticmethod
    def _fallback(candidate_profile: CandidateProfile) -> ProfileAgentOutput:
        top_skills = candidate_profile.skills[:4]
        headline_parts = []
        if candidate_profile.full_name:
            headline_parts.append("Candidate profile for " + candidate_profile.full_name)
        else:
            headline_parts.append("Candidate profile ready for tailoring")
        if top_skills:
            headline_parts.append("Skills: " + ", ".join(top_skills))

        evidence_highlights = list(candidate_profile.source_signals[:3])
        for experience in candidate_profile.experience[:2]:
            if experience.title or experience.organization:
                evidence_highlights.append(
                    "{title} at {organization}".format(
                        title=experience.title or "Experience",
                        organization=experience.organization or "recent organization",
                    )
                )

        strengths = []
        if top_skills:
            strengths.append("Reusable skills detected: " + ", ".join(top_skills) + ".")
        if candidate_profile.experience:
            strengths.append("Structured experience is available for grounded tailoring.")
        if candidate_profile.education:
            strengths.append("Education details are available for application packaging.")

        cautions = []
        if not candidate_profile.full_name:
            cautions.append("Candidate name was not inferred from the current inputs.")
        if not candidate_profile.experience:
            cautions.append("Experience evidence is limited in the current resume input.")

        return ProfileAgentOutput(
            positioning_headline=" | ".join(unique_strings(headline_parts, limit=2)),
            evidence_highlights=unique_strings(evidence_highlights, limit=4),
            strengths=unique_strings(strengths, limit=4),
            cautions=unique_strings(cautions, limit=3),
        )
