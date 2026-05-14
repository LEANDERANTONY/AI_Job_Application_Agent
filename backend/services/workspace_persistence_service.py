from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, is_dataclass
from typing import Any

from backend.quota import current_period_key
from backend.services.auth_session_service import resolve_authenticated_context
from backend.tiers import TIER_CAPS, UNLIMITED, resolve_user_tier
from src.cover_letter_builder import build_cover_letter_artifact
from src.errors import QuotaExceededError
from src.resume_builder import build_tailored_resume_artifact
from src.saved_workspace_store import SavedWorkspaceStore
from src.services.jd_summary_service import generate_job_summary_view
from src.workflow_payloads import (
    WORKFLOW_HISTORY_PAYLOAD_KIND_COVER_LETTER,
    WORKFLOW_HISTORY_PAYLOAD_KIND_SNAPSHOT,
    WORKFLOW_HISTORY_PAYLOAD_KIND_TAILORED_RESUME,
    build_saved_cover_letter_from_payload,
    build_saved_tailored_resume_from_payload,
    build_saved_workflow_snapshot_from_payload,
    versioned_payload,
)


def _serialize(value: Any):
    if is_dataclass(value):
        return {key: _serialize(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


def _workspace_signature(snapshot: dict[str, Any]):
    """Stable 64-char sha256 of the canonical workspace payload.

    Previously this stored the full `json.dumps(...)` (~50KB) on every
    saved-workspace row. The signature is write-only — no consumer
    parses it — so the hash is just as useful as a change-detection
    fingerprint while keeping the row trivially small."""
    payload = {
        "candidate_profile": snapshot.get("candidate_profile") or {},
        "job_description": snapshot.get("job_description") or {},
        "fit_analysis": snapshot.get("fit_analysis") or {},
        "tailored_draft": snapshot.get("tailored_draft") or {},
    }
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_workspace_snapshot(snapshot: dict[str, Any] | None):
    payload = dict(snapshot or {})
    required_sections = [
        "candidate_profile",
        "job_description",
        "fit_analysis",
        "tailored_draft",
        "artifacts",
    ]
    for section in required_sections:
        if not isinstance(payload.get(section), dict):
            raise ValueError(section)
    return payload


def save_workspace_snapshot(
    *,
    access_token: str,
    refresh_token: str,
    workspace_snapshot: dict[str, Any] | None,
):
    """Persist (or overwrite) the user's saved workspace.

    Quota gate (Step 6 of tier-enforcement):
      `saved_workspaces` is a PERSISTENT row-count cap, NOT a
      period-keyed counter: Free 1 / Pro 5 / Business UNLIMITED.

      Today's SavedWorkspaceStore upserts on user_id, so a single
      user only ever has at most ONE saved-workspace row -- the
      Free=1 cap is automatically satisfied by the upsert, and
      Pro=5 / Business=UNLIMITED are effectively unused capacity
      against the current schema. The gate enforces the cap
      generically anyway so:
        (a) when the schema migrates to multi-row saved workspaces
            (e.g. one row per saved_workspace_slug or uuid), the
            gate already enforces the Pro=5 ceiling without
            further changes, and
        (b) the structured 429 surface is consistent across saved
            jobs / saved workspaces / period-keyed counters.

      Eviction policy at-cap: REJECT, do not auto-evict the oldest.
      Auto-eviction is surprising; users should explicitly delete a
      saved workspace to make room. The 429 message points them at
      that affordance.

      Re-saving the SAME workspace (same user_id under the upsert
      semantic) is always allowed -- the cap counts distinct slots,
      not lifetime write operations.
    """
    try:
        snapshot = _validate_workspace_snapshot(workspace_snapshot)
    except ValueError as exc:
        raise ValueError(f"workspace_snapshot.{exc.args[0]}")

    context = resolve_authenticated_context(
        access_token=access_token,
        refresh_token=refresh_token,
    )
    saved_workspace_store = SavedWorkspaceStore(context.auth_service)
    if not saved_workspace_store.is_configured():
        raise RuntimeError("Saved workspace persistence is not configured.")

    # Persistent-count quota gate. Skip when the tier cap is UNLIMITED
    # (Business). For capped tiers, the rule is: a NEW slot creation
    # counts toward the cap; UPDATES to an existing slot do not.
    #
    # Today's store upserts on user_id (one row per user). So when the
    # user already has an "available" record, this save is an UPDATE to
    # their existing slot, not a new slot — the cap doesn't apply and
    # the save proceeds. This is critical for the frontend autosave UX:
    # every snapshot refresh after the first save would otherwise 429
    # for Free users (cap=1, 1 >= 1 blocks the upsert).
    #
    # When the schema migrates to per-slot rows (e.g. one row per
    # saved-workspace slug, future PR), `existing_count` becomes the
    # user's actual distinct-slot count and `is_creating_new_slot`
    # becomes True only when the save's slug isn't already in the
    # user's set. The gate logic then naturally blocks the (cap+1)-th
    # distinct slot without revisiting this code path.
    #
    # The 429 message + the saved_jobs gate's parallel "delete to make
    # room" UX still apply for genuinely-new slot creation; this just
    # carves out the upsert path so autosave doesn't break under tier
    # caps the user hasn't actually exceeded.
    tier = resolve_user_tier(context.app_user)
    cap = TIER_CAPS[tier]["saved_workspaces"]
    quota_user_id = str(getattr(context.app_user, "id", "") or "")
    if cap != UNLIMITED and quota_user_id:
        existing_record, existing_status = saved_workspace_store.load_workspace(
            access_token,
            refresh_token,
            quota_user_id,
        )
        is_existing_slot_update = (
            existing_status == "available" and existing_record is not None
        )
        existing_count = 1 if is_existing_slot_update else 0
        is_creating_new_slot = not is_existing_slot_update
        if is_creating_new_slot and existing_count >= cap:
            raise QuotaExceededError(
                "You have reached the saved-workspaces limit for your "
                "plan. Delete an existing saved workspace to make room, "
                "or upgrade to continue saving more.",
                counter="saved_workspaces",
                current=existing_count,
                cap=cap,
                reset_period=current_period_key(),  # informational only -- persistent counters don't reset
                tier=tier,
            )

    artifacts = dict(snapshot.get("artifacts") or {})
    record = saved_workspace_store.save_workspace(
        access_token,
        refresh_token,
        {
            "user_id": context.app_user.id,
            "job_title": str(
                snapshot.get("job_description", {}).get("title", "") or ""
            ),
            "workflow_signature": _workspace_signature(snapshot),
            "workflow_snapshot_json": versioned_payload(
                WORKFLOW_HISTORY_PAYLOAD_KIND_SNAPSHOT,
                {
                    "candidate_profile": snapshot.get("candidate_profile") or {},
                    "job_description": snapshot.get("job_description") or {},
                    "fit_analysis": snapshot.get("fit_analysis") or {},
                    "tailored_draft": snapshot.get("tailored_draft") or {},
                    "agent_result": snapshot.get("agent_result"),
                    "imported_job_posting": snapshot.get("imported_job_posting"),
                },
            ),
            "cover_letter_payload_json": versioned_payload(
                WORKFLOW_HISTORY_PAYLOAD_KIND_COVER_LETTER,
                artifacts.get("cover_letter") or {},
            ),
            "tailored_resume_payload_json": versioned_payload(
                WORKFLOW_HISTORY_PAYLOAD_KIND_TAILORED_RESUME,
                artifacts.get("tailored_resume") or {},
            ),
        },
    )
    return {
        "status": "saved",
        "saved_workspace": {
            "job_title": record.job_title,
            "expires_at": record.expires_at,
            "updated_at": record.updated_at,
        },
    }


def load_saved_workspace_snapshot(*, access_token: str, refresh_token: str):
    context = resolve_authenticated_context(
        access_token=access_token,
        refresh_token=refresh_token,
    )
    saved_workspace_store = SavedWorkspaceStore(context.auth_service)
    if not saved_workspace_store.is_configured():
        raise RuntimeError("Saved workspace persistence is not configured.")

    record, status = saved_workspace_store.load_workspace(
        access_token,
        refresh_token,
        context.app_user.id,
    )
    if record is None:
        return {
            "status": status,
            "saved_workspace": None,
        }

    saved_snapshot = build_saved_workflow_snapshot_from_payload(
        record.workflow_snapshot_json
    )
    if saved_snapshot is None:
        raise RuntimeError(
            "The saved workspace could not be restored safely. Re-run the flow to create a fresh save."
        )

    saved_tailored_resume_artifact = build_saved_tailored_resume_from_payload(
        record.tailored_resume_payload_json
    )
    tailored_resume_artifact = build_tailored_resume_artifact(
        saved_snapshot.candidate_profile,
        saved_snapshot.job_description,
        saved_snapshot.fit_analysis,
        saved_snapshot.tailored_draft,
        agent_result=saved_snapshot.agent_result,
        theme=(
            getattr(saved_tailored_resume_artifact, "theme", None)
            or "classic_ats"
        ),
    )
    cover_letter_artifact = build_saved_cover_letter_from_payload(
        record.cover_letter_payload_json
    ) or build_cover_letter_artifact(
        saved_snapshot.candidate_profile,
        saved_snapshot.job_description,
        saved_snapshot.fit_analysis,
        saved_snapshot.tailored_draft,
        agent_result=saved_snapshot.agent_result,
    )

    workspace_snapshot = {
        "resume_document": {
            "text": saved_snapshot.candidate_profile.resume_text,
            "filetype": "Saved Workspace",
            "source": "saved_workspace",
        },
        "candidate_profile": _serialize(saved_snapshot.candidate_profile),
        "job_description": _serialize(saved_snapshot.job_description),
        "jd_summary_view": generate_job_summary_view(
            openai_service=None,
            job_description=saved_snapshot.job_description,
            imported_job_posting=saved_snapshot.imported_job_posting,
        ),
        "fit_analysis": _serialize(saved_snapshot.fit_analysis),
        "tailored_draft": _serialize(saved_snapshot.tailored_draft),
        "agent_result": _serialize(saved_snapshot.agent_result),
        "artifacts": {
            "tailored_resume": _serialize(tailored_resume_artifact),
            "cover_letter": _serialize(cover_letter_artifact),
        },
        "workflow": {
            "mode": getattr(saved_snapshot.agent_result, "mode", "") or "saved_workspace",
            "assisted_requested": bool(saved_snapshot.agent_result),
            "assisted_available": True,
            "review_approved": bool(
                getattr(getattr(saved_snapshot.agent_result, "review", None), "approved", False)
            ),
            "fallback_reason": str(
                getattr(saved_snapshot.agent_result, "fallback_reason", "") or ""
            ),
        },
        "imported_job_posting": _serialize(saved_snapshot.imported_job_posting),
    }

    return {
        "status": "available",
        "saved_workspace": {
            "job_title": record.job_title,
            "expires_at": record.expires_at,
            "updated_at": record.updated_at,
        },
        "workspace_snapshot": workspace_snapshot,
    }
