import json
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, Iterable

from src.schemas import (
    CandidateProfile,
    FitAnalysis,
    FitAgentOutput,
    JobAgentOutput,
    JobDescription,
    ProfileAgentOutput,
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
    profile_output: ProfileAgentOutput,
    job_output: JobAgentOutput,
) -> Dict[str, Any]:
    contract = {
        "fit_summary": "two to three sentence summary of fit",
        "top_matches": "array of 2-4 strongest grounded matches",
        "key_gaps": "array of 2-4 grounded gaps or risks",
        "interview_themes": "array of 2-4 interview themes to prepare",
    }
    user_prompt, metadata = _build_budgeted_user_prompt(
        [
            ("Candidate Profile", candidate_profile, 2400),
            ("Job Description", job_description, 2200),
            ("Deterministic Fit Analysis", fit_analysis, 1800),
            ("Profile Agent Output", profile_output, 1000),
            ("Job Agent Output", job_output, 1000),
        ]
    )
    return {
        "system": (
            "You are the Fit Analysis Agent. Use the deterministic fit analysis as the primary signal, "
            "and enrich it with concise grounded reasoning. Do not contradict explicit data. "
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
    profile_output: ProfileAgentOutput,
    fit_output: FitAgentOutput,
    previous_tailoring_output: TailoringAgentOutput = None,
    revision_requests: Any = None,
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
        ("Profile Agent Output", profile_output, 1000),
        ("Fit Agent Output", fit_output, 1200),
    ]
    if previous_tailoring_output:
        sections.append(("Previous Tailoring Output", previous_tailoring_output, 1200))
    if revision_requests:
        sections.append(("Revision Requests", revision_requests, 900))
    user_prompt, metadata = _build_budgeted_user_prompt(sections)
    return {
        "system": (
            "You are the Tailoring Agent. Improve the deterministic draft without inventing facts. "
            "If evidence is weak, write conservatively and note transferable alignment instead of exaggerating. "
            "When revision requests are provided, treat them as mandatory constraints and revise the prior tailoring output rather than repeating the same wording. "
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
        "approved": "boolean approval flag",
        "grounding_issues": "array of 0-4 unsupported or weakly supported claims",
        "revision_requests": "array of 0-4 concrete requested revisions",
        "final_notes": "array of 1-3 final quality notes",
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
            "You are the Review Agent. Your job is to reject embellishment and unsupported claims. "
            "Approve only if the wording stays grounded in the source profile and deterministic analysis. "
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
    profile_output: ProfileAgentOutput,
    fit_output: FitAgentOutput,
    tailoring_output: TailoringAgentOutput,
    previous_strategy_output: StrategyAgentOutput = None,
    revision_requests: Any = None,
) -> Dict[str, Any]:
    contract = {
        "recruiter_positioning": "2-3 sentence recruiter-facing positioning guidance grounded in the inputs",
        "cover_letter_talking_points": "array of 2-4 grounded cover-letter talking points",
        "interview_preparation_themes": "array of 2-4 interview themes to prepare with evidence",
        "portfolio_project_emphasis": "array of 2-4 portfolio or project emphasis suggestions grounded in the candidate profile",
    }
    sections = [
        ("Candidate Profile", candidate_profile, 2000),
        ("Job Description", job_description, 1600),
        ("Deterministic Fit Analysis", fit_analysis, 1500),
        ("Profile Agent Output", profile_output, 1000),
        ("Fit Agent Output", fit_output, 1200),
        ("Tailoring Agent Output", tailoring_output, 1400),
    ]
    if previous_strategy_output:
        sections.append(("Previous Strategy Output", previous_strategy_output, 1200))
    if revision_requests:
        sections.append(("Revision Requests", revision_requests, 900))
    user_prompt, metadata = _build_budgeted_user_prompt(sections)
    return {
        "system": (
            "You are the Application Strategy Agent. Convert grounded fit and tailoring signals into downstream application guidance. "
            "Do not invent projects, experience, technologies, or recruiter claims that are not supported by the source profile. "
            "When revision requests are provided, treat them as mandatory constraints and revise the previous strategy output instead of repeating rejected wording. "
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
    if review_output:
        sections.append(("Review Agent Output", review_output, 1000))
    user_prompt, metadata = _build_budgeted_user_prompt(sections)
    return {
        "system": (
            "You are the Resume Generation Agent. Produce the final tailored resume content from grounded upstream analysis. "
            "You may rewrite, reorder, and emphasize, but you must not invent employers, achievements, dates, metrics, or unsupported skills. "
            "Keep the output ATS-safe and recruiter-readable. "
            + _build_contract(contract)
        ),
        "user": user_prompt,
        "expected_keys": list(contract.keys()),
        "metadata": metadata,
    }


def build_product_help_assistant_prompt(
    app_context: Dict[str, Any],
    question: str,
    history: Any = None,
) -> Dict[str, Any]:
    contract = {
        "answer": "short, direct answer explaining how to use the product or what a feature does",
        "sources": "array of 1-3 relevant product areas or screens used for the answer",
        "suggested_follow_ups": "array of 0-3 follow-up questions the user may want to ask next",
    }
    user_prompt = "\n\n".join(
        [
            _json_block("Product Context", app_context),
            _json_block("User Question", {"question": question}),
        ]
        + ([_json_block("Recent History", history[-4:])] if history else [])
    )
    return {
        "system": (
            "You are the Product Help Assistant for an AI job application app. "
            "Explain the current product behavior clearly and only describe features that are actually available in the provided context. "
            "Use retrieved product knowledge hits when they are provided, but keep runtime session context authoritative for current state such as quotas, page availability, and active artifacts. "
            "If the user asks about navigation, explain the current sidebar pages and signed-in actions from the provided context. "
            "If the user asks who you are or what your name is, answer as the in-app Product Help Assistant rather than switching to a generic workflow summary. "
            "If the user asks about limits, tokens, quota, warnings, or fallback behavior, explain the difference between browser-session assisted budget and account-level daily quota using the provided context. "
            + _build_contract(contract)
        ),
        "user": user_prompt,
        "expected_keys": list(contract.keys()),
    }


def build_application_qa_assistant_prompt(
    workflow_context: Dict[str, Any],
    question: str,
    history: Any = None,
) -> Dict[str, Any]:
    contract = {
        "answer": "grounded answer that can combine general resume coaching with context-specific recommendations from the user's current package",
        "sources": "array of 1-4 workflow artifacts or signals used for the answer",
        "suggested_follow_ups": "array of 0-3 useful next questions or actions",
    }
    user_prompt = "\n\n".join(
        [
            _json_block("Workflow Context", workflow_context),
            _json_block("User Question", {"question": question}),
        ]
        + ([_json_block("Recent History", history[-4:])] if history else [])
    )
    return {
        "system": (
            "You are the Application Q&A Assistant. Use the provided workflow context as the grounding source for all context-specific claims. "
            "If the user asks for broader resume or application coaching, you may provide general guidance, but anchor it back to the user's current package and clearly separate general advice from context-specific recommendations when helpful. "
            "Do not invent facts about the candidate, JD, or outputs. If evidence is weak, say so directly. "
            + _build_contract(contract)
        ),
        "user": user_prompt,
        "expected_keys": list(contract.keys()),
    }
