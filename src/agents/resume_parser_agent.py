from src.config import get_openai_max_completion_tokens_for_task
from src.prompts import build_resume_parser_agent_prompt
from src.schemas import CandidateProfile, EducationEntry, ResumeDocument, ResumeParserAgentOutput, WorkExperience

from .common import coerce_string, coerce_string_list, unique_strings


def _coerce_work_experience_list(value):
    if not isinstance(value, list):
        return []
    entries = []
    for item in value:
        if not isinstance(item, dict):
            continue
        entries.append(
            WorkExperience(
                title=coerce_string(item.get("title")),
                organization=coerce_string(item.get("organization")),
                location=coerce_string(item.get("location")),
                description=coerce_string(item.get("description")),
                start=coerce_string(item.get("start")) or None,
                end=coerce_string(item.get("end")) or None,
            )
        )
    return [entry for entry in entries if entry.title or entry.organization or entry.description]


def _coerce_education_list(value):
    if not isinstance(value, list):
        return []
    entries = []
    for item in value:
        if not isinstance(item, dict):
            continue
        entries.append(
            EducationEntry(
                institution=coerce_string(item.get("institution")),
                degree=coerce_string(item.get("degree")),
                field_of_study=coerce_string(item.get("field_of_study")),
                start=coerce_string(item.get("start")),
                end=coerce_string(item.get("end")),
            )
        )
    return [entry for entry in entries if entry.institution or entry.degree]


class ResumeParserAgent:
    def __init__(self, openai_service=None):
        self._openai_service = openai_service

    def run(
        self,
        resume_document: ResumeDocument,
        candidate_profile: CandidateProfile,
    ) -> CandidateProfile:
        if self._openai_service and self._openai_service.is_available():
            prompt = build_resume_parser_agent_prompt(resume_document, candidate_profile)
            payload = self._openai_service.run_json_prompt(
                prompt["system"],
                prompt["user"],
                expected_keys=prompt["expected_keys"],
                max_completion_tokens=get_openai_max_completion_tokens_for_task("resume_parser"),
                task_name="resume_parser",
                metadata=prompt.get("metadata"),
            )
            verified = ResumeParserAgentOutput(
                full_name=coerce_string(payload.get("full_name"), default=candidate_profile.full_name),
                location=coerce_string(payload.get("location"), default=candidate_profile.location),
                contact_lines=coerce_string_list(payload.get("contact_lines")),
                skills=coerce_string_list(payload.get("skills")),
                experience=_coerce_work_experience_list(payload.get("experience")),
                education=_coerce_education_list(payload.get("education")),
                certifications=coerce_string_list(payload.get("certifications")),
                verification_notes=coerce_string_list(payload.get("verification_notes"), limit=4),
            )
            return CandidateProfile(
                full_name=verified.full_name or candidate_profile.full_name,
                location=verified.location or candidate_profile.location,
                contact_lines=verified.contact_lines or candidate_profile.contact_lines,
                source=candidate_profile.source,
                resume_text=candidate_profile.resume_text,
                skills=verified.skills or candidate_profile.skills,
                experience=verified.experience or candidate_profile.experience,
                education=verified.education or candidate_profile.education,
                certifications=verified.certifications or candidate_profile.certifications,
                source_signals=unique_strings(
                    list(candidate_profile.source_signals)
                    + (["Resume parser agent reviewed and corrected the structured profile."] if verified.verification_notes else [])
                    + verified.verification_notes,
                    limit=12,
                ),
            )
        return candidate_profile
