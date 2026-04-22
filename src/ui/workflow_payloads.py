import json
from dataclasses import asdict
from typing import Optional

from src.schemas import (
    AgentWorkflowResult,
    ApplicationReport,
    CandidateProfile,
    CoverLetterArtifact,
    CoverLetterAgentOutput,
    EducationEntry,
    FitAgentOutput,
    FitAnalysis,
    JobAgentOutput,
    JobDescription,
    JobRequirements,
    ProfileAgentOutput,
    ResumeGenerationAgentOutput,
    ReviewAgentOutput,
    ReviewPassResult,
    SavedWorkflowSnapshot,
    StrategyAgentOutput,
    TailoredResumeArtifact,
    TailoredResumeDraft,
    TailoringAgentOutput,
    WorkExperience,
)


WORKFLOW_HISTORY_PAYLOAD_VERSION = 1
WORKFLOW_HISTORY_PAYLOAD_KIND_SNAPSHOT = "workflow_snapshot"
WORKFLOW_HISTORY_PAYLOAD_KIND_REPORT = "application_report"
WORKFLOW_HISTORY_PAYLOAD_KIND_COVER_LETTER = "cover_letter_artifact"
WORKFLOW_HISTORY_PAYLOAD_KIND_TAILORED_RESUME = "tailored_resume_artifact"


def versioned_payload(payload_kind: str, payload_data: dict):
    return json.dumps(
        {
            "version": WORKFLOW_HISTORY_PAYLOAD_VERSION,
            "kind": payload_kind,
            "data": payload_data,
        },
        sort_keys=True,
        default=str,
    )


def json_payload(payload_kind: str, value):
    return versioned_payload(payload_kind, asdict(value))


def workflow_snapshot_json(view_model):
    payload = {
        "candidate_profile": asdict(view_model.candidate_profile),
        "job_description": asdict(view_model.job_description),
        "fit_analysis": asdict(view_model.fit_analysis),
        "tailored_draft": asdict(view_model.tailored_draft),
        "agent_result": asdict(view_model.agent_result) if view_model.agent_result else None,
        "imported_job_posting": getattr(view_model, "imported_job_posting", None),
    }
    return versioned_payload(WORKFLOW_HISTORY_PAYLOAD_KIND_SNAPSHOT, payload)


def inspect_saved_payload(raw_payload: str, expected_kind: str):
    if not raw_payload:
        return {
            "present": False,
            "supported": False,
            "version": None,
            "label": "Unavailable",
            "message": "No saved payload is available for this artifact.",
            "data": None,
            "storage": "missing",
        }

    try:
        payload = json.loads(raw_payload)
    except (TypeError, json.JSONDecodeError) as exc:
        return {
            "present": True,
            "supported": False,
            "version": None,
            "label": "Malformed",
            "message": "This saved workflow payload is malformed and cannot be regenerated safely.",
            "data": None,
            "storage": "malformed",
            "details": str(exc),
        }

    if not isinstance(payload, dict):
        return {
            "present": True,
            "supported": False,
            "version": None,
            "label": "Malformed",
            "message": "This saved workflow payload is malformed and cannot be regenerated safely.",
            "data": None,
            "storage": "malformed",
        }

    if "version" in payload and "data" in payload:
        try:
            version = int(payload.get("version", 0) or 0)
        except (TypeError, ValueError):
            version = -1
        payload_kind = str(payload.get("kind", "") or "")
        payload_data = payload.get("data")
        if payload_kind and payload_kind != expected_kind:
            return {
                "present": True,
                "supported": False,
                "version": version,
                "label": "Kind Mismatch",
                "message": "This saved workflow payload does not match the expected artifact type.",
                "data": None,
                "storage": "versioned",
            }
        if version != WORKFLOW_HISTORY_PAYLOAD_VERSION:
            return {
                "present": True,
                "supported": False,
                "version": version,
                "label": "Unsupported",
                "message": (
                    "This saved workflow run uses payload version v{version}, but the app currently "
                    "supports only v{current}."
                ).format(version=version, current=WORKFLOW_HISTORY_PAYLOAD_VERSION),
                "data": None,
                "storage": "versioned",
            }
        if not isinstance(payload_data, dict):
            return {
                "present": True,
                "supported": False,
                "version": version,
                "label": "Malformed",
                "message": "This saved workflow payload is malformed and cannot be regenerated safely.",
                "data": None,
                "storage": "versioned",
            }
        return {
            "present": True,
            "supported": True,
            "version": version,
            "label": "v{version} Current".format(version=version),
            "message": "This saved run uses the current versioned payload envelope for historical regeneration.",
            "data": payload_data,
            "storage": "versioned",
        }

    return {
        "present": True,
        "supported": True,
        "version": 0,
        "label": "Legacy v0",
        "message": "This saved run predates explicit payload versioning. Historical downloads still use the legacy-compatible reader.",
        "data": payload,
        "storage": "legacy",
    }


def get_saved_workflow_payload_status(workflow_run: Optional[object]):
    if workflow_run is None:
        return {
            "label": "Unavailable",
            "supported": False,
            "message": "No workflow run is selected.",
        }

    inspections = []
    for raw_payload, expected_kind in (
        (getattr(workflow_run, "workflow_snapshot_json", ""), WORKFLOW_HISTORY_PAYLOAD_KIND_SNAPSHOT),
        (getattr(workflow_run, "report_payload_json", ""), WORKFLOW_HISTORY_PAYLOAD_KIND_REPORT),
        (getattr(workflow_run, "cover_letter_payload_json", ""), WORKFLOW_HISTORY_PAYLOAD_KIND_COVER_LETTER),
        (getattr(workflow_run, "tailored_resume_payload_json", ""), WORKFLOW_HISTORY_PAYLOAD_KIND_TAILORED_RESUME),
    ):
        inspection = inspect_saved_payload(raw_payload, expected_kind)
        if inspection["present"]:
            inspections.append(inspection)

    if not inspections:
        return {
            "label": "Unavailable",
            "supported": False,
            "message": "This workflow run does not have any saved regeneration payloads.",
        }

    unsupported = next((inspection for inspection in inspections if not inspection["supported"]), None)
    if unsupported is not None:
        version = unsupported.get("version")
        label = unsupported["label"]
        if version not in (None, "") and label == "Unsupported":
            label = "v{version} Unsupported".format(version=version)
        return {
            "label": label,
            "supported": False,
            "message": unsupported["message"],
        }

    versions = {inspection["version"] for inspection in inspections}
    if versions == {WORKFLOW_HISTORY_PAYLOAD_VERSION}:
        return {
            "label": "v{version} Current".format(version=WORKFLOW_HISTORY_PAYLOAD_VERSION),
            "supported": True,
            "message": "This saved run uses the current versioned payload envelope for historical regeneration.",
        }
    if versions == {0}:
        return {
            "label": "Legacy v0",
            "supported": True,
            "message": "This saved run predates explicit payload versioning. Historical downloads remain available through the legacy-compatible reader.",
        }
    return {
        "label": "Mixed Compatibility",
        "supported": True,
        "message": "This saved run mixes legacy and current saved payload envelopes. Historical downloads remain available through compatible readers.",
    }


def build_saved_report_from_payload(raw_payload: str):
    inspection = inspect_saved_payload(raw_payload, WORKFLOW_HISTORY_PAYLOAD_KIND_REPORT)
    if not inspection["supported"]:
        return None
    payload = inspection["data"] or {}
    return ApplicationReport(
        title=str(payload.get("title", "Saved Application Report") or "Saved Application Report"),
        filename_stem=str(payload.get("filename_stem", "saved-application-report") or "saved-application-report"),
        summary=str(payload.get("summary", "") or ""),
        markdown=str(payload.get("markdown", "") or ""),
        plain_text=str(payload.get("plain_text", "") or ""),
    )


def build_saved_cover_letter_from_payload(raw_payload: str):
    inspection = inspect_saved_payload(raw_payload, WORKFLOW_HISTORY_PAYLOAD_KIND_COVER_LETTER)
    if not inspection["supported"]:
        return None
    payload = inspection["data"] or {}
    return CoverLetterArtifact(
        title=str(payload.get("title", "Saved Cover Letter") or "Saved Cover Letter"),
        filename_stem=str(payload.get("filename_stem", "saved-cover-letter") or "saved-cover-letter"),
        summary=str(payload.get("summary", "") or ""),
        markdown=str(payload.get("markdown", "") or ""),
        plain_text=str(payload.get("plain_text", "") or ""),
    )


def build_saved_tailored_resume_from_payload(raw_payload: str):
    inspection = inspect_saved_payload(raw_payload, WORKFLOW_HISTORY_PAYLOAD_KIND_TAILORED_RESUME)
    if not inspection["supported"]:
        return None
    payload = inspection["data"] or {}
    return TailoredResumeArtifact(
        title=str(payload.get("title", "Saved Tailored Resume") or "Saved Tailored Resume"),
        filename_stem=str(payload.get("filename_stem", "saved-tailored-resume") or "saved-tailored-resume"),
        summary=str(payload.get("summary", "") or ""),
        markdown=str(payload.get("markdown", "") or ""),
        plain_text=str(payload.get("plain_text", "") or ""),
        theme=str(payload.get("theme", "classic_ats") or "classic_ats"),
    )


def build_saved_workflow_snapshot_from_payload(raw_payload: str):
    inspection = inspect_saved_payload(raw_payload, WORKFLOW_HISTORY_PAYLOAD_KIND_SNAPSHOT)
    if not inspection["supported"]:
        return None
    payload = inspection["data"] or {}
    return build_saved_workflow_snapshot_from_data(payload)


def build_saved_workflow_snapshot_from_data(payload: dict):
    candidate_profile = payload.get("candidate_profile") or {}
    job_description = payload.get("job_description") or {}
    fit_analysis = payload.get("fit_analysis") or {}
    tailored_draft = payload.get("tailored_draft") or {}
    if not candidate_profile or not job_description or not fit_analysis or not tailored_draft:
        return None
    return SavedWorkflowSnapshot(
        candidate_profile=_build_candidate_profile(candidate_profile),
        job_description=_build_job_description(job_description),
        fit_analysis=_build_fit_analysis(fit_analysis),
        tailored_draft=_build_tailored_draft(tailored_draft),
        agent_result=_build_agent_result(payload.get("agent_result")),
        imported_job_posting=_build_imported_job_posting(payload.get("imported_job_posting")),
    )


def _build_imported_job_posting(payload):
    if not isinstance(payload, dict):
        return None
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    return {
        "id": str(payload.get("id", "") or ""),
        "source": str(payload.get("source", "") or ""),
        "title": str(payload.get("title", "") or ""),
        "company": str(payload.get("company", "") or ""),
        "location": str(payload.get("location", "") or ""),
        "employment_type": str(payload.get("employment_type", "") or ""),
        "url": str(payload.get("url", "") or ""),
        "summary": str(payload.get("summary", "") or ""),
        "description_text": str(payload.get("description_text", "") or ""),
        "posted_at": str(payload.get("posted_at", "") or ""),
        "scraped_at": str(payload.get("scraped_at", "") or ""),
        "metadata": metadata,
    }


def _build_candidate_profile(payload: dict):
    return CandidateProfile(
        full_name=str(payload.get("full_name", "") or ""),
        location=str(payload.get("location", "") or ""),
        contact_lines=[str(item) for item in payload.get("contact_lines", []) or []],
        source=str(payload.get("source", "") or ""),
        resume_text=str(payload.get("resume_text", "") or ""),
        skills=[str(item) for item in payload.get("skills", []) or []],
        experience=[_build_work_experience(item) for item in payload.get("experience", []) or []],
        education=[_build_education_entry(item) for item in payload.get("education", []) or []],
        certifications=[str(item) for item in payload.get("certifications", []) or []],
        source_signals=[str(item) for item in payload.get("source_signals", []) or []],
    )


def _build_work_experience(payload: dict):
    return WorkExperience(
        title=str(payload.get("title", "") or ""),
        organization=str(payload.get("organization", "") or ""),
        location=str(payload.get("location", "") or ""),
        description=str(payload.get("description", "") or ""),
        start=payload.get("start"),
        end=payload.get("end"),
    )


def _build_education_entry(payload: dict):
    return EducationEntry(
        institution=str(payload.get("institution", "") or ""),
        degree=str(payload.get("degree", "") or ""),
        field_of_study=str(payload.get("field_of_study", "") or ""),
        start=str(payload.get("start", "") or ""),
        end=str(payload.get("end", "") or ""),
    )


def _build_job_description(payload: dict):
    requirements = payload.get("requirements") or {}
    return JobDescription(
        title=str(payload.get("title", "") or ""),
        raw_text=str(payload.get("raw_text", "") or ""),
        cleaned_text=str(payload.get("cleaned_text", "") or ""),
        location=str(payload.get("location", "") or "") or None,
        requirements=JobRequirements(
            hard_skills=[str(item) for item in requirements.get("hard_skills", []) or []],
            soft_skills=[str(item) for item in requirements.get("soft_skills", []) or []],
            experience_requirement=requirements.get("experience_requirement"),
            must_haves=[str(item) for item in requirements.get("must_haves", []) or []],
            nice_to_haves=[str(item) for item in requirements.get("nice_to_haves", []) or []],
        ),
    )


def _build_fit_analysis(payload: dict):
    return FitAnalysis(
        target_role=str(payload.get("target_role", "") or ""),
        overall_score=int(payload.get("overall_score", 0) or 0),
        readiness_label=str(payload.get("readiness_label", "") or ""),
        matched_hard_skills=[str(item) for item in payload.get("matched_hard_skills", []) or []],
        missing_hard_skills=[str(item) for item in payload.get("missing_hard_skills", []) or []],
        matched_soft_skills=[str(item) for item in payload.get("matched_soft_skills", []) or []],
        missing_soft_skills=[str(item) for item in payload.get("missing_soft_skills", []) or []],
        experience_signal=str(payload.get("experience_signal", "") or ""),
        strengths=[str(item) for item in payload.get("strengths", []) or []],
        gaps=[str(item) for item in payload.get("gaps", []) or []],
        recommendations=[str(item) for item in payload.get("recommendations", []) or []],
    )


def _build_tailored_draft(payload: dict):
    return TailoredResumeDraft(
        target_role=str(payload.get("target_role", "") or ""),
        professional_summary=str(payload.get("professional_summary", "") or ""),
        highlighted_skills=[str(item) for item in payload.get("highlighted_skills", []) or []],
        priority_bullets=[str(item) for item in payload.get("priority_bullets", []) or []],
        gap_mitigation_steps=[str(item) for item in payload.get("gap_mitigation_steps", []) or []],
    )


def _build_profile_output(payload: dict):
    return ProfileAgentOutput(
        positioning_headline=str(payload.get("positioning_headline", "") or ""),
        evidence_highlights=[str(item) for item in payload.get("evidence_highlights", []) or []],
        strengths=[str(item) for item in payload.get("strengths", []) or []],
        cautions=[str(item) for item in payload.get("cautions", []) or []],
    )


def _build_job_output(payload: dict):
    return JobAgentOutput(
        requirement_summary=str(payload.get("requirement_summary", "") or ""),
        priority_skills=[str(item) for item in payload.get("priority_skills", []) or []],
        must_have_themes=[str(item) for item in payload.get("must_have_themes", []) or []],
        messaging_guidance=[str(item) for item in payload.get("messaging_guidance", []) or []],
    )


def _build_fit_output(payload: dict):
    return FitAgentOutput(
        fit_summary=str(payload.get("fit_summary", "") or ""),
        top_matches=[str(item) for item in payload.get("top_matches", []) or []],
        key_gaps=[str(item) for item in payload.get("key_gaps", []) or []],
    )


def _build_tailoring_output(payload: dict):
    return TailoringAgentOutput(
        professional_summary=str(payload.get("professional_summary", "") or ""),
        rewritten_bullets=[str(item) for item in payload.get("rewritten_bullets", []) or []],
        highlighted_skills=[str(item) for item in payload.get("highlighted_skills", []) or []],
        cover_letter_themes=[str(item) for item in payload.get("cover_letter_themes", []) or []],
    )


def _build_strategy_output(payload):
    if not payload:
        return None
    return StrategyAgentOutput(
        recruiter_positioning=str(payload.get("recruiter_positioning", "") or ""),
        cover_letter_talking_points=[str(item) for item in payload.get("cover_letter_talking_points", []) or []],
        portfolio_project_emphasis=[str(item) for item in payload.get("portfolio_project_emphasis", []) or []],
    )


def _build_review_output(payload: dict):
    return ReviewAgentOutput(
        approved=bool(payload.get("approved", False)),
        grounding_issues=[str(item) for item in payload.get("grounding_issues", []) or []],
        unresolved_issues=[str(item) for item in payload.get("unresolved_issues", []) or []],
        revision_requests=[str(item) for item in payload.get("revision_requests", []) or []],
        final_notes=[str(item) for item in payload.get("final_notes", []) or []],
        corrected_tailoring=_build_tailoring_output(payload.get("corrected_tailoring") or {}) if payload.get("corrected_tailoring") else None,
        corrected_strategy=_build_strategy_output(payload.get("corrected_strategy")),
    )


def _build_resume_generation_output(payload):
    if not payload:
        return None
    return ResumeGenerationAgentOutput(
        professional_summary=str(payload.get("professional_summary", "") or ""),
        highlighted_skills=[str(item) for item in payload.get("highlighted_skills", []) or []],
        experience_bullets=[str(item) for item in payload.get("experience_bullets", []) or []],
        section_order=[str(item) for item in payload.get("section_order", []) or []],
        template_hint=str(payload.get("template_hint", "classic_ats") or "classic_ats"),
    )


def _build_cover_letter_output(payload):
    if not payload:
        return None
    return CoverLetterAgentOutput(
        greeting=str(payload.get("greeting", "") or ""),
        opening_paragraph=str(payload.get("opening_paragraph", "") or ""),
        body_paragraphs=[str(item) for item in payload.get("body_paragraphs", []) or []],
        closing_paragraph=str(payload.get("closing_paragraph", "") or ""),
        signoff=str(payload.get("signoff", "") or ""),
        signature_name=str(payload.get("signature_name", "") or ""),
    )


def _build_review_pass_result(payload: dict):
    return ReviewPassResult(
        pass_index=int(payload.get("pass_index", 0) or 0),
        tailoring=_build_tailoring_output(payload.get("tailoring") or {}),
        strategy=_build_strategy_output(payload.get("strategy")),
        review=_build_review_output(payload.get("review") or {}),
    )


def _build_agent_result(payload):
    if not payload:
        return None
    return AgentWorkflowResult(
        mode=str(payload.get("mode", "") or ""),
        model=str(payload.get("model", "") or ""),
        profile=_build_profile_output(payload.get("profile") or {}),
        job=_build_job_output(payload.get("job") or {}),
        fit=_build_fit_output(payload.get("fit") or {}),
        tailoring=_build_tailoring_output(payload.get("tailoring") or {}),
        review=_build_review_output(payload.get("review") or {}),
        strategy=_build_strategy_output(payload.get("strategy")),
        resume_generation=_build_resume_generation_output(payload.get("resume_generation")),
        cover_letter=_build_cover_letter_output(payload.get("cover_letter")),
        review_history=[_build_review_pass_result(item) for item in payload.get("review_history", []) or []],
    )
