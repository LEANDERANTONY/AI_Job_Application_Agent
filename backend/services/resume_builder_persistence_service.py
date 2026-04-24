from __future__ import annotations

from backend.services.auth_session_service import resolve_authenticated_context
from backend.services.resume_builder_service import (
    export_resume_builder_session_payload,
    restore_resume_builder_session_payload,
)
from src.resume_builder_store import ResumeBuilderStore


def _resolve_store(*, access_token: str, refresh_token: str):
    normalized_access = str(access_token or "").strip()
    normalized_refresh = str(refresh_token or "").strip()
    if not normalized_access or not normalized_refresh:
        return None, None

    try:
        context = resolve_authenticated_context(
            access_token=normalized_access,
            refresh_token=normalized_refresh,
        )
    except Exception:
        return None, None

    store = ResumeBuilderStore(context.auth_service)
    if not store.is_configured():
        return None, None
    return context, store


def load_latest_resume_builder_session(*, access_token: str, refresh_token: str):
    context, store = _resolve_store(
        access_token=access_token,
        refresh_token=refresh_token,
    )
    if context is None or store is None:
        return {
            "status": "missing",
            "session": None,
        }

    try:
        record = store.load_latest_session(
            access_token,
            refresh_token,
            context.app_user.id,
        )
    except Exception:
        return {
            "status": "missing",
            "session": None,
        }

    if record is None or not record.session_payload_json:
        return {
            "status": "missing",
            "session": None,
        }

    try:
        session = restore_resume_builder_session_payload(record.session_payload_json)
    except Exception:
        return {
            "status": "missing",
            "session": None,
        }

    return {
        "status": "available",
        "session": session,
    }


def persist_resume_builder_session(
    *,
    access_token: str,
    refresh_token: str,
    session_id: str,
):
    context, store = _resolve_store(
        access_token=access_token,
        refresh_token=refresh_token,
    )
    if context is None or store is None:
        return {"status": "skipped"}

    try:
        session_payload_json = export_resume_builder_session_payload(session_id=session_id)
    except Exception:
        return {"status": "skipped"}

    try:
        store.save_session(
            access_token,
            refresh_token,
            {
                "user_id": context.app_user.id,
                "session_id": session_id,
                "session_payload_json": session_payload_json,
            },
        )
    except Exception:
        return {"status": "skipped"}

    return {"status": "saved"}


def clear_resume_builder_session(*, access_token: str, refresh_token: str):
    context, store = _resolve_store(
        access_token=access_token,
        refresh_token=refresh_token,
    )
    if context is None or store is None:
        return {"status": "skipped"}

    try:
        store.delete_session(access_token, refresh_token, context.app_user.id)
    except Exception:
        return {"status": "skipped"}
    return {"status": "cleared"}
