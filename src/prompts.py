import json
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, Iterable

from src.schemas import (
    CandidateProfile,
    FitAnalysis,
    JobDescription,
    ReviewAgentOutput,
    TailoredResumeDraft,
    TailoringAgentOutput,
)


def _to_serializable(value: Any):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {key: _to_serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_serializable(item) for item in value]
    return value


def _json_block(label: str, value: Any) -> str:
    payload = json.dumps(_to_serializable(value), indent=2, default=str)
    return "{label}:\n{payload}".format(label=label, payload=payload)


def _truncate_text(value: Any, max_chars: int) -> str:
    text = str(value or "")
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    if max_chars <= 16:
        return text[:max_chars]
    return text[: max_chars - 16].rstrip() + "...[truncated]"


def _compact_prompt_value(value: Any, *, max_string_chars: int, max_list_items: int):
    serializable = _to_serializable(value)
    if isinstance(serializable, dict):
        return {
            key: _compact_prompt_value(
                item,
                max_string_chars=max_string_chars,
                max_list_items=max_list_items,
            )
            for key, item in serializable.items()
        }
    if isinstance(serializable, list):
        return [
            _compact_prompt_value(
                item,
                max_string_chars=max_string_chars,
                max_list_items=max_list_items,
            )
            for item in serializable[:max_list_items]
        ]
    if isinstance(serializable, tuple):
        return [
            _compact_prompt_value(
                item,
                max_string_chars=max_string_chars,
                max_list_items=max_list_items,
            )
            for item in serializable[:max_list_items]
        ]
    if isinstance(serializable, str):
        return _truncate_text(serializable, max_string_chars)
    return serializable


def _json_block_with_budget(label: str, value: Any, *, max_chars: int) -> tuple[str, Dict[str, Any]]:
    serialized_value = _to_serializable(value)
    original_payload = json.dumps(serialized_value, indent=2, default=str)
    payload = original_payload
    compacted = False

    if len(payload) > max_chars:
        compacted = True
        for max_string_chars, max_list_items in (
            (600, 12),
            (420, 8),
            (280, 6),
            (180, 4),
            (120, 3),
        ):
            compacted_value = _compact_prompt_value(
                serialized_value,
                max_string_chars=max_string_chars,
                max_list_items=max_list_items,
            )
            payload = json.dumps(compacted_value, indent=2, default=str)
            if len(payload) <= max_chars:
                break

        if len(payload) > max_chars:
            payload = json.dumps(
                {
                    "summary": "Section compacted to stay within the prompt budget.",
                    "preview": _truncate_text(payload, min(max_chars, 600)),
                },
                indent=2,
                default=str,
            )

    return (
        "{label}:\n{payload}".format(label=label, payload=payload),
        {
            "label": label,
            "original_chars": len(original_payload),
            "final_chars": len(payload),
            "compacted": compacted,
        },
    )


def _build_budgeted_user_prompt(sections: Iterable[tuple[str, Any, int]]) -> tuple[str, Dict[str, str]]:
    blocks = []
    stats = []
    for label, value, max_chars in sections:
        block, stat = _json_block_with_budget(label, value, max_chars=max_chars)
        blocks.append(block)
        stats.append(stat)

    user_prompt = "\n\n".join(blocks)
    compacted_labels = [stat["label"] for stat in stats if stat["compacted"]]
    metadata = {
        "estimated_input_chars": str(len(user_prompt)),
        "compacted_sections": str(len(compacted_labels)),
        "prompt_budget_mode": "compacted" if compacted_labels else "full",
    }
    if compacted_labels:
        metadata["compacted_labels"] = ", ".join(compacted_labels)
    return user_prompt, metadata


def _build_contract(contract: Dict[str, str]) -> str:
    lines = ["Return JSON only with exactly these keys:"]
    for key, description in contract.items():
        lines.append('- "{key}": {description}'.format(key=key, description=description))
    return "\n".join(lines)


def build_tailoring_agent_prompt(
    candidate_profile: CandidateProfile,
    job_description: JobDescription,
    fit_analysis: FitAnalysis,
    tailored_draft: TailoredResumeDraft,
) -> Dict[str, Any]:
    """Build the TailoringAgent prompt.

    Note: a previous version of this prompt also included the
    FitAgent's narrated 'top matches / key gaps' as an extra context
    block. That agent has been removed — TailoringAgent now reads the
    structured FitAnalysis directly (matched_hard_skills, gaps,
    recommendations etc. are all there in structured form). One
    fewer LLM call per workspace analysis with no quality regression.
    """
    contract = {
        "professional_summary": "3-4 sentence tailored summary using only grounded claims",
        "rewritten_bullets": "array of 3-5 tailored bullet ideas",
        "highlighted_skills": "array of 4-8 skills to foreground",
        "cover_letter_themes": "array of 2-4 cover-letter talking points",
    }
    sections = [
        ("Candidate Profile", candidate_profile, 2200),
        ("Job Description", job_description, 1800),
        ("Deterministic Fit Analysis", fit_analysis, 1600),
        ("Deterministic Tailored Draft", tailored_draft, 1800),
    ]
    user_prompt, metadata = _build_budgeted_user_prompt(sections)
    return {
        "system": (
            "You are the Tailoring Agent. Improve the deterministic draft without inventing facts. "
            "If evidence is weak, write conservatively and note transferable alignment instead of exaggerating. "
            + _build_contract(contract)
        ),
        "user": user_prompt,
        "expected_keys": list(contract.keys()),
        "metadata": metadata,
    }


def build_review_agent_prompt(
    candidate_profile: CandidateProfile,
    job_description: JobDescription,
    fit_analysis: FitAnalysis,
    tailored_draft: TailoredResumeDraft,
    tailoring_output: TailoringAgentOutput,
) -> Dict[str, Any]:
    contract = {
        "approved": "boolean flag that must be true when the final outputs are safe to use after applying any review corrections; false only when unresolved issues still remain after review",
        "grounding_issues": "array of 0-4 unsupported or weakly supported claims found in the incoming tailoring draft before review corrections",
        "unresolved_issues": "array of 0-4 issues that still remain after review corrections are applied; return an empty array when the corrected outputs are safe to use",
        "revision_requests": "array of 0-4 concise correction notes or fixes that were needed",
        "final_notes": "array of 1-3 final quality notes",
        "corrected_tailoring": "null when no tailoring changes are needed; otherwise an object matching the Tailoring Agent contract after review corrections are applied",
    }
    sections = [
        ("Candidate Profile", candidate_profile, 2000),
        ("Job Description", job_description, 1600),
        ("Deterministic Fit Analysis", fit_analysis, 1600),
        ("Deterministic Tailored Draft", tailored_draft, 1800),
        ("Tailoring Agent Output", tailoring_output, 1400),
    ]
    user_prompt, metadata = _build_budgeted_user_prompt(sections)
    return {
        "system": (
            "You are the Review Agent. Your job is to reject embellishment and unsupported claims, then directly repair the tailoring output when fixes are straightforward. "
            "Approve when the final corrected wording stays grounded in the source profile and deterministic analysis, even if the incoming draft had issues that you fixed. "
            "Set approved to false only when unresolved issues remain after your corrections. "
            "Return null for corrected_tailoring when the current output is already acceptable or when no change is needed. "
            + _build_contract(contract)
        ),
        "user": user_prompt,
        "expected_keys": list(contract.keys()),
        "metadata": metadata,
    }


def build_resume_generation_agent_prompt(
    candidate_profile: CandidateProfile,
    job_description: JobDescription,
    fit_analysis: FitAnalysis,
    tailored_draft: TailoredResumeDraft,
    tailoring_output: TailoringAgentOutput,
    review_output: ReviewAgentOutput = None,
) -> Dict[str, Any]:
    contract = {
        "professional_summary": "2-4 sentence final summary for the tailored resume using only grounded claims",
        "highlighted_skills": "array of 4-8 skills to surface in the tailored resume",
        "experience_bullets": "array of 3-6 grounded experience bullets for the tailored resume",
        "section_order": "array describing preferred section order for the resume",
        "template_hint": "set this to classic_ats",
    }
    sections = [
        ("Candidate Profile", candidate_profile, 1800),
        ("Job Description", job_description, 1500),
        ("Deterministic Fit Analysis", fit_analysis, 1500),
        ("Deterministic Tailored Draft", tailored_draft, 1800),
        ("Tailoring Agent Output", tailoring_output, 1400),
    ]
    user_prompt, metadata = _build_budgeted_user_prompt(sections)
    return {
        "system": (
            "You are the Resume Generation Agent. Produce the final tailored resume content from grounded upstream analysis. "
            "You may rewrite, reorder, and emphasize, but you must not invent employers, achievements, dates, metrics, or unsupported skills. "
            "Write in standard resume style: no first-person or third-person pronouns, no full-name self-reference inside the summary or bullets, and no cover-letter phrasing. "
            "Keep the output ATS-safe and recruiter-readable. "
            + _build_contract(contract)
        ),
        "user": user_prompt,
        "expected_keys": list(contract.keys()),
        "metadata": metadata,
    }


def build_cover_letter_agent_prompt(
    candidate_profile: CandidateProfile,
    job_description: JobDescription,
    fit_analysis: FitAnalysis,
    tailored_draft: TailoredResumeDraft,
    tailoring_output: TailoringAgentOutput,
    review_output: ReviewAgentOutput = None,
    resume_generation_output=None,
) -> Dict[str, Any]:
    contract = {
        "greeting": "salutation such as Dear Hiring Team",
        "opening_paragraph": "2-4 sentence opening paragraph grounded in the approved workflow outputs",
        "body_paragraphs": "array of 1-3 grounded body paragraphs connecting evidence to the role",
        "closing_paragraph": "1-2 sentence closing paragraph with grounded enthusiasm and next-step language",
        "signoff": "closing signoff such as Sincerely",
        "signature_name": "candidate name for the signature line",
    }
    sections = [
        ("Candidate Profile", candidate_profile, 1800),
        ("Job Description", job_description, 1500),
        ("Deterministic Fit Analysis", fit_analysis, 1400),
        ("Deterministic Tailored Draft", tailored_draft, 1600),
        ("Approved Tailoring Output", tailoring_output, 1400),
    ]
    if review_output:
        sections.append(("Review Output", review_output, 1200))
    if resume_generation_output:
        sections.append(("Resume Generation Output", resume_generation_output, 1200))
    user_prompt, metadata = _build_budgeted_user_prompt(sections)
    return {
        "system": (
            "You are the Cover Letter Agent. Write a recruiter-facing cover letter only after the review stage has approved or corrected the upstream outputs. "
            "Write entirely in first person from the candidate's perspective. "
            "Do not describe the candidate as he, she, him, his, her, or by full name anywhere in the letter body; reserve the candidate name for the signature line only. "
            "Use the approved tailoring, review, and resume-generation context as the source of truth. "
            "Do not invent employers, metrics, projects, technologies, or direct experience that are not supported by the provided inputs. "
            "Keep the result specific to the role, grounded, and ready for packaging into the final artifact. "
            + _build_contract(contract)
        ),
        "user": user_prompt,
        "expected_keys": list(contract.keys()),
        "metadata": metadata,
    }


def build_assistant_prompt(
    assistant_context: Dict[str, Any],
    question: str,
    history: Any = None,
) -> Dict[str, Any]:
    contract = {
        "answer": "short, direct grounded answer that can explain product behavior, saved workspace behavior, or the user's current application outputs",
        "sources": "array of 1-4 relevant pages, artifacts, or workflow signals used for the answer",
        "suggested_follow_ups": "array of 0-3 follow-up questions the user may want to ask next",
    }
    user_prompt = "\n\n".join(
        [
            _json_block("Assistant Context", assistant_context),
            _json_block("User Question", {"question": question}),
        ]
        + ([_json_block("Recent History", history[-4:])] if history else [])
    )
    return {
        "system": (
            "You are the in-app assistant for an AI job application app. "
            "Stay strictly within scope: the job application product and the user's current workspace artifacts (resume, job description, fit analysis, tailored resume, cover letter). "
            "If the user asks for entertainment recommendations (movies, books, music, shows, restaurants), lifestyle advice, jokes, opinions on unrelated topics, or anything outside the job application domain, decline in one short sentence and redirect to job application help — even if you could plausibly answer. "
            "When refusing an off-topic ask: do NOT name specific titles, authors, or artists; do NOT offer to suggest one based on genre, mood, or any other angle; do NOT acknowledge the off-topic premise beyond a brief decline. The refusal must not engage with the off-topic question. "
            "You answer both product questions and grounded questions about the user's current package in one conversation. "
            "Explain only features and artifacts that are present in the provided context. "
            "Use retrieved product knowledge hits when they are provided, but treat runtime session context as authoritative for current state such as quotas, page availability, saved workspace behavior, and active artifacts. "
            "If the user asks about navigation, explain the current sidebar pages and signed-in actions from the provided context. "
            "If the user asks about the current resume, cover letter, report, or fit analysis, ground the answer in the workflow context and say directly when evidence is weak or unavailable. "
            "If the user asks for broader resume or application coaching, you may provide general advice, but anchor it back to the current package when possible and separate general guidance from context-specific recommendations when helpful. "
            "If the user asks about limits, tokens, quota, warnings, or fallback behavior, explain the signed-in account-level daily quota using the provided context and do not describe any browser-session budget model. "
            "If the user asks who you are or what your name is, answer as the in-app assistant for this product. "
            + _build_contract(contract)
        ),
        "user": user_prompt,
        "expected_keys": list(contract.keys()),
    }


def build_assistant_text_prompt(
    assistant_context: Dict[str, Any],
    question: str,
    history: Any = None,
) -> Dict[str, Any]:
    """Plain-prose variant of ``build_assistant_prompt`` for the SSE
    streaming endpoint.

    Same context, same grounding rules, but instructs the model to
    return prose only (no JSON contract) so the response can be
    streamed token-by-token. Sources and follow-up suggestions are
    computed deterministically from the workspace snapshot in the
    streaming caller (see ``stream_workspace_question``).
    """
    user_prompt = "\n\n".join(
        [
            _json_block("Assistant Context", assistant_context),
            _json_block("User Question", {"question": question}),
        ]
        + ([_json_block("Recent History", history[-4:])] if history else [])
    )
    return {
        "system": (
            "You are the in-app assistant for an AI job application app. "
            "Stay strictly within scope: the job application product and the user's current workspace artifacts (resume, job description, fit analysis, tailored resume, cover letter). "
            "If the user asks for entertainment recommendations (movies, books, music, shows, restaurants), lifestyle advice, jokes, opinions on unrelated topics, or anything outside the job application domain, decline in one short sentence and redirect to job application help — even if you could plausibly answer. "
            "When refusing an off-topic ask: do NOT name specific titles, authors, or artists; do NOT offer to suggest one based on genre, mood, or any other angle; do NOT acknowledge the off-topic premise beyond a brief decline. The refusal must not engage with the off-topic question. "
            "You answer both product questions and grounded questions about the user's current package in one conversation. "
            "Explain only features and artifacts that are present in the provided context. "
            "Use retrieved product knowledge hits when they are provided, but treat runtime session context as authoritative for current state such as quotas, page availability, saved workspace behavior, and active artifacts. "
            "If the user asks about navigation, explain the current sidebar pages and signed-in actions from the provided context. "
            "If the user asks about the current resume, cover letter, report, or fit analysis, ground the answer in the workflow context and say directly when evidence is weak or unavailable. "
            "If the user asks for broader resume or application coaching, you may provide general advice, but anchor it back to the current package when possible and separate general guidance from context-specific recommendations when helpful. "
            "If the user asks about limits, tokens, quota, warnings, or fallback behavior, explain the signed-in account-level daily quota using the provided context and do not describe any browser-session budget model. "
            "If the user asks who you are or what your name is, answer as the in-app assistant for this product. "
            "Respond as a concise, direct prose answer. Do not return JSON, do not wrap the answer in code fences, and do not list sources — sources are surfaced separately by the app."
        ),
        "user": user_prompt,
    }


def build_assistant_followup_prompt(
    question: str,
    *,
    assistant_scope: str = "assistant",
    state_updates: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    contract = {
        "answer": "short, direct grounded answer to the user's latest question",
        "sources": "array of 1-4 relevant pages, artifacts, or workflow signals used for the answer",
        "suggested_follow_ups": "array of 0-3 useful next questions",
    }
    user_sections = [
        _json_block("User Question", {"question": question}),
    ]
    if state_updates:
        user_sections.append(_json_block("State Updates", state_updates))
    return {
        "system": (
            "You are continuing an in-app assistant conversation for an AI job application app. "
            "Stay strictly within scope: the job application product and the user's current workspace artifacts. "
            "If the user asks for entertainment recommendations, lifestyle advice, or anything outside the job application domain, decline in one short sentence and redirect — do not name specific titles, do not offer to suggest based on genre or mood, do not engage with the off-topic premise. "
            "Use the existing conversation state as the primary memory for this session. "
            "Use any provided state updates to refresh your understanding of the current page, product state, or workspace artifacts. "
            "Keep answers grounded, concise, and directly useful. "
            "If the question is about the current workspace, stay tied to the current fit, tailored resume, and cover letter context already established in the session. "
            "If the question is product-help oriented, explain only features and behavior that match the current product. "
            "Current assistant scope: {scope}. ".format(scope=assistant_scope)
            + _build_contract(contract)
        ),
        "user": "\n\n".join(user_sections),
        "expected_keys": list(contract.keys()),
    }


_RESUME_BUILDER_FIELD_DESCRIPTIONS = {
    "full_name": (
        "candidate's full name as they typed it — capture EVERY name "
        "token (first, middle, last, suffix). Don't drop a surname just "
        "because the user packed location or contact info onto the same "
        "line ('Priya Sharma, Bangalore. priya@gmail.com' → "
        "full_name='Priya Sharma', NOT 'Priya')."
    ),
    "location": "city / region / 'Remote'",
    "contact_lines": "list of contact entries: emails, phones, links",
    "target_role": "the SHORT role title the candidate is targeting",
    "professional_summary": (
        "1-3 sentence headline of the candidate's professional identity. "
        "Self-descriptions like 'Senior backend engineer with 5 years on "
        "distributed Python systems' belong here — NOT in experience_notes. "
        "Capture even when the user phrases it in first person; downstream "
        "rendering rephrases to third-person ATS voice."
    ),
    "experience_notes": (
        "Specific past roles only — company names, titles, date ranges, "
        "impact bullets. Do NOT put broad self-descriptions or summary-style "
        "language here; that goes in professional_summary."
    ),
    "education_notes": "degrees, institutions, dates",
    "skills": "list of tools / technologies / strengths",
    "certifications": "optional list of credentials / specializations",
    "projects_notes": (
        "OPTIONAL — side projects, open-source work, or portfolio pieces "
        "the candidate wants on the resume. Capture verbatim user prose "
        "(name, link, what it does, tech used, outcomes). Skip this field "
        "for candidates without a tech-heavy background or no projects to "
        "share — never push for one if they don't mention any."
    ),
    "publications": (
        "OPTIONAL — academic publications, papers, or conference talks. "
        "List of citation strings. Skip this field unless the candidate "
        "explicitly mentions a paper / publication / talk."
    ),
}


# Fields that DON'T block "ready" status when empty. The LLM intake
# prompt knows to skip these unless the user volunteers them — pushing
# every candidate to invent projects or publications would be annoying.
_RESUME_BUILDER_OPTIONAL_FIELDS = {
    "certifications",
    "projects_notes",
    "publications",
}


def resume_builder_missing_fields(draft: Dict[str, Any]) -> list[str]:
    """Return the list of REQUIRED resume-builder fields that are still empty.

    Used by the LLM intake prompt so the model can pick the next gap to
    ask about without having to re-derive it. Public helper so the
    service layer and tests can compute it consistently. Optional
    fields (certifications, projects, publications) are excluded —
    they're only asked when the user volunteers them.
    """
    missing: list[str] = []
    for key in _RESUME_BUILDER_FIELD_DESCRIPTIONS:
        if key in _RESUME_BUILDER_OPTIONAL_FIELDS:
            continue
        value = draft.get(key) if isinstance(draft, dict) else None
        if value is None:
            missing.append(key)
            continue
        if isinstance(value, str) and not value.strip():
            missing.append(key)
            continue
        if isinstance(value, list) and not value:
            missing.append(key)
            continue
    return missing


def build_resume_builder_prompt(
    *,
    draft: Dict[str, Any],
    history: Any = None,
    user_message: str,
) -> Dict[str, Any]:
    """LLM intake prompt for the conversational resume builder.

    The model receives the current draft (truth source), a list of
    fields that are still empty (so it doesn't have to re-derive),
    recent conversation turns (for narrative continuity / backtracking),
    and the latest user message. It returns a partial draft update + a
    natural conversational reply + a status flag.

    Rendering the resume itself is not the model's job — the dataclass
    is templated to markdown by `_build_resume_markdown` after the
    draft is captured.
    """
    contract = {
        "draft_updates": (
            "partial dict of resume-builder fields the user mentioned in this "
            "turn or recent turns; OMIT fields you cannot ground in user text"
        ),
        "assistant_message": "the next conversational reply to show the user (1-2 sentences)",
        "status": "one of: 'collecting' (more fields to gather), 'reviewing' (enough to draft), 'ready' (user confirmed)",
        "focus_field": "the field your next question is about, or '' if none",
    }

    field_lines = "\n".join(
        f"  - {name}: {description}"
        for name, description in _RESUME_BUILDER_FIELD_DESCRIPTIONS.items()
    )
    missing = resume_builder_missing_fields(draft)

    history_payload = list(history or [])[-12:]

    user_prompt = "\n\n".join(
        [
            _json_block("Current Draft", draft),
            _json_block("Missing Fields", missing),
            _json_block("Recent Conversation", history_payload),
            _json_block("Latest User Message", {"message": user_message}),
        ]
    )

    return {
        "system": (
            "You are a friendly resume-intake assistant inside a job-application app. "
            "Your job: build a structured resume profile by chatting naturally with the user. "
            "Each turn, listen for any of these fields the user mentions:\n"
            f"{field_lines}\n"
            "\n"
            "These fields render into a resume shaped roughly as:\n"
            "  # {full_name}\n"
            "  {location}\n"
            "  {contact_lines joined by ' | '}\n"
            "  ## Professional Summary\n  {professional_summary}\n"
            "  ## Core Skills\n  - {skills (one per bullet)}\n"
            "  ## Professional Experience\n  {experience_notes — first line is the role headline, rest are bullets}\n"
            "  ## Projects\n  {projects_notes — only when present}\n"
            "  ## Education\n  {education_notes}\n"
            "  ## Publications\n  - {publications (one per bullet, only when present)}\n"
            "  ## Certifications\n  - {certifications (one per bullet)}\n"
            "\n"
            "Rules:\n"
            "- Don't invent. Only put a field in `draft_updates` if the user actually said it (literally or via a clear paraphrase) in the latest message or recent conversation. If unsure, omit.\n"
            "- Backtracking is fine: if the user corrects a previously captured field (e.g., 'actually my role is X'), overwrite that field in `draft_updates`.\n"
            "- Replace, don't append. `draft_updates` values overwrite existing ones — for list fields (skills, contact_lines, certifications), include the FULL new list, not just additions.\n"
            "- Be concise: one or two sentences per assistant_message. Acknowledge what you just captured, then ask the next most useful question.\n"
            "- Pick the next gap from `Missing Fields` in roughly the listed order, but follow the user's lead if they jump ahead.\n"
            "- Don't ask compound questions. One topic at a time.\n"
            "- If the user gives a vague answer ('I'm a developer'), ask one targeted follow-up before moving on.\n"
            "- The `experience_notes`, `education_notes`, and `projects_notes` fields capture the user's words verbatim — don't paraphrase or expand them in `draft_updates`. Downstream rendering handles voice.\n"
            "- Projects + publications are OPTIONAL. Only ask about them when the user mentions a side project / open-source repo / paper / talk OR when their target_role is heavily technical (engineer, ML, data, research) AND they haven't already filled experience_notes with rich detail. Don't pressure for them — many candidates won't have any. After 'experience' is captured for a tech role, you may ask once: 'Do you want to include any side projects or papers?'. If they say no, move on.\n"
            "- Crucial split: when a single user turn contains BOTH a broad self-description (no specific company/dates) AND specific role details, route the self-description to `professional_summary` and the role details to `experience_notes`. Example — user says 'I'm a senior backend engineer with 5 years experience. I worked at Acme from 2020-2024 on the billing pipeline.' → professional_summary captures the first sentence, experience_notes captures the second.\n"
            "- Set status='collecting' while required fields (full_name, contact_lines, target_role, experience_notes, skills) are still empty; 'reviewing' once those are filled and the user could plausibly draft now; 'ready' only after the user explicitly confirms they're done.\n"
            "- Set focus_field to whichever field your next question is about ('' if you're confirming completion).\n"
            "- If the user asks an off-topic question (movies, jokes, lifestyle), decline in one sentence and steer back to resume building. Do not engage with the off-topic premise.\n"
            + _build_contract(contract)
        ),
        "user": user_prompt,
        "expected_keys": list(contract.keys()),
    }


def build_resume_builder_structuring_prompt(
    *,
    draft: Dict[str, Any],
) -> Dict[str, Any]:
    """LLM structuring pass for the resume builder draft.

    The conversational intake captures `experience_notes` and
    `education_notes` as free-form prose (verbatim user words). At
    generate / export time we ask the model to convert those strings
    into a list of structured role / degree objects so the resume
    renderer can produce one card per role and one row per degree.

    The model also gets license to LIGHTLY rewrite bullets into ATS
    voice and infer obvious missing pieces (e.g., the second role's
    title when the user wrote "prior at FinStart"). It must NOT
    fabricate companies, schools, dates, or skills the user did not
    mention. Voice rewrite only — facts stay the user's.

    Returns are merged into a CandidateProfile downstream. On any
    failure (LLM unavailable, JSON malformed, schema mismatch) the
    caller falls back to the deterministic regex parsers, so this
    prompt is best-effort enrichment, not a hard dependency.
    """
    contract = {
        "experience": (
            "list of role objects with keys: title (string), organization (string), "
            "location (string, '' if unknown), start (string like '2020' or 'Jan 2023', "
            "'' if unknown), end (string, 'Present' for current roles, '' if unknown), "
            "bullets (list of 2-4 short impact-focused strings). Order most-recent first."
        ),
        "education": (
            "list of education objects with keys: institution (string), degree (string), "
            "field_of_study (string, '' if degree already includes it), start (string, "
            "'' if unknown), end (string, '' if unknown). Order most-recent first."
        ),
        "projects": (
            "list of project objects with keys: name (string — short title), "
            "description (string, '' if bullets capture it), bullets (list of 1-3 "
            "short impact-focused strings), technologies (list of tech / framework "
            "names that appear in the user's prose, max 8), start (string, '' if "
            "unknown), end (string, '' if unknown), link (URL string, '' if none). "
            "Empty list when projects_notes is empty. Order most-recent first."
        ),
        "skill_categories": (
            "OPTIONAL dict mapping category labels to skill name lists, e.g. "
            "{'Languages & Tools': ['Python', 'SQL'], 'ML / DL Frameworks': "
            "['PyTorch', 'Scikit-learn'], 'GenAI & LLMs': ['LangChain', 'OpenAI API']}. "
            "Generate this ONLY when the candidate has 8+ skills that obviously "
            "cluster by category. Pick category labels that fit the candidate's "
            "domain (common labels: 'Languages & Tools', 'ML / DL Frameworks', "
            "'GenAI & LLMs', 'Vector Databases', 'Systems & Deployment', "
            "'Data & Analysis', 'Cloud & Infrastructure', 'Frontend', 'Mobile'). "
            "Skip and return {} when skills are sparse, uniform, or don't cluster "
            "obviously — the renderer falls back to a flat list."
        ),
    }

    user_prompt = "\n\n".join(
        [
            _json_block(
                "Draft Snapshot",
                {
                    "full_name": draft.get("full_name") or "",
                    "target_role": draft.get("target_role") or "",
                    "professional_summary": draft.get("professional_summary") or "",
                    "skills": draft.get("skills") or [],
                },
            ),
            _json_block(
                "Experience Notes (user prose, verbatim)",
                {"text": draft.get("experience_notes") or ""},
            ),
            _json_block(
                "Education Notes (user prose, verbatim)",
                {"text": draft.get("education_notes") or ""},
            ),
            _json_block(
                "Projects Notes (user prose, verbatim)",
                {"text": draft.get("projects_notes") or ""},
            ),
        ]
    )

    return {
        "system": (
            "You convert resume-builder intake notes into structured resume "
            "entries. The user gave you their experience and education as "
            "free-form prose. Your job is to split that prose into one entry "
            "per role and one entry per degree, then return the structured "
            "lists as JSON.\n"
            "\n"
            "Rules — read carefully:\n"
            "- Split on role / degree boundaries: a new entry starts at every "
            "company name (\"Senior X at Acme\") or transition word (\"prior\", "
            "\"previously\", \"before that\", \"earlier\"). Multiple degrees on "
            "one line (\"MS CS Stanford 2017, BTech IIT Madras 2015\") become "
            "multiple education entries.\n"
            "- Fact preservation is mandatory. Companies, schools, dates, and "
            "skill names must come VERBATIM from the user's prose. Do not "
            "invent employers, schools, dates, technologies, or impact "
            "numbers the user did not mention.\n"
            "- Bullet voice is yours. Convert the user's casual phrasing into "
            "tight, ATS-style impact bullets ('Reduced p99 latency 30% by …', "
            "'Owned ingestion pipeline for …'). Each bullet should start with "
            "a strong verb and stay under ~22 words. If the user gave no "
            "specifics for a role, return an EMPTY bullets list — do NOT "
            "fabricate impact.\n"
            "- Title inference is allowed only when context makes it "
            "unambiguous. \"Senior Backend Engineer at TechCorp 2020-Present, "
            "prior at FinStart 2017-2020\" → second role's title is "
            "\"Backend Engineer\" (drop the seniority modifier). When in "
            "doubt, copy the user's most recent explicit title or leave "
            "title=\"Relevant Experience\".\n"
            "- Dates: parse what the user wrote into start/end strings. "
            "\"2020-Present\" → start='2020', end='Present'. \"(Jan 2023 - "
            "Jan 2025)\" → start='Jan 2023', end='Jan 2025'. Single year → "
            "start=year, end=''.\n"
            "- Education degree vs field: \"BTech CS\" → degree='BTech', "
            "field_of_study='CS'. \"MS Computer Science\" → degree='MS', "
            "field_of_study='Computer Science'. Treat the abbreviation alone "
            "as degree.\n"
            "- Order most recent first in all three lists.\n"
            "- Projects: same fact-preservation contract as experience. "
            "Extract project name, link (any URL the user typed), "
            "technologies (tech names appearing in the prose), and bullets "
            "(impact + outcome). Don't invent metrics, GitHub URLs, or "
            "technologies that aren't in the prose. If projects_notes is "
            "empty, return projects=[].\n"
            "- Skill categories: only emit when 8+ skills cluster naturally "
            "by domain. Every skill that appears in skill_categories MUST "
            "also appear in the original skills list — don't invent new "
            "tech. Don't reorder the skill names within a bucket; preserve "
            "the user's casing ('TensorFlow' not 'tensorflow').\n"
            "- If the user's prose is empty for a section, return an empty "
            "list for that section.\n"
            + _build_contract(contract)
        ),
        "user": user_prompt,
        "expected_keys": list(contract.keys()),
    }


def build_product_help_assistant_prompt(
    app_context: Dict[str, Any],
    question: str,
    history: Any = None,
) -> Dict[str, Any]:
    return build_assistant_prompt(
        {
            "assistant_scope": "product_help",
            "product_context": app_context,
        },
        question,
        history=history,
    )


def build_application_qa_assistant_prompt(
    workflow_context: Dict[str, Any],
    question: str,
    history: Any = None,
) -> Dict[str, Any]:
    return build_assistant_prompt(
        {
            "assistant_scope": "application_qa",
            "workflow_context": workflow_context,
        },
        question,
        history=history,
    )
