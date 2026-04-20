import json
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, Iterable

from src.schemas import (
    CandidateProfile,
    CoverLetterAgentOutput,
    FitAnalysis,
    FitAgentOutput,
    JobDescription,
    ReviewAgentOutput,
    StrategyAgentOutput,
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


def build_profile_agent_prompt(candidate_profile: CandidateProfile) -> Dict[str, Any]:
    contract = {
        "positioning_headline": "short recruiter-facing headline grounded in the candidate input",
        "evidence_highlights": "array of 2-4 evidence-backed highlights",
        "strengths": "array of 2-4 grounded strengths",
        "cautions": "array of 1-3 caveats or missing-evidence notes",
    }
    return {
        "system": (
            "You are the Profile Agent for an AI job application workflow. "
            "Use only the provided candidate data. Do not invent experience, metrics, or technologies. "
            + _build_contract(contract)
        ),
        "user": _json_block("Candidate Profile", candidate_profile),
        "expected_keys": list(contract.keys()),
    }


def build_job_agent_prompt(job_description: JobDescription) -> Dict[str, Any]:
    contract = {
        "requirement_summary": "two to three sentence summary of the job's hiring intent",
        "priority_skills": "array of 3-6 priority skills from the JD",
        "must_have_themes": "array of 2-4 must-have themes derived from the JD",
        "messaging_guidance": "array of 2-4 ways the candidate should mirror the JD language",
    }
    return {
        "system": (
            "You are the Job Agent. Summarize the job clearly and conservatively. "
            "Stay grounded in the JD text and requirements only. "
            + _build_contract(contract)
        ),
        "user": _json_block("Job Description", job_description),
        "expected_keys": list(contract.keys()),
    }


def build_fit_agent_prompt(
    candidate_profile: CandidateProfile,
    job_description: JobDescription,
    fit_analysis: FitAnalysis,
) -> Dict[str, Any]:
    contract = {
        "fit_summary": "two concise sentences summarizing fit",
        "top_matches": "array of 2-4 strongest grounded matches",
        "key_gaps": "array of 2-4 grounded gaps or risks",
    }
    user_prompt, metadata = _build_budgeted_user_prompt(
        [
            ("Candidate Profile", candidate_profile, 2400),
            ("Job Description", job_description, 2200),
            ("Deterministic Fit Analysis", fit_analysis, 1800),
        ]
    )
    return {
        "system": (
            "You are the Fit Analysis Agent. Use the deterministic fit analysis as the primary signal, "
            "and compress it into a recruiter-readable grounded summary. Do not contradict explicit data or restate obvious parser output. "
            + _build_contract(contract)
        ),
        "user": user_prompt,
        "expected_keys": list(contract.keys()),
        "metadata": metadata,
    }


def build_tailoring_agent_prompt(
    candidate_profile: CandidateProfile,
    job_description: JobDescription,
    fit_analysis: FitAnalysis,
    tailored_draft: TailoredResumeDraft,
    fit_output: FitAgentOutput,
) -> Dict[str, Any]:
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
        ("Fit Agent Output", fit_output, 1200),
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
    strategy_output: StrategyAgentOutput = None,
) -> Dict[str, Any]:
    contract = {
        "approved": "boolean flag that must be true when the final outputs are safe to use after applying any review corrections; false only when unresolved issues still remain after review",
        "grounding_issues": "array of 0-4 unsupported or weakly supported claims found in the incoming tailoring or strategy draft before review corrections",
        "unresolved_issues": "array of 0-4 issues that still remain after review corrections are applied; return an empty array when the corrected outputs are safe to use",
        "revision_requests": "array of 0-4 concise correction notes or fixes that were needed",
        "final_notes": "array of 1-3 final quality notes",
        "corrected_tailoring": "null when no tailoring changes are needed; otherwise an object matching the Tailoring Agent contract after review corrections are applied",
        "corrected_strategy": "null when no strategy changes are needed; otherwise an object matching the Strategy Agent contract after review corrections are applied",
    }
    sections = [
        ("Candidate Profile", candidate_profile, 2000),
        ("Job Description", job_description, 1600),
        ("Deterministic Fit Analysis", fit_analysis, 1600),
        ("Deterministic Tailored Draft", tailored_draft, 1800),
        ("Tailoring Agent Output", tailoring_output, 1400),
    ]
    if strategy_output:
        sections.append(("Strategy Agent Output", strategy_output, 1200))
    user_prompt, metadata = _build_budgeted_user_prompt(sections)
    return {
        "system": (
            "You are the Review Agent. Your job is to reject embellishment and unsupported claims, then directly repair the tailoring and strategy outputs when fixes are straightforward. "
            "Approve when the final corrected wording stays grounded in the source profile and deterministic analysis, even if the incoming draft had issues that you fixed. "
            "Set approved to false only when unresolved issues remain after your corrections. "
            "Return null for corrected_tailoring and corrected_strategy when the current outputs are already acceptable or when no change is needed for that section. "
            "Only return a corrected object for the specific section that actually needs a grounded rewrite. "
            + _build_contract(contract)
        ),
        "user": user_prompt,
        "expected_keys": list(contract.keys()),
        "metadata": metadata,
    }


def build_strategy_agent_prompt(
    candidate_profile: CandidateProfile,
    job_description: JobDescription,
    fit_analysis: FitAnalysis,
    fit_output: FitAgentOutput,
    tailoring_output: TailoringAgentOutput,
) -> Dict[str, Any]:
    contract = {
        "recruiter_positioning": "2-3 sentence recruiter-facing positioning guidance grounded in the inputs",
        "cover_letter_talking_points": "array of 2-4 grounded cover-letter talking points",
        "portfolio_project_emphasis": "array of 2-4 portfolio or project emphasis suggestions grounded in the candidate profile",
    }
    sections = [
        ("Candidate Profile", candidate_profile, 2000),
        ("Job Description", job_description, 1600),
        ("Deterministic Fit Analysis", fit_analysis, 1500),
        ("Fit Agent Output", fit_output, 1200),
        ("Tailoring Agent Output", tailoring_output, 1400),
    ]
    user_prompt, metadata = _build_budgeted_user_prompt(sections)
    return {
        "system": (
            "You are the Application Strategy Agent. Convert grounded fit and tailoring signals into downstream application guidance. "
            "Do not invent projects, experience, technologies, or recruiter claims that are not supported by the source profile. "
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
    strategy_output: StrategyAgentOutput = None,
    review_output: ReviewAgentOutput = None,
) -> Dict[str, Any]:
    contract = {
        "professional_summary": "2-4 sentence final summary for the tailored resume using only grounded claims",
        "highlighted_skills": "array of 4-8 skills to surface in the tailored resume",
        "experience_bullets": "array of 3-6 grounded experience bullets for the tailored resume",
        "section_order": "array describing preferred section order for the resume",
        "template_hint": "preferred template hint such as classic_ats or modern_professional",
    }
    sections = [
        ("Candidate Profile", candidate_profile, 1800),
        ("Job Description", job_description, 1500),
        ("Deterministic Fit Analysis", fit_analysis, 1500),
        ("Deterministic Tailored Draft", tailored_draft, 1800),
        ("Tailoring Agent Output", tailoring_output, 1400),
    ]
    if strategy_output:
        sections.append(("Strategy Agent Output", strategy_output, 1100))
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
    strategy_output: StrategyAgentOutput = None,
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
    if strategy_output:
        sections.append(("Approved Strategy Output", strategy_output, 1200))
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
            "Use the approved tailoring, strategy, review, and resume-generation context as the source of truth. "
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
            "Use the existing conversation state as the primary memory for this session. "
            "Use any provided state updates to refresh your understanding of the current page, product state, or application package. "
            "Keep answers grounded, concise, and directly useful. "
            "If the question is about the current application package, stay tied to the current fit, tailored resume, cover letter, and report context already established in the session. "
            "If the question is product-help oriented, explain only features and behavior that match the current product. "
            "Current assistant scope: {scope}. ".format(scope=assistant_scope)
            + _build_contract(contract)
        ),
        "user": "\n\n".join(user_sections),
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
