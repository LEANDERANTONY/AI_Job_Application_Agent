import json
from dataclasses import asdict
from typing import Optional

from src.schemas import ApplicationReport, TailoredResumeArtifact


WORKFLOW_HISTORY_PAYLOAD_VERSION = 1
WORKFLOW_HISTORY_PAYLOAD_KIND_SNAPSHOT = "workflow_snapshot"
WORKFLOW_HISTORY_PAYLOAD_KIND_REPORT = "application_report"
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
            "message": "This saved run uses the current versioned payload envelope for deterministic historical regeneration.",
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
            "message": "This saved run uses the current versioned payload envelope for deterministic historical regeneration.",
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