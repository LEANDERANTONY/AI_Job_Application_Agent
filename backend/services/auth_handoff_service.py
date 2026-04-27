from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from src.errors import InputValidationError

from backend.services.auth_session_service import restore_authenticated_session


HANDOFF_TTL_SECONDS = 60


@dataclass
class WorkspaceHandoffRecord:
    access_token: str
    refresh_token: str
    created_at: float = field(default_factory=time.time)


_HANDOFFS: dict[str, WorkspaceHandoffRecord] = {}
_LOCK = threading.Lock()


def _prune_handoffs() -> None:
    cutoff = time.time() - HANDOFF_TTL_SECONDS
    stale_tokens = [
        token
        for token, record in _HANDOFFS.items()
        if record.created_at < cutoff
    ]
    for token in stale_tokens:
        _HANDOFFS.pop(token, None)


def _append_handoff_query(target_url: str, handoff_token: str) -> str:
    url = str(target_url or "").strip()
    parsed = urlsplit(url)
    query_items = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key != "handoff"
    ]
    query_items.append(("handoff", handoff_token))
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(query_items),
            parsed.fragment,
        )
    )


def start_workspace_handoff(
    *,
    access_token: str,
    refresh_token: str,
    target_url: str,
) -> dict:
    normalized_access = str(access_token or "").strip()
    normalized_refresh = str(refresh_token or "").strip()
    normalized_target = str(target_url or "").strip()

    if not normalized_access or not normalized_refresh:
        raise InputValidationError("Sign in with Google before entering the workspace.")
    if not normalized_target:
        raise InputValidationError("A workspace target URL is required.")

    with _LOCK:
        _prune_handoffs()
        handoff_token = uuid.uuid4().hex
        _HANDOFFS[handoff_token] = WorkspaceHandoffRecord(
            access_token=normalized_access,
            refresh_token=normalized_refresh,
        )

    return {
        "status": "ready",
        "redirect_url": _append_handoff_query(normalized_target, handoff_token),
    }


def exchange_workspace_handoff(*, handoff_token: str) -> dict:
    normalized_token = str(handoff_token or "").strip()
    if not normalized_token:
        raise InputValidationError("A workspace handoff token is required.")

    with _LOCK:
        _prune_handoffs()
        record = _HANDOFFS.pop(normalized_token, None)

    if record is None:
        raise InputValidationError(
            "That workspace handoff expired. Open the workspace from the landing page again."
        )

    return restore_authenticated_session(
        access_token=record.access_token,
        refresh_token=record.refresh_token,
    )
