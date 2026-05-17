from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal
from uuid import uuid4

from backend import quota
from backend.services.auth_session_service import resolve_authenticated_context
from backend.tiers import resolve_user_tier
from src.config import get_openai_max_completion_tokens_for_task
from src.errors import AgentExecutionError
from src.exporters import export_docx_bytes, export_pdf_bytes
from src.logging_utils import get_logger, log_event
from src.prompts import build_resume_builder_prompt, build_resume_builder_structuring_prompt
from src.resume_builder import build_tailored_resume_artifact
from src.schemas import (
    CandidateProfile,
    EducationEntry,
    FitAnalysis,
    JobDescription,
    JobRequirements,
    ProjectEntry,
    ResumeDocument,
    TailoredResumeDraft,
    WorkExperience,
)
from src.schemas_llm_outputs import ResumeBuilderStructuringOutput
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
    # Projects: free-form prose like experience_notes (the LLM intake
    # captures verbatim, the structuring pass turns it into ProjectEntry
    # objects). Optional — only asked when the user has a tech-heavy
    # background or mentions side projects.
    projects_notes: str = ""
    # Publications: list of citation strings, like certifications.
    # Optional — only relevant for academics / researchers.
    publications: list[str] = field(default_factory=list)


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
    # Cache for the LLM structuring pass. The signature is a SHA256 of
    # the inputs the structuring prompt sees; if the user edits any of
    # those inputs the hash changes and we re-run the LLM. Without this
    # cache every export at a different theme (or a re-download for a
    # different format) re-burns a structuring call AND the LLM may
    # rephrase bullets between calls — re-downloads would silently
    # produce different wording, which felt off in QA.
    structuring_signature: str = ""
    structured_experience_payload: list[dict] = field(default_factory=list)
    structured_education_payload: list[dict] = field(default_factory=list)
    structured_projects_payload: list[dict] = field(default_factory=list)
    structured_skill_categories: dict = field(default_factory=dict)
    structured_professional_summary: str = ""


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
    if "projects_notes" in updates:
        session.draft.projects_notes = str(updates.get("projects_notes", "") or "").strip()
    if "publications" in updates:
        publications = updates.get("publications", [])
        if not isinstance(publications, list):
            publications = []
        session.draft.publications = dedupe_strings(
            [str(item).strip() for item in publications if str(item).strip()]
        )


# Patterns shared by the experience/education parsers below. Defined at
# module scope so they're compiled once.
#
# Date tokens we accept inside headlines: 4-digit years, "Present",
# "Current", "Now", and month-name + year (Jan 2023, March 2024, etc.).
_DATE_TOKEN_RE = (
    r"(?:(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    r"[a-z]*\.?\s*\d{4}|\d{4}|Present|present|Current|current|Now|now)"
)
_DATE_RANGE_PATTERN = re.compile(
    rf"\b({_DATE_TOKEN_RE})\s*[\-–—]\s*({_DATE_TOKEN_RE})\b"
)
_PARENTHETICAL_DATES_PATTERN = re.compile(
    rf"\(\s*([^)]*{_DATE_TOKEN_RE}[^)]*?)\s*\)", re.IGNORECASE
)
_SINGLE_DATE_PATTERN = re.compile(rf"\b({_DATE_TOKEN_RE})\b")
_LEADING_FROM_PATTERN = re.compile(r"^\s*(?:from|since|in)\s+", re.IGNORECASE)
_TRAILING_FROM_PATTERN = re.compile(r"\s+(?:from|since|in)\s*$", re.IGNORECASE)
# Role transition markers users say when squashing two roles onto one line:
# "X at A 2020-Present, prior at B 2017-2020" / "Y at A then earlier at B"
_ROLE_TRANSITION_PATTERN = re.compile(
    r"\s*[,;\.]?\s*\b"
    r"(?:prior(?:ly)?|previously|previous(?:\s+role|\s+job|\s+position)?"
    r"|before(?:\s+that)?|earlier|formerly|then(?:\s+at)?)\b\s+",
    re.IGNORECASE,
)
# Common degree abbreviations + a couple of common spellings, used to detect
# multiple education entries on one line.
_DEGREE_PATTERN = re.compile(
    r"\b(?:B\.?S\.?c?|B\.?A\.?|B\.?Tech|B\.?E\.?|B\.?Eng|B\.?Sc"
    r"|M\.?S\.?c?|M\.?A\.?|M\.?Tech|M\.?B\.?A\.?|M\.?E\.?|M\.?Eng"
    r"|Ph\.?D|Doctorate|Diploma|Associate|Bachelor[s]?|Master[s]?)\b",
    re.IGNORECASE,
)
# Institution markers — words that, when present, almost certainly mark
# the institution part of an education chunk. Mirrors
# `INSTITUTION_KEYWORDS` in `src/services/profile_service.py`.
_INSTITUTION_KEYWORDS = (
    "university",
    "institute",
    "college",
    "school",
    "academy",
    "polytechnic",
    "iiit",
    "iit",
    "nit",
)


def _split_date_range_parts(date_text: str) -> tuple[str, str]:
    """Split "2020 - 2024" into ("2020", "2024"); single dates → (date, "")."""
    normalized = (date_text or "").strip()
    if not normalized:
        return "", ""
    parts = re.split(r"\s*[\-–—]\s*", normalized, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return normalized, ""


def _split_into_sentences(text: str) -> list[str]:
    """Split free-form prose on newlines AND sentence boundaries.

    Users may type the whole experience block as one paragraph
    ("Engineer at A 2020-Present. Built X. Reduced Y."). This expands
    such input into the sentences we then group into role blocks.
    """
    if not text:
        return []
    raw = re.split(r"(?<=[\.!?])\s+|\n+", str(text))
    return [chunk.strip(" \t-•") for chunk in raw if chunk.strip(" \t-•")]


def _looks_like_role_headline(line: str) -> bool:
    """Heuristic: does this sentence start a new role block?

    A headline typically contains " at " (Engineer at Acme), a 4-digit
    year (2024), a parenthetical date span, or pipe-separated columns.
    """
    if not line:
        return False
    stripped = line.strip()
    if stripped.startswith(("- ", "* ", "• ", "→ ")):
        return False
    if re.search(r"\bat\b", stripped, re.IGNORECASE):
        return True
    if re.search(r"\b(19|20)\d{2}\b", stripped):
        return True
    if "|" in stripped:
        return True
    return False


def _split_headline_on_transitions(headline: str) -> list[str]:
    """Break "X at A 2020-Present, prior at B 2017-2020" into two headlines.

    Returns the original headline (single-element list) if no transition
    markers are present. Splitting happens BEFORE the transition word so
    each fragment retains its own role context.
    """
    parts = _ROLE_TRANSITION_PATTERN.split(headline)
    cleaned = [part.strip(" ,;.-") for part in parts if part.strip(" ,;.-")]
    return cleaned or [headline]


def _split_into_role_blocks(notes: str) -> list[list[str]]:
    """Group sentences into role blocks of [headline, *bullets].

    Walks the sentences once: a sentence that looks like a headline
    starts a new block; non-headline sentences attach as bullets to the
    current block (or seed the first block if no headline came before).
    If the entire input collapsed to a single block, we try to detect
    multiple roles within the headline itself.
    """
    sentences = _split_into_sentences(notes)
    if not sentences:
        return []

    blocks: list[list[str]] = []
    current: list[str] = []
    for sentence in sentences:
        if _looks_like_role_headline(sentence):
            if current:
                blocks.append(current)
            current = [sentence]
        else:
            if current:
                current.append(sentence)
            else:
                # No headline yet — first sentence becomes the block's
                # headline so we don't lose content.
                current = [sentence]
    if current:
        blocks.append(current)

    if len(blocks) == 1 and blocks[0]:
        headline = blocks[0][0]
        bullets = blocks[0][1:]
        sub_headlines = _split_headline_on_transitions(headline)
        if len(sub_headlines) > 1:
            # First sub-role keeps the bullets that followed the original
            # headline; subsequent sub-roles start with no bullets since
            # we don't know which ones belonged to which role.
            blocks = [[sub_headlines[0]] + bullets]
            for sub in sub_headlines[1:]:
                blocks.append([sub])

    return blocks


def _extract_headline_dates(headline: str) -> tuple[str, str, str]:
    """Pull dates out of a role headline.

    Returns (cleaned_headline_without_dates, start, end). Dates can be:
    parenthetical ("(Jan 2023 - Present)"), an explicit range
    ("2020-2024"), or a single year ("2024").
    """
    cleaned = headline
    start = ""
    end = ""

    paren = _PARENTHETICAL_DATES_PATTERN.search(cleaned)
    if paren:
        start, end = _split_date_range_parts(paren.group(1).strip())
        cleaned = (cleaned[: paren.start()] + cleaned[paren.end():]).strip()

    if not start:
        rng = _DATE_RANGE_PATTERN.search(cleaned)
        if rng:
            start = rng.group(1).strip()
            end = rng.group(2).strip()
            cleaned = (cleaned[: rng.start()] + cleaned[rng.end():]).strip()

    if not start:
        single = _SINGLE_DATE_PATTERN.search(cleaned)
        if single:
            start = single.group(1).strip()
            cleaned = (cleaned[: single.start()] + cleaned[single.end():]).strip()

    cleaned = _LEADING_FROM_PATTERN.sub("", cleaned).strip()
    cleaned = _TRAILING_FROM_PATTERN.sub("", cleaned).strip()
    # Date extraction can leave punctuation residue ("Example Labs ." after
    # we lift "(Jan 2023 - Present)" out of "Example Labs (Jan 2023 - Present).").
    # Collapse those leftovers + any double whitespace before returning.
    cleaned = re.sub(r"\s+([,;.\-])", r"\1", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned)
    cleaned = cleaned.strip(" ,;.-")
    return cleaned, start, end


def _parse_experience_headline(headline: str) -> tuple[str, str, str, str]:
    """Extract (title, organization, start, end) from a role headline."""
    cleaned, start, end = _extract_headline_dates(headline)

    title = cleaned
    organization = ""

    # Match " at " with required surrounding whitespace OR a leading "at "
    # (e.g. transition-split sub-headlines like "at FinStart" — the leading
    # "at" has no whitespace before it after we trimmed the chunk).
    leading_at = re.match(r"^at\s+(.*)", cleaned, flags=re.IGNORECASE)
    if leading_at:
        title = ""
        organization = leading_at.group(1).strip(" ,;-")
    elif re.search(r"\s+at\s+", cleaned, re.IGNORECASE):
        parts = re.split(r"\s+at\s+", cleaned, maxsplit=1, flags=re.IGNORECASE)
        if len(parts) == 2:
            title = parts[0].strip(" ,;-")
            organization = parts[1].strip(" ,;-")
    elif "|" in cleaned:
        parts = [part.strip() for part in cleaned.split("|") if part.strip()]
        if parts:
            title = parts[0]
        if len(parts) > 1:
            organization = parts[1]
        if len(parts) > 2 and not start:
            start, end = _split_date_range_parts(parts[2])

    if not title and organization:
        # Headline was something like "at FinStart 2017-2020" — keep the
        # org but flag a fallback title so the renderer doesn't drop the
        # row.
        title = "Relevant Experience"
    return title or "Relevant Experience", organization, start, end


def _build_experience_entries(notes: str) -> list[WorkExperience]:
    blocks = _split_into_role_blocks(notes)
    if not blocks:
        return []

    entries: list[WorkExperience] = []
    for block in blocks:
        if not block:
            continue
        headline = block[0]
        bullets = [bullet for bullet in block[1:] if bullet]
        title, organization, start, end = _parse_experience_headline(headline)
        # description holds ONLY the explicit bullet sentences. Stuffing
        # the headline back into description (the previous behaviour)
        # caused it to render as both the meta line *and* a duplicated
        # bullet row in the resume.
        description = "\n".join(bullets).strip()
        entries.append(
            WorkExperience(
                title=title,
                organization=organization,
                description=description,
                start=start or None,
                end=end or None,
            )
        )
    return entries


def _split_education_into_chunks(notes: str) -> list[str]:
    """Split education notes so each chunk is one degree.

    Newlines are the primary boundary. If a single line names multiple
    degrees ("MS Computer Science Stanford 2017, BTech CS IIT Madras
    2015"), we split on commas and keep the chunks that carry their own
    degree pattern or year.
    """
    lines = _normalize_lines(notes)
    if not lines:
        return []

    chunks: list[str] = []
    for line in lines:
        if len(_DEGREE_PATTERN.findall(line)) <= 1:
            chunks.append(line)
            continue
        # Multi-degree line — split on commas / semicolons / sentence breaks.
        parts = [
            part.strip(" ,;.-")
            for part in re.split(r"\s*[,;]\s*|\.\s+", line)
            if part.strip(" ,;.-")
        ]
        for part in parts:
            looks_like_entry = bool(
                _DEGREE_PATTERN.search(part)
                or re.search(r"\b(19|20)\d{2}\b", part)
            )
            if looks_like_entry:
                chunks.append(part)
            elif chunks:
                # Continuation fragment ("Magna Cum Laude") – stick it onto
                # the previous chunk so we don't drop user-typed context.
                chunks[-1] = (chunks[-1] + ", " + part).strip(", ")
            else:
                chunks.append(part)
    return chunks


def _split_education_trailing_institution(text: str) -> tuple[str, str]:
    """Split a "field-of-study + institution" trailing fragment.

    Returns (field_of_study, institution). Tries three strategies in
    order:
      1. " from " connector — "Computer Science from Stanford".
      2. Institution keyword (university, institute, iit, ...) — finds
         the token that carries the keyword and keeps the proper-noun
         run that surrounds it ("CS IIT Madras" → "IIT Madras").
      3. Fallback: the LAST single word is treated as the institution
         (handles bare names like "Stanford", "Harvard", "MIT").
    """
    cleaned = text.strip(" ,;-")
    if not cleaned:
        return "", ""

    from_match = re.search(r"\s+from\s+", cleaned, flags=re.IGNORECASE)
    if from_match:
        field = cleaned[: from_match.start()].strip(" ,;-")
        institution = cleaned[from_match.end():].strip(" ,;-")
        return field, institution

    lowered = cleaned.lower()
    for keyword in _INSTITUTION_KEYWORDS:
        # `\b` keeps "iit" from matching inside "circuit"; still picks up
        # "IIT Madras" via the prefix variant.
        match = re.search(rf"\b{re.escape(keyword)}\b", lowered)
        if not match:
            continue
        keyword_start = match.start()
        keyword_end = match.end()
        # Walk backwards through capitalized words to find the institution's
        # leading edge — but only ONE word back, to avoid swallowing
        # multi-word fields of study ("Computer Science Stanford
        # University" → institution must be "Stanford University", not
        # "Computer Science Stanford University"). Short all-caps tokens
        # (CS, MS, BS, BA) are degree-field abbreviations, never an
        # institution prefix.
        prefix = cleaned[:keyword_start].rstrip()
        institution_start = keyword_start
        if prefix:
            tokens = prefix.split()
            if tokens:
                last = tokens[-1]
                if (
                    last
                    and last[0].isupper()
                    and not (last.isupper() and len(last) <= 3)
                ):
                    institution_start = cleaned.rfind(last, 0, keyword_start)
                    if institution_start < 0:
                        institution_start = keyword_start
        # Walk forwards: institutions often have a trailing proper-noun
        # qualifier ("IIT Madras", "University of Toronto", "Institute of
        # Science").
        suffix = cleaned[keyword_end:]
        institution_end = keyword_end
        if suffix:
            stripped = suffix.lstrip()
            offset = len(suffix) - len(stripped)
            tokens = stripped.split()
            extra: list[str] = []
            connectors = {"of", "for", "and", "the"}
            for token in tokens:
                if token.lower() in connectors and extra:
                    extra.append(token)
                    continue
                if token and (token[0].isupper() or token.lower() in connectors):
                    extra.append(token)
                else:
                    break
            if extra:
                joined = " ".join(extra)
                institution_end = (
                    keyword_end + offset + suffix.lstrip().find(joined) + len(joined)
                )
        institution = cleaned[institution_start:institution_end].strip(" ,;-")
        field = (
            (cleaned[:institution_start] + " " + cleaned[institution_end:])
            .strip(" ,;-")
        )
        return field, institution

    # Fallback: bare institution name (no keyword, no "from"). Last token
    # is almost always the institution ("MS Computer Science Stanford").
    tokens = cleaned.split()
    if len(tokens) >= 2:
        return " ".join(tokens[:-1]), tokens[-1]
    return "", cleaned


def _parse_education_chunk(chunk: str) -> tuple[str, str, str, str]:
    """Extract (institution, degree, start, end) from one education chunk."""
    cleaned, start, end = _extract_headline_dates(chunk)

    institution = cleaned
    degree = ""
    deg_match = _DEGREE_PATTERN.search(cleaned)
    if deg_match:
        # Strip ".," etc. on both sides — `\b` only matches at the END of
        # "B.E." after the "E", so the closing period leaks into `after`
        # ("B.E . Computer Science") unless we explicitly strip it here.
        before = cleaned[: deg_match.start()].strip(" ,;.-")
        after = cleaned[deg_match.end():].strip(" ,;.-")
        deg_token = deg_match.group(0).strip()
        if before:
            # "Stanford MS Computer Science" → institution=Stanford,
            # degree=MS Computer Science.
            institution = before
            degree = (deg_token + (" " + after if after else "")).strip()
        elif after:
            # Degree comes first, institution is the trailing fragment.
            field, institution_chunk = _split_education_trailing_institution(after)
            if institution_chunk:
                institution = institution_chunk
                degree = (deg_token + (" " + field if field else "")).strip()
            else:
                institution = after
                degree = deg_token
        else:
            institution = ""
            degree = deg_token
    elif "|" in cleaned:
        parts = [part.strip() for part in cleaned.split("|") if part.strip()]
        institution = parts[0] if parts else ""
        if len(parts) > 1:
            degree = parts[1]

    return institution.strip(), degree.strip(), start, end


def _build_education_entries(notes: str) -> list[EducationEntry]:
    chunks = _split_education_into_chunks(notes)
    if not chunks:
        return []

    entries: list[EducationEntry] = []
    for chunk in chunks:
        institution, degree, start, end = _parse_education_chunk(chunk)
        if not institution and not degree:
            continue
        entries.append(
            EducationEntry(
                institution=institution,
                degree=degree,
                start=start,
                end=end,
            )
        )
    return entries


def _coerce_str_value(value) -> str:
    """LLM payloads occasionally hand us None or numerics — normalize to str."""
    if value is None:
        return ""
    return str(value).strip()


def _coerce_bullet_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        text = _coerce_str_value(item)
        if text:
            cleaned.append(text)
    return cleaned


def _build_experience_entry_from_llm(item: dict) -> WorkExperience | None:
    """Convert one LLM-emitted role dict into a WorkExperience.

    Returns None for entries that are too sparse to render (no title and
    no organization). The structured renderer in `src/resume_builder.py`
    later splits the description (newline-joined bullets) back into a
    bullet list, mirroring the behaviour the regex parser produces.
    """
    if not isinstance(item, dict):
        return None
    title = _coerce_str_value(item.get("title"))
    organization = _coerce_str_value(item.get("organization"))
    if not title and not organization:
        return None
    bullets = _coerce_bullet_list(item.get("bullets"))
    description = "\n".join(bullets).strip()
    return WorkExperience(
        title=title or "Relevant Experience",
        organization=organization,
        location=_coerce_str_value(item.get("location")),
        description=description,
        start=_coerce_str_value(item.get("start")) or None,
        end=_coerce_str_value(item.get("end")) or None,
    )


def _build_education_entry_from_llm(item: dict) -> EducationEntry | None:
    """Convert one LLM-emitted degree dict into an EducationEntry."""
    if not isinstance(item, dict):
        return None
    institution = _coerce_str_value(item.get("institution"))
    degree = _coerce_str_value(item.get("degree"))
    if not institution and not degree:
        return None
    field = _coerce_str_value(item.get("field_of_study"))
    return EducationEntry(
        institution=institution,
        degree=degree,
        field_of_study=field,
        start=_coerce_str_value(item.get("start")),
        end=_coerce_str_value(item.get("end")),
    )


def _build_project_entry_from_llm(item: dict) -> ProjectEntry | None:
    """Convert one LLM-emitted project dict into a ProjectEntry."""
    if not isinstance(item, dict):
        return None
    name = _coerce_str_value(item.get("name"))
    if not name:
        return None
    bullets = _coerce_bullet_list(item.get("bullets"))
    technologies = _coerce_bullet_list(item.get("technologies"))
    return ProjectEntry(
        name=name,
        description=_coerce_str_value(item.get("description")),
        bullets=bullets,
        technologies=technologies,
        start=_coerce_str_value(item.get("start")),
        end=_coerce_str_value(item.get("end")),
        link=_coerce_str_value(item.get("link")),
    )


# URL detector for project links — covers github.com, vercel.app, .xyz, etc.
_PROJECT_LINK_PATTERN = re.compile(
    r"(?:https?://)?(?:[\w-]+\.)+[a-z]{2,}(?:/[^\s,;]*)?",
    re.IGNORECASE,
)


def _build_project_entries(notes: str) -> list[ProjectEntry]:
    """Regex fallback: split projects prose into one ProjectEntry per
    project. The LLM does this much better, but if the LLM is
    unavailable we still want SOME structure — at minimum one entry per
    bullet block separated by blank lines or sentence boundaries.

    Heuristic: each block becomes one project. The first line of a block
    is the project name (with link extracted if present); remaining
    lines become bullets.
    """
    if not notes or not notes.strip():
        return []

    # Split into blocks separated by double newlines or "Project: " markers.
    # Falls back to splitting on single newlines if no double newlines.
    blocks: list[str] = []
    if "\n\n" in notes:
        blocks = [b.strip() for b in notes.split("\n\n") if b.strip()]
    else:
        # Try one-line-per-project; if there's only one line, use it as one project.
        lines = [line.strip() for line in notes.splitlines() if line.strip()]
        # Group consecutive bullet lines (start with '-') under the prior name line.
        current: list[str] = []
        for line in lines:
            if line.startswith(("- ", "* ", "• ")):
                if current:
                    current.append(line.lstrip("-*• ").strip())
                else:
                    current = [line.lstrip("-*• ").strip()]
            else:
                if current:
                    blocks.append("\n".join(current))
                current = [line]
        if current:
            blocks.append("\n".join(current))

    entries: list[ProjectEntry] = []
    for block in blocks:
        block_lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not block_lines:
            continue
        headline = block_lines[0]
        bullets = block_lines[1:]
        # Extract link from headline if present.
        link = ""
        link_match = _PROJECT_LINK_PATTERN.search(headline)
        if link_match:
            link = link_match.group(0)
            headline = (
                headline[: link_match.start()] + headline[link_match.end():]
            ).strip(" -|,;")
        name = headline or "Project"
        entries.append(
            ProjectEntry(
                name=name,
                bullets=[b.lstrip("-*• ").strip() for b in bullets if b.strip()],
                link=link,
            )
        )
    return entries


def _structuring_signature(draft: ResumeBuilderDraft) -> str:
    """Stable hash of the inputs the structuring prompt sees.

    When this signature matches the one we cached on the session the
    LLM call is a no-op — we rebuild the entries from the cached
    payload. Any change to experience_notes / education_notes / draft
    context the prompt feeds the model invalidates the cache by
    yielding a different hash.

    Uses SHA256 (not for cryptographic strength — just for collision
    resistance over the input space we expect: a few KB of text).
    """
    payload = json.dumps(
        {
            "experience_notes": draft.experience_notes or "",
            "education_notes": draft.education_notes or "",
            "projects_notes": draft.projects_notes or "",
            "publications": list(draft.publications or []),
            "full_name": draft.full_name or "",
            "target_role": draft.target_role or "",
            "professional_summary": draft.professional_summary or "",
            "skills": sorted(draft.skills or []),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _experience_to_dict(entry: WorkExperience) -> dict:
    """asdict-style serialisation for cache storage. We dump WorkExperience
    via asdict() generally, but `start` / `end` may be dicts (date parts)
    so we coerce to the str/None contract the LLM payload uses."""
    return {
        "title": entry.title or "",
        "organization": entry.organization or "",
        "location": entry.location or "",
        "description": entry.description or "",
        "start": "" if entry.start is None else str(entry.start),
        "end": "" if entry.end is None else str(entry.end),
    }


def _education_to_dict(entry: EducationEntry) -> dict:
    return {
        "institution": entry.institution or "",
        "degree": entry.degree or "",
        "field_of_study": getattr(entry, "field_of_study", "") or "",
        "start": entry.start or "",
        "end": entry.end or "",
    }


def _experience_from_dict(payload: dict) -> WorkExperience | None:
    if not isinstance(payload, dict):
        return None
    title = str(payload.get("title", "") or "")
    organization = str(payload.get("organization", "") or "")
    if not title and not organization:
        return None
    start = str(payload.get("start", "") or "")
    end = str(payload.get("end", "") or "")
    return WorkExperience(
        title=title or "Relevant Experience",
        organization=organization,
        location=str(payload.get("location", "") or ""),
        description=str(payload.get("description", "") or ""),
        start=start or None,
        end=end or None,
    )


def _education_from_dict(payload: dict) -> EducationEntry | None:
    if not isinstance(payload, dict):
        return None
    institution = str(payload.get("institution", "") or "")
    degree = str(payload.get("degree", "") or "")
    if not institution and not degree:
        return None
    return EducationEntry(
        institution=institution,
        degree=degree,
        field_of_study=str(payload.get("field_of_study", "") or ""),
        start=str(payload.get("start", "") or ""),
        end=str(payload.get("end", "") or ""),
    )


def _project_to_dict(entry: ProjectEntry) -> dict:
    return {
        "name": entry.name or "",
        "description": entry.description or "",
        "bullets": list(entry.bullets or []),
        "technologies": list(entry.technologies or []),
        "start": entry.start or "",
        "end": entry.end or "",
        "link": entry.link or "",
    }


def _project_from_dict(payload: dict) -> ProjectEntry | None:
    if not isinstance(payload, dict):
        return None
    name = str(payload.get("name", "") or "")
    if not name:
        return None
    bullets_value = payload.get("bullets") or []
    technologies_value = payload.get("technologies") or []
    return ProjectEntry(
        name=name,
        description=str(payload.get("description", "") or ""),
        bullets=[str(item) for item in bullets_value if str(item).strip()],
        technologies=[str(item) for item in technologies_value if str(item).strip()],
        start=str(payload.get("start", "") or ""),
        end=str(payload.get("end", "") or ""),
        link=str(payload.get("link", "") or ""),
    )


def _structure_via_llm(
    session: ResumeBuilderSession,
    *,
    openai_service,
) -> tuple[list[WorkExperience], list[EducationEntry], list[ProjectEntry]] | None:
    """LLM-first conversion of free-form notes into structured entries.

    Mirrors the rest of the agent pipeline: the conversational intake
    captures user prose, then a structuring pass at generate / export
    time turns that prose into the same shape the JD-driven path would
    produce. Returns None on ANY failure (service unavailable, JSON
    malformed, payload missing keys, no usable entries) so the caller
    can fall back to the deterministic regex parsers.

    The fallback is essential — users without OpenAI keys, rate-limited
    requests, or transient model errors must still be able to render
    their resume. The regex parsers handle those cases correctly even
    if the output is less polished than the LLM rewrite.

    Caches the structured payload on the session keyed on a hash of the
    structuring prompt's inputs. A re-download (PDF after DOCX, theme
    switch, etc.) within the same session reuses the cached entries
    instead of re-calling the LLM and getting subtly different bullet
    wording.

    Returns a 3-tuple `(experience, education, projects)` — projects
    are part of the same structuring pass since they share the same
    bullet-rewrite-and-fact-preservation contract.
    """
    if openai_service is None or not getattr(openai_service, "is_available", lambda: False)():
        return None

    has_experience = bool(session.draft.experience_notes.strip())
    has_education = bool(session.draft.education_notes.strip())
    has_projects = bool(session.draft.projects_notes.strip())
    if not (has_experience or has_education or has_projects):
        # Nothing to structure — short-circuit to avoid burning a token
        # budget on an empty payload. Do NOT cache this state because a
        # subsequent edit might add prose; the next call will compute a
        # different signature and re-evaluate.
        return [], [], []

    current_signature = _structuring_signature(session.draft)
    if (
        session.structuring_signature
        and session.structuring_signature == current_signature
    ):
        # Cache hit — rebuild entries from stored payload. Stable
        # bullets across re-downloads and the LLM call we save is the
        # most expensive part of /generate and /export.
        cached_experience = [
            entry
            for entry in (
                _experience_from_dict(item)
                for item in session.structured_experience_payload
            )
            if entry is not None
        ]
        cached_education = [
            entry
            for entry in (
                _education_from_dict(item)
                for item in session.structured_education_payload
            )
            if entry is not None
        ]
        cached_projects = [
            entry
            for entry in (
                _project_from_dict(item)
                for item in session.structured_projects_payload
            )
            if entry is not None
        ]
        return cached_experience, cached_education, cached_projects

    prompt = build_resume_builder_structuring_prompt(draft=asdict(session.draft))
    try:
        # Schema-strict path: the structuring output is the biggest /
        # most fragile JSON in the workflow (multiple arrays + optional
        # categories + optional summary). Production runs through
        # ``run_structured_prompt`` so the model is constrained at
        # generation time to match ``ResumeBuilderStructuringOutput``.
        # Test fakes that only implement the legacy ``run_json_prompt``
        # still work via the ``hasattr`` shim below — the validation
        # then happens here in Python rather than at the API edge.
        if hasattr(openai_service, "run_structured_prompt"):
            structured = openai_service.run_structured_prompt(
                prompt["system"],
                prompt["user"],
                response_model=ResumeBuilderStructuringOutput,
                max_completion_tokens=get_openai_max_completion_tokens_for_task(
                    "resume_builder_structuring"
                ),
                task_name="resume_builder_structuring",
                allow_output_budget_retry=True,
            )
            payload = structured.model_dump()
        else:
            payload = openai_service.run_json_prompt(
                prompt["system"],
                prompt["user"],
                expected_keys=prompt["expected_keys"],
                temperature=None,
                max_completion_tokens=get_openai_max_completion_tokens_for_task(
                    "resume_builder_structuring"
                ),
                task_name="resume_builder_structuring",
                allow_output_budget_retry=True,
            )
    except Exception as exc:  # noqa: BLE001 — any LLM error → fallback
        log_event(
            LOGGER,
            logging.WARNING,
            "resume_builder_structuring_failed",
            "Resume builder structuring LLM call failed; falling back to regex parser.",
            session_id=session.session_id,
            error=str(exc),
        )
        return None

    if not isinstance(payload, dict):
        log_event(
            LOGGER,
            logging.WARNING,
            "resume_builder_structuring_invalid_payload",
            "Resume builder structuring returned non-dict payload; falling back to regex.",
            session_id=session.session_id,
            payload_type=type(payload).__name__,
        )
        return None

    experience_items = payload.get("experience")
    education_items = payload.get("education")
    projects_items = payload.get("projects")
    skill_categories_raw = payload.get("skill_categories")
    expanded_summary_raw = payload.get("professional_summary")

    experience_entries: list[WorkExperience] = []
    if isinstance(experience_items, list):
        for item in experience_items:
            entry = _build_experience_entry_from_llm(item)
            if entry is not None:
                experience_entries.append(entry)

    education_entries: list[EducationEntry] = []
    if isinstance(education_items, list):
        for item in education_items:
            entry = _build_education_entry_from_llm(item)
            if entry is not None:
                education_entries.append(entry)

    project_entries: list[ProjectEntry] = []
    if isinstance(projects_items, list):
        for item in projects_items:
            entry = _build_project_entry_from_llm(item)
            if entry is not None:
                project_entries.append(entry)

    # If the user typed prose for a section but the LLM returned nothing
    # parseable, treat that as a failure for THAT section so the regex
    # parser fills the gap. We don't fail the whole call — the LLM
    # might handle one section well and the other badly.
    if has_experience and not experience_entries:
        experience_entries = _build_experience_entries(session.draft.experience_notes)
    if has_education and not education_entries:
        education_entries = _build_education_entries(session.draft.education_notes)
    if has_projects and not project_entries:
        project_entries = _build_project_entries(session.draft.projects_notes)

    # Stash the structured result so re-downloads at a different theme
    # / format / page-load reuse identical bullets without re-calling
    # the LLM. The signature is what gates the next cache lookup; if
    # the user edits any of the prompt's input fields, the next
    # _structuring_signature() differs and we re-run.
    session.structured_experience_payload = [
        _experience_to_dict(entry) for entry in experience_entries
    ]
    session.structured_education_payload = [
        _education_to_dict(entry) for entry in education_entries
    ]
    session.structured_projects_payload = [
        _project_to_dict(entry) for entry in project_entries
    ]
    # Skill categories are stored on the session (not returned in the
    # tuple) — _synthesize_resume_builder_artifact reads them after
    # build_tailored_resume_artifact and assigns to artifact.skill_categories.
    # Validate shape before caching: dict[str, list[str]], every skill
    # in the buckets must appear in the user's flat skills list (defends
    # against the LLM inventing categories with new tech).
    session.structured_skill_categories = _sanitize_skill_categories(
        skill_categories_raw, session.draft.skills or []
    )
    # Summary expansion is opt-in by the LLM — only stored when the
    # model emits a non-empty replacement and it's actually longer than
    # what the user typed (defends against the model summarising
    # downward by accident).
    expanded_summary = (str(expanded_summary_raw or "") or "").strip()
    user_summary_len = len((session.draft.professional_summary or "").strip())
    if expanded_summary and len(expanded_summary) > user_summary_len:
        session.structured_professional_summary = expanded_summary
    else:
        session.structured_professional_summary = ""
    session.structuring_signature = current_signature

    return experience_entries, education_entries, project_entries


def _sanitize_skill_categories(
    raw, allowed_skills: list[str]
) -> dict[str, list[str]]:
    """Validate the LLM's skill_categories payload against the user's
    flat skill list. Drops any skill the LLM invented; drops empty
    buckets; preserves user casing where possible.

    Returns {} on any structural problem so the renderer falls back to
    the flat list cleanly.
    """
    if not isinstance(raw, dict):
        return {}
    # Build a case-insensitive lookup of allowed skills, mapping lowercase
    # back to the user's original casing.
    canon = {str(s).lower().strip(): str(s).strip() for s in allowed_skills if str(s).strip()}
    if not canon:
        return {}
    cleaned: dict[str, list[str]] = {}
    for label, items in raw.items():
        if not isinstance(label, str) or not label.strip():
            continue
        if not isinstance(items, list):
            continue
        bucket: list[str] = []
        for item in items:
            key = str(item or "").lower().strip()
            if key in canon:
                bucket.append(canon[key])
        if bucket:
            cleaned[label.strip()] = bucket
    return cleaned


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

    if draft.projects_notes:
        sections.append("")
        sections.append("## Projects")
        sections.extend(_normalize_lines(draft.projects_notes))

    sections.append("")
    sections.append("## Education")
    if draft.education_notes:
        sections.extend(_normalize_lines(draft.education_notes))
    else:
        sections.append("- Add your education details here.")

    if draft.publications:
        sections.append("")
        sections.append("## Publications")
        sections.extend(f"- {publication}" for publication in draft.publications)

    if draft.certifications:
        sections.append("")
        sections.append("## Certifications")
        sections.extend(f"- {certification}" for certification in draft.certifications)

    return "\n".join(sections).strip()


def _build_candidate_profile_and_resume(
    session: ResumeBuilderSession,
    *,
    openai_service=None,
) -> tuple[ResumeDocument, CandidateProfile]:
    """Compose the rendered resume + structured CandidateProfile.

    Tries the LLM structuring pass first when an `openai_service` is
    provided; falls back to the deterministic regex parsers when the
    service is unavailable or the structured output couldn't be
    parsed. Either way the call returns the same `(ResumeDocument,
    CandidateProfile)` shape, so route handlers don't need to know
    which path produced the entries.
    """
    markdown = _build_resume_markdown(session.draft)
    plain_text = markdown_to_text(markdown, strip_bold=True)
    session.generated_resume_markdown = markdown
    session.generated_resume_plain_text = plain_text

    structured = _structure_via_llm(session, openai_service=openai_service)
    if structured is not None:
        experience_entries, education_entries, project_entries = structured
    else:
        experience_entries = _build_experience_entries(session.draft.experience_notes)
        education_entries = _build_education_entries(session.draft.education_notes)
        project_entries = _build_project_entries(session.draft.projects_notes)

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
        experience=experience_entries,
        education=education_entries,
        certifications=session.draft.certifications,
        projects=project_entries,
        publications=list(session.draft.publications or []),
        source_signals=dedupe_strings(
            [
                "Profile created with the resume builder assistant.",
                f"Target role: {session.draft.target_role}" if session.draft.target_role else "",
                "Experience notes captured through guided intake." if session.draft.experience_notes else "",
                "Skills were confirmed by the user." if session.draft.skills else "",
                "Projects captured through guided intake." if session.draft.projects_notes else "",
                "Publications captured through guided intake." if session.draft.publications else "",
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
            # Persist the structuring cache so a container restart
            # doesn't force a re-call to the LLM (which would also
            # subtly rewrite the bullets). Drops gracefully if the
            # session was saved before this field existed.
            "structuring_signature": session.structuring_signature,
            "structured_experience_payload": list(
                session.structured_experience_payload or []
            ),
            "structured_education_payload": list(
                session.structured_education_payload or []
            ),
            "structured_projects_payload": list(
                session.structured_projects_payload or []
            ),
            "structured_skill_categories": dict(
                session.structured_skill_categories or {}
            ),
            "structured_professional_summary": (
                session.structured_professional_summary or ""
            ),
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
            projects_notes=str(draft_payload.get("projects_notes", "") or ""),
            publications=[
                str(item).strip()
                for item in draft_payload.get("publications", [])
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
        structuring_signature=str(
            raw_payload.get("structuring_signature", "") or ""
        ),
        structured_experience_payload=[
            item
            for item in (raw_payload.get("structured_experience_payload") or [])
            if isinstance(item, dict)
        ],
        structured_education_payload=[
            item
            for item in (raw_payload.get("structured_education_payload") or [])
            if isinstance(item, dict)
        ],
        structured_projects_payload=[
            item
            for item in (raw_payload.get("structured_projects_payload") or [])
            if isinstance(item, dict)
        ],
        structured_skill_categories=(
            raw_payload.get("structured_skill_categories") or {}
            if isinstance(raw_payload.get("structured_skill_categories"), dict)
            else {}
        ),
        structured_professional_summary=str(
            raw_payload.get("structured_professional_summary", "") or ""
        ),
    )
    _SESSIONS[session.session_id] = session
    return _serialize_session(session)


def has_resume_builder_session(session_id: str) -> bool:
    return str(session_id or "").strip() in _SESSIONS


def start_resume_builder_session(
    *,
    access_token: str = "",
    refresh_token: str = "",
):
    """Begin a new resume-builder intake.

    Quota gate (Step 5 of tier-enforcement):
      `resume_builder_sessions` is the special case from the brief:
        Free  -> lifetime counter, cap 1   (one onboarding ever)
        Pro   -> monthly counter,  cap 3
        Business -> monthly counter, cap 15
      We pass `lifetime=True` to `check_and_increment` ONLY when
      `tier == "free"`. Other tiers fall through to the default
      monthly period_key. The credit is consumed on session creation
      (not per intake turn) so users can chat freely once they're in.

    Failure refund: if the in-memory session insert fails we
    refund. Realistically this can only fail if the in-process
    dict mutation raises (e.g. interpreter shutdown) -- the gate
    pattern is here for consistency with the rest of the series.

    Anonymous flow: when no auth tokens are passed the gate skips
    and the session is created without any credit being charged.
    Anonymous resume-builder usage was already the existing
    pre-quota behavior; we preserve it.
    """
    auth_context = None
    if access_token and refresh_token:
        auth_context = resolve_authenticated_context(
            access_token=access_token,
            refresh_token=refresh_token,
        )

    app_user = getattr(auth_context, "app_user", None) if auth_context is not None else None
    tier = resolve_user_tier(app_user)
    quota_user_id = str(getattr(app_user, "id", "") or "") if app_user is not None else ""
    # Lifetime ONLY on Free -- Pro and Business get monthly slots.
    lifetime = tier == "free"
    quota_consumed = False
    if quota_user_id:
        quota.check_and_increment(
            "resume_builder_sessions",
            quota_user_id,
            tier,
            lifetime=lifetime,
        )
        quota_consumed = True

    try:
        session = ResumeBuilderSession(session_id=str(uuid4()))
        _SESSIONS[session.session_id] = session
        return _serialize_session(session)
    except BaseException:
        if quota_consumed:
            try:
                quota.refund(
                    "resume_builder_sessions",
                    quota_user_id,
                    tier,
                    lifetime=lifetime,
                )
            except Exception:  # noqa: BLE001 - refund is best-effort
                log_event(
                    LOGGER,
                    logging.WARNING,
                    "resume_builder_session_quota_refund_failed",
                    "Refund after resume-builder session creation failure "
                    "raised; user credit was not restored.",
                    counter="resume_builder_sessions",
                    user_id=quota_user_id,
                    tier=tier,
                    lifetime=lifetime,
                )
        raise


_VALID_STATUSES = {"collecting", "reviewing", "ready"}


def _coerce_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _augment_full_name_from_message(
    session: ResumeBuilderSession, user_message: str
) -> None:
    """Safety net for LLM full_name truncation.

    The LLM intake sometimes captures only the first token of a
    multi-word name when the user squashes everything onto one line
    ("Priya Sharma, Bangalore. priya@gmail.com" → 'Priya'). This helper
    looks at the user's literal message; if its first chunk is a
    longer, valid-looking name that starts with what the LLM captured,
    we promote the longer version. Prefix-only check so we don't
    overwrite an LLM correction (e.g., user later says "actually it's
    Maya Sharma").
    """
    llm_name = (session.draft.full_name or "").strip()
    if not llm_name:
        return

    text = str(user_message or "").strip()
    if not text:
        return

    # First sentence-or-comma chunk of the user's literal message.
    first_chunk = re.split(r"[\n,;|.!?]", text, maxsplit=1)[0].strip()
    first_chunk = _NAME_PREAMBLE_PATTERN.sub("", first_chunk).strip()
    if not first_chunk or first_chunk == llm_name:
        return

    # Only promote when the LLM's name is a strict prefix of the literal
    # chunk AND the literal chunk passes our name-shape heuristic. The
    # prefix gate prevents accidentally overwriting an LLM correction
    # ("user typed 'Priya Sharma' but really meant 'Maya Sharma'") —
    # if the literal chunk doesn't start with what the LLM captured,
    # we trust the LLM's read.
    lower_chunk = first_chunk.lower()
    lower_llm = llm_name.lower()
    if not lower_chunk.startswith(lower_llm):
        return
    # Require a whole-word match — guards against "Pri" vs "Priya Sharma".
    boundary_index = len(llm_name)
    if boundary_index < len(first_chunk):
        next_char = first_chunk[boundary_index]
        if next_char.isalnum():
            return
    if not _looks_like_personal_name(first_chunk):
        return

    session.draft.full_name = first_chunk


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
    if "projects_notes" in updates:
        session.draft.projects_notes = str(
            updates.get("projects_notes") or ""
        ).strip()
    if "publications" in updates:
        session.draft.publications = dedupe_strings(
            _coerce_string_list(updates.get("publications"))
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
        # Deliberate fast-fail, consistent with the assistant: this is
        # an interactive turn with a graceful regex fallback (see the
        # `resume_builder_llm_fallback` except path). The heavier
        # structuring pass that emits the big JSON is a SEPARATE call
        # already budgeted generously (resume_builder_structuring=4000),
        # so the conversational turn doesn't carry the parser-style
        # silent-corruption risk. Revisit only as a product decision.
        allow_output_budget_retry=False,
    )

    draft_updates = payload.get("draft_updates")
    if isinstance(draft_updates, dict):
        _apply_llm_draft_updates(session, draft_updates)
        # Safety net: if the LLM dropped a surname when the user clearly
        # typed a full name, recover it from the literal message before
        # downstream rendering bakes "Priya" into a resume header.
        if "full_name" in draft_updates:
            _augment_full_name_from_message(session, user_message)

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


def generate_resume_builder_resume(*, session_id: str, openai_service=None):
    session = _SESSIONS.get(str(session_id or "").strip())
    if session is None:
        raise ValueError("Resume builder session not found.")

    resume_document, candidate_profile = _build_candidate_profile_and_resume(
        session,
        openai_service=openai_service,
    )
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


def commit_resume_builder_session(*, session_id: str, openai_service=None):
    session = _SESSIONS.get(str(session_id or "").strip())
    if session is None:
        raise ValueError("Resume builder session not found.")

    resume_document, candidate_profile = _build_candidate_profile_and_resume(
        session,
        openai_service=openai_service,
    )
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
    openai_service=None,
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
    _, candidate_profile = _build_candidate_profile_and_resume(
        session,
        openai_service=openai_service,
    )

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

    # Skill categories are produced by _structure_via_llm and cached on
    # the session. The artifact builder doesn't know about them, so we
    # paint them on after the fact. The renderer prefers categories
    # over the flat highlighted_skills list when present.
    if session.structured_skill_categories:
        artifact.skill_categories = dict(session.structured_skill_categories)
    # Same pattern for the expanded summary — only override when the
    # structuring pass produced one (otherwise keep what the artifact
    # builder set from the user's verbatim summary).
    if session.structured_professional_summary:
        artifact.professional_summary = session.structured_professional_summary
        artifact.summary = session.structured_professional_summary

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
    openai_service=None,
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

    artifact = _synthesize_resume_builder_artifact(
        session,
        theme=normalized_theme,
        openai_service=openai_service,
    )

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
