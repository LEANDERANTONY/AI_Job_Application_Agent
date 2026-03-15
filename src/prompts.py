import json
from dataclasses import asdict, is_dataclass
from typing import Any, Dict

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
    user_prompt = "\n\n".join(
        [
            _json_block("Candidate Profile", candidate_profile),
            _json_block("Job Description", job_description),
            _json_block("Deterministic Fit Analysis", fit_analysis),
            _json_block("Profile Agent Output", profile_output),
            _json_block("Job Agent Output", job_output),
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
    user_prompt = "\n\n".join(
        [
            _json_block("Candidate Profile", candidate_profile),
            _json_block("Job Description", job_description),
            _json_block("Deterministic Fit Analysis", fit_analysis),
            _json_block("Deterministic Tailored Draft", tailored_draft),
            _json_block("Profile Agent Output", profile_output),
            _json_block("Fit Agent Output", fit_output),
        ]
        + (
            [_json_block("Previous Tailoring Output", previous_tailoring_output)]
            if previous_tailoring_output
            else []
        )
        + ([ _json_block("Revision Requests", revision_requests)] if revision_requests else [])
    )
    return {
        "system": (
            "You are the Tailoring Agent. Improve the deterministic draft without inventing facts. "
            "If evidence is weak, write conservatively and note transferable alignment instead of exaggerating. "
            "When revision requests are provided, treat them as mandatory constraints and revise the prior tailoring output rather than repeating the same wording. "
            + _build_contract(contract)
        ),
        "user": user_prompt,
        "expected_keys": list(contract.keys()),
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
    user_prompt = "\n\n".join(
        [
            _json_block("Candidate Profile", candidate_profile),
            _json_block("Job Description", job_description),
            _json_block("Deterministic Fit Analysis", fit_analysis),
            _json_block("Deterministic Tailored Draft", tailored_draft),
            _json_block("Tailoring Agent Output", tailoring_output),
        ]
        + ([_json_block("Strategy Agent Output", strategy_output)] if strategy_output else [])
    )
    return {
        "system": (
            "You are the Review Agent. Your job is to reject embellishment and unsupported claims. "
            "Approve only if the wording stays grounded in the source profile and deterministic analysis. "
            + _build_contract(contract)
        ),
        "user": user_prompt,
        "expected_keys": list(contract.keys()),
    }


def build_strategy_agent_prompt(
    candidate_profile: CandidateProfile,
    job_description: JobDescription,
    fit_analysis: FitAnalysis,
    profile_output: ProfileAgentOutput,
    fit_output: FitAgentOutput,
    tailoring_output: TailoringAgentOutput,
) -> Dict[str, Any]:
    contract = {
        "recruiter_positioning": "2-3 sentence recruiter-facing positioning guidance grounded in the inputs",
        "cover_letter_talking_points": "array of 2-4 grounded cover-letter talking points",
        "interview_preparation_themes": "array of 2-4 interview themes to prepare with evidence",
        "portfolio_project_emphasis": "array of 2-4 portfolio or project emphasis suggestions grounded in the candidate profile",
    }
    user_prompt = "\n\n".join(
        [
            _json_block("Candidate Profile", candidate_profile),
            _json_block("Job Description", job_description),
            _json_block("Deterministic Fit Analysis", fit_analysis),
            _json_block("Profile Agent Output", profile_output),
            _json_block("Fit Agent Output", fit_output),
            _json_block("Tailoring Agent Output", tailoring_output),
        ]
    )
    return {
        "system": (
            "You are the Application Strategy Agent. Convert grounded fit and tailoring signals into downstream application guidance. "
            "Do not invent projects, experience, technologies, or recruiter claims that are not supported by the source profile. "
            + _build_contract(contract)
        ),
        "user": user_prompt,
        "expected_keys": list(contract.keys()),
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
    user_prompt = "\n\n".join(
        [
            _json_block("Candidate Profile", candidate_profile),
            _json_block("Job Description", job_description),
            _json_block("Deterministic Fit Analysis", fit_analysis),
            _json_block("Deterministic Tailored Draft", tailored_draft),
            _json_block("Tailoring Agent Output", tailoring_output),
        ]
        + ([_json_block("Strategy Agent Output", strategy_output)] if strategy_output else [])
        + ([_json_block("Review Agent Output", review_output)] if review_output else [])
    )
    return {
        "system": (
            "You are the Resume Generation Agent. Produce the final tailored resume content from grounded upstream analysis. "
            "You may rewrite, reorder, and emphasize, but you must not invent employers, achievements, dates, metrics, or unsupported skills. "
            "Keep the output ATS-safe and recruiter-readable. "
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
        "answer": "grounded answer about the user's resume, JD, report, or tailored resume",
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
            "You are the Application Q&A Assistant. Answer only from the provided workflow context. "
            "Do not invent facts about the candidate, JD, or outputs. If evidence is weak, say so directly. "
            + _build_contract(contract)
        ),
        "user": user_prompt,
        "expected_keys": list(contract.keys()),
    }
