from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Literal
from uuid import uuid4

from src.schemas import CandidateProfile, EducationEntry, ResumeDocument, WorkExperience
from src.utils import dedupe_strings, markdown_to_text


EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"(?:\+\d{1,3}[\s\-]?)?(?:\(?\d{2,5}\)?[\s\-]?){2,4}\d{2,4}")
URL_PATTERN = re.compile(r"(?:https?://)?(?:www\.)?[A-Z0-9.-]+\.[A-Z]{2,}(?:/[^\s,;]+)?", re.IGNORECASE)

RESUME_BUILDER_STEPS: list[tuple[str, str]] = [
    (
        "basics",
        "Tell me your full name, location, email, phone number, and any links you want on the resume.",
    ),
    (
        "role",
        "What kind of role are you targeting, and how would you describe your background in 2-3 lines?",
    ),
    (
        "experience",
        "Describe your most relevant experience. Include your role, company, dates, and 2-4 impact points if you can.",
    ),
    (
        "education",
        "Share your education details and any certifications you want included.",
    ),
    (
        "skills",
        "List the tools, technologies, and strengths you want highlighted on the resume.",
    ),
]


@dataclass
class ResumeBuilderDraft:
    full_name: str = ""
    location: str = ""
    contact_lines: list[str] = field(default_factory=list)
    target_role: str = ""
    professional_summary: str = ""
    experience_notes: str = ""
    education_notes: str = ""
    skills: list[str] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)


@dataclass
class ResumeBuilderSession:
    session_id: str
    current_step: str = "basics"
    status: Literal["collecting", "reviewing", "ready"] = "collecting"
    draft: ResumeBuilderDraft = field(default_factory=ResumeBuilderDraft)
    generated_resume_markdown: str = ""
    generated_resume_plain_text: str = ""


_SESSIONS: dict[str, ResumeBuilderSession] = {}


def _step_index(step: str) -> int:
    for index, (key, _) in enumerate(RESUME_BUILDER_STEPS):
        if key == step:
            return index
    return 0


def _current_prompt(step: str) -> str:
    for key, prompt in RESUME_BUILDER_STEPS:
        if key == step:
            return prompt
    return RESUME_BUILDER_STEPS[0][1]


def _normalize_lines(message: str) -> list[str]:
    return [line.strip(" -•\t") for line in str(message or "").splitlines() if line.strip()]


def _split_tokens(message: str) -> list[str]:
    raw_parts = re.split(r"[\n,;|]+", str(message or ""))
    return [part.strip() for part in raw_parts if part.strip()]


def _extract_contact_lines(message: str) -> list[str]:
    parts = _split_tokens(message)
    contacts: list[str] = []
    for part in parts:
        if EMAIL_PATTERN.search(part) or PHONE_PATTERN.search(part) or URL_PATTERN.search(part):
            contacts.append(part)
    return dedupe_strings(contacts)


def _looks_like_location(value: str) -> bool:
    lowered = value.lower()
    return "," in value or "remote" in lowered or len(value.split()) <= 4


def _apply_basics(session: ResumeBuilderSession, message: str):
    lines = _normalize_lines(message)
    if not lines:
        return

    session.draft.contact_lines = dedupe_strings(
        session.draft.contact_lines + _extract_contact_lines(message)
    )

    non_contact_lines = [
        line
        for line in lines
        if line not in session.draft.contact_lines
        and not EMAIL_PATTERN.search(line)
        and not PHONE_PATTERN.search(line)
        and not URL_PATTERN.search(line)
    ]

    if non_contact_lines:
        session.draft.full_name = non_contact_lines[0]
    if len(non_contact_lines) > 1 and _looks_like_location(non_contact_lines[1]):
        session.draft.location = non_contact_lines[1]


def _apply_role(session: ResumeBuilderSession, message: str):
    lines = _normalize_lines(message)
    if not lines:
        return
    session.draft.target_role = lines[0]
    if len(lines) > 1:
        session.draft.professional_summary = " ".join(lines[1:])
    else:
        session.draft.professional_summary = lines[0]


def _apply_experience(session: ResumeBuilderSession, message: str):
    session.draft.experience_notes = str(message or "").strip()


def _apply_education(session: ResumeBuilderSession, message: str):
    raw_lines = _normalize_lines(message)
    if not raw_lines:
        return
    certifications = [
        line
        for line in raw_lines
        if re.search(r"certif|certificate|credential|specialization|specialisation", line, re.IGNORECASE)
    ]
    session.draft.certifications = dedupe_strings(session.draft.certifications + certifications)
    education_lines = [line for line in raw_lines if line not in certifications]
    session.draft.education_notes = "\n".join(education_lines).strip()


def _apply_skills(session: ResumeBuilderSession, message: str):
    skills = [
        token
        for token in _split_tokens(message)
        if len(token) > 1
    ]
    session.draft.skills = dedupe_strings(skills)


def _build_next_message(previous_step: str, next_step: str | None) -> str:
    acknowledgements = {
        "basics": "Got it. I’ve captured your contact details.",
        "role": "Nice. I’ve got the role direction and your summary.",
        "experience": "Great. I’ve saved your experience notes.",
        "education": "Perfect. I’ve added your education details.",
        "skills": "Nice. I’ve captured the skills you want highlighted.",
    }
    if not next_step:
        return (
            f"{acknowledgements.get(previous_step, 'Saved.')}"
            " Everything is collected. Review the draft and generate your base resume when you’re ready."
        )
    return f"{acknowledgements.get(previous_step, 'Saved.')} {_current_prompt(next_step)}"


def _apply_draft_updates(session: ResumeBuilderSession, updates: dict):
    if "full_name" in updates:
        session.draft.full_name = str(updates.get("full_name", "") or "").strip()
    if "location" in updates:
        session.draft.location = str(updates.get("location", "") or "").strip()
    if "contact_lines" in updates:
        contact_lines = updates.get("contact_lines", [])
        if not isinstance(contact_lines, list):
            contact_lines = []
        session.draft.contact_lines = dedupe_strings(
            [str(item).strip() for item in contact_lines if str(item).strip()]
        )
    if "target_role" in updates:
        session.draft.target_role = str(updates.get("target_role", "") or "").strip()
    if "professional_summary" in updates:
        session.draft.professional_summary = str(
            updates.get("professional_summary", "") or ""
        ).strip()
    if "experience_notes" in updates:
        session.draft.experience_notes = str(
            updates.get("experience_notes", "") or ""
        ).strip()
    if "education_notes" in updates:
        session.draft.education_notes = str(
            updates.get("education_notes", "") or ""
        ).strip()
    if "skills" in updates:
        skills = updates.get("skills", [])
        if not isinstance(skills, list):
            skills = []
        session.draft.skills = dedupe_strings(
            [str(item).strip() for item in skills if str(item).strip()]
        )
    if "certifications" in updates:
        certifications = updates.get("certifications", [])
        if not isinstance(certifications, list):
            certifications = []
        session.draft.certifications = dedupe_strings(
            [str(item).strip() for item in certifications if str(item).strip()]
        )


def _build_experience_entries(notes: str) -> list[WorkExperience]:
    normalized = _normalize_lines(notes)
    if not normalized:
        return []

    headline = normalized[0]
    title = headline
    organization = ""
    location = ""
    start = ""
    end = ""

    if " at " in headline.lower():
        parts = re.split(r"\bat\b", headline, maxsplit=1, flags=re.IGNORECASE)
        if len(parts) == 2:
            title = parts[0].strip(" ,-")
            organization = parts[1].strip(" ,-")
    elif "|" in headline:
        parts = [part.strip() for part in headline.split("|") if part.strip()]
        if parts:
            title = parts[0]
        if len(parts) > 1:
            organization = parts[1]
        if len(parts) > 2:
            start = parts[2]

    bullets = normalized[1:] if len(normalized) > 1 else []
    description = "\n".join(bullets).strip() if bullets else headline
    return [
        WorkExperience(
            title=title or "Relevant Experience",
            organization=organization,
            location=location,
            description=description,
            start=start or None,
            end=end or None,
        )
    ]


def _build_education_entries(notes: str) -> list[EducationEntry]:
    normalized = _normalize_lines(notes)
    if not normalized:
        return []
    primary = normalized[0]
    institution = primary
    degree = ""
    if "|" in primary:
        parts = [part.strip() for part in primary.split("|") if part.strip()]
        institution = parts[0]
        if len(parts) > 1:
            degree = parts[1]
    return [
        EducationEntry(
            institution=institution,
            degree=degree,
        )
    ]


def _build_resume_markdown(draft: ResumeBuilderDraft) -> str:
    sections: list[str] = []
    header_name = draft.full_name or "Your Name"
    sections.append(f"# {header_name}")
    if draft.location:
        sections.append(draft.location)
    if draft.contact_lines:
        sections.append(" | ".join(draft.contact_lines))

    sections.append("")
    sections.append("## Professional Summary")
    sections.append(draft.professional_summary or f"Targeting {draft.target_role or 'a new role'} with a grounded profile built through guided intake.")

    sections.append("")
    sections.append("## Core Skills")
    if draft.skills:
        sections.extend(f"- {skill}" for skill in draft.skills)
    else:
        sections.append("- Add your strongest tools and skills here.")

    sections.append("")
    sections.append("## Professional Experience")
    if draft.experience_notes:
        for line in _normalize_lines(draft.experience_notes):
            prefix = "- " if line != _normalize_lines(draft.experience_notes)[0] else ""
            sections.append(f"{prefix}{line}" if prefix else line)
    else:
        sections.append("- Add your most relevant role, impact, and projects here.")

    sections.append("")
    sections.append("## Education")
    if draft.education_notes:
        sections.extend(_normalize_lines(draft.education_notes))
    else:
        sections.append("- Add your education details here.")

    if draft.certifications:
        sections.append("")
        sections.append("## Certifications")
        sections.extend(f"- {certification}" for certification in draft.certifications)

    return "\n".join(sections).strip()


def _build_candidate_profile_and_resume(session: ResumeBuilderSession) -> tuple[ResumeDocument, CandidateProfile]:
    markdown = _build_resume_markdown(session.draft)
    plain_text = markdown_to_text(markdown, strip_bold=True)
    session.generated_resume_markdown = markdown
    session.generated_resume_plain_text = plain_text

    resume_document = ResumeDocument(
        text=plain_text,
        filetype="AI Draft",
        source="assistant_builder",
    )
    candidate_profile = CandidateProfile(
        full_name=session.draft.full_name,
        location=session.draft.location,
        contact_lines=session.draft.contact_lines,
        source="assistant_builder",
        resume_text=plain_text,
        skills=session.draft.skills,
        experience=_build_experience_entries(session.draft.experience_notes),
        education=_build_education_entries(session.draft.education_notes),
        certifications=session.draft.certifications,
        source_signals=dedupe_strings(
            [
                "Profile created with the resume builder assistant.",
                f"Target role: {session.draft.target_role}" if session.draft.target_role else "",
                "Experience notes captured through guided intake." if session.draft.experience_notes else "",
                "Skills were confirmed by the user." if session.draft.skills else "",
            ]
        ),
    )
    return resume_document, candidate_profile


def _serialize_session(
    session: ResumeBuilderSession,
    *,
    assistant_message: str | None = None,
):
    step_position = min(_step_index(session.current_step), len(RESUME_BUILDER_STEPS) - 1)
    completed_steps = (
        len(RESUME_BUILDER_STEPS)
        if session.status == "ready"
        else step_position
    )
    progress_percent = int((completed_steps / len(RESUME_BUILDER_STEPS)) * 100)
    return {
        "session_id": session.session_id,
        "status": session.status,
        "current_step": session.current_step,
        "completed_steps": completed_steps,
        "total_steps": len(RESUME_BUILDER_STEPS),
        "progress_percent": progress_percent,
        "assistant_message": assistant_message or _current_prompt(session.current_step),
        "draft_profile": asdict(session.draft),
        "generated_resume_markdown": session.generated_resume_markdown,
        "generated_resume_plain_text": session.generated_resume_plain_text,
        "ready_to_generate": session.status in {"reviewing", "ready"},
        "ready_to_commit": bool(session.generated_resume_markdown),
    }


def export_resume_builder_session_payload(*, session_id: str):
    session = _SESSIONS.get(str(session_id or "").strip())
    if session is None:
        raise ValueError("Resume builder session not found.")
    return json.dumps(
        {
            "session_id": session.session_id,
            "current_step": session.current_step,
            "status": session.status,
            "draft_profile": asdict(session.draft),
            "generated_resume_markdown": session.generated_resume_markdown,
            "generated_resume_plain_text": session.generated_resume_plain_text,
        },
        separators=(",", ":"),
    )


def restore_resume_builder_session_payload(payload_json: str):
    raw_payload = json.loads(str(payload_json or "").strip() or "{}")
    if not isinstance(raw_payload, dict):
        raise ValueError("Resume builder session payload is invalid.")

    draft_payload = raw_payload.get("draft_profile") or {}
    if not isinstance(draft_payload, dict):
        raise ValueError("Resume builder session draft payload is invalid.")

    session = ResumeBuilderSession(
        session_id=str(raw_payload.get("session_id", "") or uuid4()),
        current_step=str(raw_payload.get("current_step", "basics") or "basics"),
        status=str(raw_payload.get("status", "collecting") or "collecting"),
        draft=ResumeBuilderDraft(
            full_name=str(draft_payload.get("full_name", "") or ""),
            location=str(draft_payload.get("location", "") or ""),
            contact_lines=[
                str(item).strip()
                for item in draft_payload.get("contact_lines", [])
                if str(item).strip()
            ],
            target_role=str(draft_payload.get("target_role", "") or ""),
            professional_summary=str(draft_payload.get("professional_summary", "") or ""),
            experience_notes=str(draft_payload.get("experience_notes", "") or ""),
            education_notes=str(draft_payload.get("education_notes", "") or ""),
            skills=[
                str(item).strip()
                for item in draft_payload.get("skills", [])
                if str(item).strip()
            ],
            certifications=[
                str(item).strip()
                for item in draft_payload.get("certifications", [])
                if str(item).strip()
            ],
        ),
        generated_resume_markdown=str(
            raw_payload.get("generated_resume_markdown", "") or ""
        ),
        generated_resume_plain_text=str(
            raw_payload.get("generated_resume_plain_text", "") or ""
        ),
    )
    _SESSIONS[session.session_id] = session
    return _serialize_session(session)


def start_resume_builder_session():
    session = ResumeBuilderSession(session_id=str(uuid4()))
    _SESSIONS[session.session_id] = session
    return _serialize_session(session)


def answer_resume_builder_message(*, session_id: str, message: str):
    session = _SESSIONS.get(str(session_id or "").strip())
    if session is None:
        raise ValueError("Resume builder session not found.")

    normalized_message = str(message or "").strip()
    if not normalized_message:
        raise ValueError("Add an answer before continuing.")

    current_step = session.current_step
    if current_step == "basics":
        _apply_basics(session, normalized_message)
    elif current_step == "role":
        _apply_role(session, normalized_message)
    elif current_step == "experience":
        _apply_experience(session, normalized_message)
    elif current_step == "education":
        _apply_education(session, normalized_message)
    elif current_step == "skills":
        _apply_skills(session, normalized_message)

    current_index = _step_index(current_step)
    next_index = current_index + 1
    next_step = RESUME_BUILDER_STEPS[next_index][0] if next_index < len(RESUME_BUILDER_STEPS) else None

    if next_step:
        session.current_step = next_step
        session.status = "collecting"
    else:
        session.current_step = "review"
        session.status = "reviewing"

    return _serialize_session(
        session,
        assistant_message=_build_next_message(current_step, next_step),
    )


def generate_resume_builder_resume(*, session_id: str):
    session = _SESSIONS.get(str(session_id or "").strip())
    if session is None:
        raise ValueError("Resume builder session not found.")

    resume_document, candidate_profile = _build_candidate_profile_and_resume(session)
    session.status = "ready"

    payload = _serialize_session(
        session,
        assistant_message="Your base resume draft is ready. Review it and use this profile when you want to continue into the workspace.",
    )
    payload["resume_document"] = asdict(resume_document)
    payload["candidate_profile"] = asdict(candidate_profile)
    return payload


def update_resume_builder_session(*, session_id: str, draft_updates: dict):
    session = _SESSIONS.get(str(session_id or "").strip())
    if session is None:
        raise ValueError("Resume builder session not found.")

    normalized_updates = dict(draft_updates or {})
    _apply_draft_updates(session, normalized_updates)

    return _serialize_session(
        session,
        assistant_message="Draft updated. Keep answering prompts or generate the base resume when you are ready.",
    )


def commit_resume_builder_session(*, session_id: str):
    session = _SESSIONS.get(str(session_id or "").strip())
    if session is None:
        raise ValueError("Resume builder session not found.")

    resume_document, candidate_profile = _build_candidate_profile_and_resume(session)
    session.status = "ready"
    return {
        "resume_document": asdict(resume_document),
        "candidate_profile": asdict(candidate_profile),
        "generated_resume_markdown": session.generated_resume_markdown,
        "generated_resume_plain_text": session.generated_resume_plain_text,
        "builder_session_id": session.session_id,
    }
