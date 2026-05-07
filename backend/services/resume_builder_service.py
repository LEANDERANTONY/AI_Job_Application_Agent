from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal
from uuid import uuid4

from src.config import get_openai_max_completion_tokens_for_task
from src.errors import AgentExecutionError
from src.exporters import export_docx_bytes, export_pdf_bytes
from src.logging_utils import get_logger, log_event
from src.prompts import build_resume_builder_prompt
from src.resume_builder import build_tailored_resume_artifact
from src.schemas import (
    CandidateProfile,
    EducationEntry,
    FitAnalysis,
    JobDescription,
    JobRequirements,
    ResumeDocument,
    TailoredResumeDraft,
    WorkExperience,
)
from src.utils import dedupe_strings, markdown_to_text, slugify_text


LOGGER = get_logger(__name__)


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
    # Conversational LLM intake stores user/assistant turn pairs here so
    # subsequent turns have narrative continuity (backtracking, "as I
    # said earlier" references, etc.). Each entry is
    # `{"role": "user" | "assistant", "content": str}`. Empty list means
    # the regex / step-machine flow is in use.
    conversation_history: list[dict] = field(default_factory=list)


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


_LOCATION_PREAMBLE_PATTERN = re.compile(
    r"\b(?:based in|from|located in|living in|currently in|in)\b\s+",
    re.IGNORECASE,
)
_NAME_PREAMBLE_PATTERN = re.compile(
    r"^(?:i\s+am|i'?m|my\s+name\s+is|name[:]?)\s*",
    re.IGNORECASE,
)


def _looks_like_personal_name(value: str) -> bool:
    """Heuristic: looks like a person's name (1-5 short words, mostly letters).

    Unicode-aware: accepts any letter the user's keyboard produces,
    including accented Latin (François, Müller), Cyrillic, CJK, etc.
    Rejects digits, underscores, and structural symbols (`@`, `/`, etc.)
    so emails/urls/role labels can't be misclassified as names.
    """
    cleaned = value.strip(" ,.;-").strip()
    if not cleaned or "@" in cleaned or "/" in cleaned or "http" in cleaned.lower():
        return False
    words = cleaned.split()
    if not (1 <= len(words) <= 5):
        return False
    for word in words:
        if not word or not word[0].isalpha():
            return False
        # Allow inner connectors (apostrophe, hyphen, period — for
        # names like O'Brien, Smith-Jones, St. John) plus any letter
        # in any script. Reject digits and underscores.
        for ch in word[1:]:
            if not (ch.isalpha() or ch in "'-."):
                return False
    return True


def _apply_basics(session: ResumeBuilderSession, message: str):
    """Pull out name, location, and contact lines from a free-form answer.

    Users typically reply on one line ("Leander Antony A, based in Chennai,
    India. Email: …, phone: …, GitHub: …") so the prior implementation
    that only split on newlines fell back to empty name/location every
    time. This pass splits the message on commas + sentence boundaries,
    classifies each chunk, and threads the leftovers into name/location
    detection.
    """
    text = str(message or "").strip()
    if not text:
        return

    # Coarse split: commas, semicolons, pipes, newlines, AND sentence
    # boundaries. The contact extractor below only cares about chunks
    # that hold a contact pattern; the rest are name/location candidates.
    coarse_parts = [
        part.strip()
        for part in re.split(r"[\n,;|]+|(?<=[.!?])\s+", text)
        if part and part.strip()
    ]
    if not coarse_parts:
        return

    contact_chunks: list[str] = []
    leftover_chunks: list[str] = []

    for part in coarse_parts:
        is_contact = bool(
            EMAIL_PATTERN.search(part)
            or PHONE_PATTERN.search(part)
            or URL_PATTERN.search(part)
        )
        if is_contact:
            # Extract just the contact-bearing token out of the chunk —
            # avoids storing prose like "phone: +91 …" with the
            # leading label, which doesn't belong on a resume header.
            contact_chunks.extend(_extract_contact_lines(part) or [part])
        else:
            leftover_chunks.append(part.rstrip(".").strip())

    session.draft.contact_lines = dedupe_strings(
        session.draft.contact_lines + contact_chunks
    )

    if not leftover_chunks:
        return

    # Strip "I'm / my name is" preambles before classifying.
    cleaned_chunks: list[str] = []
    for chunk in leftover_chunks:
        cleaned = _NAME_PREAMBLE_PATTERN.sub("", chunk).strip()
        # Strip "based in X" → "X" so the location chunk is just the
        # place; the preamble itself is noise.
        if _LOCATION_PREAMBLE_PATTERN.search(cleaned):
            cleaned = _LOCATION_PREAMBLE_PATTERN.sub("", cleaned, count=1).strip()
        if cleaned:
            cleaned_chunks.append(cleaned)

    if not cleaned_chunks:
        return

    # First chunk that looks like a personal name → full_name.
    name_index: int | None = None
    for index, chunk in enumerate(cleaned_chunks):
        if _looks_like_personal_name(chunk):
            session.draft.full_name = chunk
            name_index = index
            break

    # Location: combine adjacent chunks that look like place fragments
    # ("Chennai" + "India" → "Chennai, India"). Skip the name chunk.
    location_parts: list[str] = []
    for index, chunk in enumerate(cleaned_chunks):
        if index == name_index:
            continue
        if _looks_like_location(chunk):
            location_parts.append(chunk)
    if location_parts:
        session.draft.location = ", ".join(location_parts[:2])


_ROLE_PREAMBLE_PATTERN = re.compile(
    r"^\s*(?:i'?m\s+)?(?:currently\s+|primarily\s+|mostly\s+)?"
    r"(?:targeting|looking\s+for|aiming\s+for|seeking|interested\s+in)\s+",
    re.IGNORECASE,
)
_ROLE_SUFFIX_PATTERN = re.compile(r"\s+roles?\s*$", re.IGNORECASE)


def _apply_role(session: ResumeBuilderSession, message: str):
    """Split the role answer into a SHORT title + a free-form summary.

    Users routinely answer with a paragraph ("Targeting Senior ML
    Engineer / Applied AI roles. Independent ML engineer with 4 years
    building production AI systems including …"). The prior version
    stuffed the whole paragraph into target_role AND professional_summary,
    which then renders as a cramped multi-line role title in the resume
    header. Now we split on the first sentence boundary, strip
    "Targeting / looking for" preambles, and cap the title length.

    Newline-first: when the user answers with the title on line 1 and
    background on line 2 (a very common pattern, even without
    sentence-ending punctuation on line 1), prefer the newline split.
    Fall through to sentence-boundary splitting only when the message
    is single-line.
    """
    text = str(message or "").strip()
    if not text:
        return

    title_chunk: str = ""
    summary_chunk: str = ""
    if "\n" in text:
        leading, _, remainder = text.partition("\n")
        leading_clean = leading.strip().rstrip(".!?,;: ")
        if leading_clean and len(leading_clean) <= 80:
            title_chunk = leading_clean
            summary_chunk = remainder.strip()
    if not title_chunk:
        # Single-line answer (or leading line was too long to be a
        # title): fall back to sentence-boundary splitting so a
        # paragraph-style answer still extracts the lead clause.
        sentence_split = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)
        title_chunk = sentence_split[0].strip().rstrip(".!?,;: ")
        summary_chunk = sentence_split[1].strip() if len(sentence_split) > 1 else ""

    # Strip "Targeting" / "Looking for" / trailing "roles" so the stored
    # value is the role TITLE itself, not the user's framing of it.
    title_chunk = _ROLE_PREAMBLE_PATTERN.sub("", title_chunk).strip()
    title_chunk = _ROLE_SUFFIX_PATTERN.sub("", title_chunk).strip()

    # Cap the title at 80 chars so we don't render paragraphs in the
    # resume header. Trim on the last word boundary when over budget.
    if len(title_chunk) > 80:
        truncated = title_chunk[:80]
        last_space = truncated.rfind(" ")
        if last_space > 40:
            truncated = truncated[:last_space]
        title_chunk = f"{truncated}…"

    session.draft.target_role = title_chunk

    # Summary defaults to the post-title sentences. If the user wrote
    # only a single sentence (no period), fall back to the whole text
    # so the summary slot isn't empty and the resume preview reads
    # naturally.
    session.draft.professional_summary = summary_chunk or text


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
    # `_step_index("review")` returns 0 because "review" isn't in
    # RESUME_BUILDER_STEPS — that used to flicker the UI back to 0%
    # and drop every DONE badge the moment the user landed on Review.
    # Treat "review" (and "ready") as all-steps-complete instead.
    if session.current_step == "review" or session.status in {"reviewing", "ready"}:
        completed_steps = len(RESUME_BUILDER_STEPS)
    else:
        completed_steps = min(
            _step_index(session.current_step),
            len(RESUME_BUILDER_STEPS) - 1,
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
            "conversation_history": list(session.conversation_history or []),
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

    history_payload = raw_payload.get("conversation_history") or []
    if not isinstance(history_payload, list):
        history_payload = []
    sanitized_history = [
        {
            "role": str(item.get("role", "") or "").strip() or "user",
            "content": str(item.get("content", "") or ""),
        }
        for item in history_payload
        if isinstance(item, dict)
    ]

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
        conversation_history=sanitized_history,
    )
    _SESSIONS[session.session_id] = session
    return _serialize_session(session)


def has_resume_builder_session(session_id: str) -> bool:
    return str(session_id or "").strip() in _SESSIONS


def start_resume_builder_session():
    session = ResumeBuilderSession(session_id=str(uuid4()))
    _SESSIONS[session.session_id] = session
    return _serialize_session(session)


_VALID_STATUSES = {"collecting", "reviewing", "ready"}


def _coerce_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _apply_llm_draft_updates(session: ResumeBuilderSession, updates: dict):
    """Merge a partial dict of resume-builder fields into the session's
    draft. Mirrors the shape of `_apply_draft_updates` but only writes
    keys present in `updates` (so the LLM can return a partial)."""
    if not isinstance(updates, dict):
        return
    if "full_name" in updates:
        session.draft.full_name = str(updates.get("full_name") or "").strip()
    if "location" in updates:
        session.draft.location = str(updates.get("location") or "").strip()
    if "contact_lines" in updates:
        session.draft.contact_lines = dedupe_strings(
            _coerce_string_list(updates.get("contact_lines"))
        )
    if "target_role" in updates:
        session.draft.target_role = str(updates.get("target_role") or "").strip()
    if "professional_summary" in updates:
        session.draft.professional_summary = str(
            updates.get("professional_summary") or ""
        ).strip()
    if "experience_notes" in updates:
        session.draft.experience_notes = str(
            updates.get("experience_notes") or ""
        ).strip()
    if "education_notes" in updates:
        session.draft.education_notes = str(
            updates.get("education_notes") or ""
        ).strip()
    if "skills" in updates:
        session.draft.skills = dedupe_strings(_coerce_string_list(updates.get("skills")))
    if "certifications" in updates:
        session.draft.certifications = dedupe_strings(
            _coerce_string_list(updates.get("certifications"))
        )


def _run_llm_turn(
    *,
    session: ResumeBuilderSession,
    user_message: str,
    openai_service,
):
    """Drive one conversational turn through the LLM intake prompt.

    Returns the assistant message text on success. Mutates the session
    in place: applies `draft_updates`, updates `status` and
    `current_step`, appends the user/assistant turn pair to
    `conversation_history`. Raises `AgentExecutionError` on any failure
    so the caller can swallow it and fall back to the regex flow.
    """
    if openai_service is None or not openai_service.is_available():
        raise AgentExecutionError("OpenAI service is not available for resume builder intake.")

    prompt = build_resume_builder_prompt(
        draft=asdict(session.draft),
        history=session.conversation_history,
        user_message=user_message,
    )
    payload = openai_service.run_json_prompt(
        prompt["system"],
        prompt["user"],
        expected_keys=prompt["expected_keys"],
        temperature=None,
        max_completion_tokens=get_openai_max_completion_tokens_for_task("resume_builder"),
        task_name="resume_builder",
        allow_output_budget_retry=False,
    )

    draft_updates = payload.get("draft_updates")
    if isinstance(draft_updates, dict):
        _apply_llm_draft_updates(session, draft_updates)

    assistant_message = str(payload.get("assistant_message") or "").strip()
    if not assistant_message:
        raise AgentExecutionError("LLM returned an empty assistant_message.")

    raw_status = str(payload.get("status") or "").strip().lower()
    status = raw_status if raw_status in _VALID_STATUSES else "collecting"
    session.status = status

    focus_field = str(payload.get("focus_field") or "").strip()
    if status == "ready":
        session.current_step = "review"
    elif status == "reviewing":
        session.current_step = "review"
    elif focus_field and any(focus_field == key for key, _ in RESUME_BUILDER_STEPS):
        # Map LLM focus_field back to a step key for legacy
        # `current_step` consumers (UI progress indicator, etc.).
        session.current_step = focus_field
    elif focus_field in {"full_name", "location", "contact_lines"}:
        session.current_step = "basics"
    elif focus_field in {"professional_summary", "target_role"}:
        session.current_step = "role"
    elif focus_field in {"experience_notes"}:
        session.current_step = "experience"
    elif focus_field in {"education_notes", "certifications"}:
        session.current_step = "education"
    elif focus_field in {"skills"}:
        session.current_step = "skills"
    # If the model returned no focus_field, leave current_step alone.

    session.conversation_history.append(
        {"role": "user", "content": user_message}
    )
    session.conversation_history.append(
        {"role": "assistant", "content": assistant_message}
    )
    # Cap memory: keep only the last 24 turn pairs so a long session
    # doesn't blow the prompt budget. The model still sees enough
    # context for back-references; older turns are summarized by the
    # current `draft` state itself.
    if len(session.conversation_history) > 48:
        session.conversation_history = session.conversation_history[-48:]

    return assistant_message


def _advance_step_after_regex_apply(session: ResumeBuilderSession, current_step: str):
    """Tick the step machine forward after a deterministic _apply_*
    call. Pulled out of `answer_resume_builder_message` so the regex
    fallback path and the legacy regex-only path share the same
    advancement logic."""
    current_index = _step_index(current_step)
    next_index = current_index + 1
    next_step = (
        RESUME_BUILDER_STEPS[next_index][0]
        if next_index < len(RESUME_BUILDER_STEPS)
        else None
    )

    if next_step:
        session.current_step = next_step
        session.status = "collecting"
    else:
        session.current_step = "review"
        session.status = "reviewing"
    return next_step


def answer_resume_builder_message(
    *,
    session_id: str,
    message: str,
    openai_service=None,
):
    session = _SESSIONS.get(str(session_id or "").strip())
    if session is None:
        raise ValueError("Resume builder session not found.")

    normalized_message = str(message or "").strip()
    if not normalized_message:
        raise ValueError("Add an answer before continuing.")

    # LLM-first path: when an OpenAIService is available, the model
    # extracts fields, picks the next question, and produces the
    # conversational reply. The regex / step-machine path below stays
    # as the safety net so the feature still works without an API key,
    # on JSON-decode failures, or on any other LLM error.
    if openai_service is not None and openai_service.is_available():
        try:
            assistant_message = _run_llm_turn(
                session=session,
                user_message=normalized_message,
                openai_service=openai_service,
            )
            return _serialize_session(
                session,
                assistant_message=assistant_message,
            )
        except AgentExecutionError as exc:
            log_event(
                LOGGER,
                logging.WARNING,
                "resume_builder_llm_fallback",
                "Resume-builder LLM turn failed; falling back to deterministic intake.",
                session_id=session.session_id,
                error_type=type(exc).__name__,
                error_message=exc.user_message,
            )
        except Exception as exc:  # pragma: no cover - defensive
            LOGGER.exception(
                "Resume-builder LLM turn raised unexpectedly.",
                extra={"session_id": session.session_id},
            )

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

    next_step = _advance_step_after_regex_apply(session, current_step)

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


_DOCX_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)


def _synthesize_resume_builder_artifact(
    session: ResumeBuilderSession,
    *,
    theme: str,
):
    """Build a TailoredResumeArtifact from a resume-builder session.

    Phase 5 of the DOCX export plan. The resume-builder is a separate
    intake surface (no JD context, no agent_result), so we synthesize
    empty JobDescription / FitAnalysis / TailoredResumeDraft objects
    and let `build_tailored_resume_artifact` do the structural work.
    Section order falls out of `compute_section_order(candidate_profile)`
    via `_resolve_section_order` in the artifact builder.

    The artifact's title and filename_stem are then overridden so the
    download reads as a generic base resume rather than a "Tailored
    Resume" — that wording belongs to JD-driven exports, not the
    builder's exit point.
    """
    _, candidate_profile = _build_candidate_profile_and_resume(session)

    job_description = JobDescription(
        title=session.draft.target_role or "",
        raw_text="",
        cleaned_text="",
        requirements=JobRequirements(),
    )
    fit_analysis = FitAnalysis(
        target_role=session.draft.target_role or "",
        overall_score=0,
        readiness_label="",
        # Surfacing the user's confirmed skills as 'matched' lets the
        # artifact builder's highlighted_skills merge logic still pick
        # them up; without this, highlighted_skills could collapse to
        # an empty list when the agent_result is absent.
        matched_hard_skills=list(session.draft.skills or []),
    )
    tailored_draft = TailoredResumeDraft(
        target_role=session.draft.target_role or "",
        professional_summary=session.draft.professional_summary or "",
        highlighted_skills=list(session.draft.skills or []),
    )

    artifact = build_tailored_resume_artifact(
        candidate_profile,
        job_description,
        fit_analysis,
        tailored_draft,
        theme=theme,
    )

    name = (candidate_profile.full_name or "Candidate").strip() or "Candidate"
    target_role = (session.draft.target_role or "").strip()
    if target_role:
        artifact.title = f"{name} - {target_role} Resume"
        slug_source = f"{name}-{target_role}-resume"
    else:
        artifact.title = f"{name} Resume"
        slug_source = f"{name}-resume"
    artifact.filename_stem = slugify_text(slug_source, fallback="resume")

    return artifact


def export_resume_builder_artifact(
    *,
    session_id: str,
    export_format: str,
    theme: str = "classic_ats",
):
    """Render the builder's generated resume as PDF or DOCX bytes.

    Returns a dict shaped the same as
    `backend.services.artifact_export_service.export_workspace_artifact`
    so the frontend's `downloadBase64File` helper handles both the
    workspace and resume-builder downloads identically. Auth gating
    + session hydration on a cache miss live in the route handler;
    this function only depends on the in-memory session being present.
    """
    import base64

    session = _SESSIONS.get(str(session_id or "").strip())
    if session is None:
        raise ValueError("Resume builder session not found.")

    normalized_format = str(export_format or "").strip().lower()
    if normalized_format not in {"pdf", "docx"}:
        raise ValueError("Choose a supported export format.")

    normalized_theme = str(theme or "").strip()
    if normalized_theme not in {"classic_ats", "professional_neutral"}:
        normalized_theme = "classic_ats"

    artifact = _synthesize_resume_builder_artifact(session, theme=normalized_theme)

    if normalized_format == "pdf":
        payload = export_pdf_bytes(artifact)
        mime_type = "application/pdf"
        file_name = f"{artifact.filename_stem or 'resume'}.pdf"
    else:
        payload = export_docx_bytes(artifact)
        mime_type = _DOCX_MIME_TYPE
        file_name = f"{artifact.filename_stem or 'resume'}.docx"

    return {
        "status": "ready",
        "export_format": normalized_format,
        "file_name": file_name,
        "mime_type": mime_type,
        "content_base64": base64.b64encode(payload).decode("ascii"),
        "theme": normalized_theme,
        "artifact_title": artifact.title,
    }
