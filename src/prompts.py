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
    StrategyAgentOutput,
    TailoredResumeDraft,
    TailoringAgentOutput,
)


def _to_serializable(value: Any):
    if is_dataclass(value):
        return asdict(value)
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
