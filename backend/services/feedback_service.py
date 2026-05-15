"""Online feedback persistence for AI Job Application Agent.

Each user 👍 / 👎 on a tailored resume / cover letter / JD summary /
assistant turn / resume-builder session writes one row to
``aijobagent_feedback`` (see ``docs/sql/supabase-feedback.sql``)
carrying:

  * surface — which artifact / turn was rated
  * rating  — 'up' or 'down'
  * trace_id — optional, nullable, NOT a FK. Lets us correlate feedback
               with the LLM call's cost / model when the surface has a
               single trace to point at. The DB schema permits NULL on
               this column intentionally so a retention sweep on
               aijobagent_run_traces doesn't cascade-delete the
               feedback row.
  * comment — optional free-text, truncated to 4096 chars at the
              service boundary so a malicious 1 GB body can't blow up
              the row.

This module mirrors ``backend/run_traces.py``:

  * A ``_SupabaseFeedbackBackend`` that lazily creates a service-role
    Supabase client and writes rows via the standard
    ``client.table(...).insert(...)`` path.
  * A ``_InMemoryFeedbackBackend`` fallback when Supabase isn't
    configured (CI without secrets, local dev). Process-local;
    production must run with the Supabase client.
  * A single public ``record_feedback`` helper that the route can
    invoke without knowing which backend is active.

Best-effort semantics: a backend exception is logged and re-raised so
the route can convert it into a 502 / 503. Unlike run_traces, feedback
is NOT a side-channel — if a write fails, the user's "Thanks!" UI
would be a lie if we swallowed the error silently.
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from src.config import SUPABASE_SERVICE_ROLE_KEY, SUPABASE_URL


try:  # supabase is optional in some test paths (parity with quota.py)
    from supabase import create_client as _create_supabase_client  # type: ignore
except Exception:  # pragma: no cover - defensive import
    _create_supabase_client = None  # type: ignore


logger = logging.getLogger(__name__)


# Module-level config knob. The env-var override exists for the same
# reason aijobagent_quota_counters has one — running parallel staging
# environments off a single Supabase project without colliding rows.
_FEEDBACK_TABLE = os.getenv("SUPABASE_FEEDBACK_TABLE", "aijobagent_feedback").strip()


# Mirrors the CHECK constraint in supabase-feedback.sql. Kept in sync
# manually because adding a new surface requires a SQL migration anyway,
# and importing the SQL into Python at runtime would be over-engineered.
VALID_SURFACES: frozenset[str] = frozenset(
    {
        "tailored_resume",
        "cover_letter",
        "jd_summary",
        "assistant_turn",
        "resume_builder_session",
    }
)

VALID_RATINGS: frozenset[str] = frozenset({"up", "down"})

# Comment column is `text` so technically unbounded, but the route's
# defense-in-depth check truncates here so a malicious 1 GB body can't
# bloat the row. 4096 chars is plenty for a free-text rating note;
# longer than a tweet but short enough to keep the row indexable.
COMMENT_MAX_CHARS = 4096


# ── Public data shape ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class FeedbackRecord:
    """A single recorded feedback action.

    Mirrors the SQL columns 1:1. ``feedback_id`` / ``created_at`` are
    filled in by DB defaults; the application doesn't need to compute
    them client-side.
    """

    user_id: str
    surface: str
    rating: str
    trace_id: Optional[str] = None
    comment: str = ""
    created_at: str = ""


# ── Backend abstraction (parity with backend.quota / backend.run_traces) ──


class _InMemoryFeedbackBackend:
    """Process-local backend used when Supabase isn't configured.

    Mirrors ``_InMemoryRunTracesBackend`` — tests and local dev still
    hit the same code path that production uses, they just write into
    an in-process list instead of Postgres.

    The store is exposed via ``rows()`` for assertions; ``reset()``
    wipes it between test cases.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: list[dict] = []

    def reset(self) -> None:
        with self._lock:
            self._rows.clear()

    def rows(self) -> list[dict]:
        with self._lock:
            return list(self._rows)

    def insert(self, record: FeedbackRecord) -> None:
        with self._lock:
            row = {
                "user_id": record.user_id,
                "surface": record.surface,
                "rating": record.rating,
                "trace_id": record.trace_id,
                "comment": record.comment,
                "created_at": record.created_at
                or datetime.now(timezone.utc).isoformat(),
            }
            self._rows.append(row)


class _SupabaseFeedbackBackend:
    """Service-role-backed feedback persister.

    Insert-only — reads happen from the frontend / admin dashboard via
    RLS-protected ``select`` against the same table. Lazy client init
    so importing this module without SUPABASE_URL / SERVICE_ROLE_KEY
    doesn't crash; ``is_configured()`` gates which backend
    ``_select_backend`` picks.
    """

    def __init__(
        self,
        *,
        supabase_url: str = SUPABASE_URL,
        service_role_key: str = SUPABASE_SERVICE_ROLE_KEY,
        table_name: str = _FEEDBACK_TABLE,
    ) -> None:
        self._url = supabase_url
        self._key = service_role_key
        self._table = table_name
        self._client = None

    def is_configured(self) -> bool:
        return bool(self._url and self._key and _create_supabase_client is not None)

    def _require_client(self):
        if self._client is None:
            self._client = _create_supabase_client(self._url, self._key)
        return self._client

    def insert(self, record: FeedbackRecord) -> None:
        client = self._require_client()
        row = {
            "user_id": record.user_id,
            "surface": record.surface,
            "rating": record.rating,
            "trace_id": record.trace_id,
            "comment": record.comment,
        }
        try:
            client.table(self._table).insert(row).execute()
        except Exception:  # noqa: BLE001 - boundary translation
            logger.exception(
                "feedback_insert_failed surface=%s user_id=%s",
                record.surface,
                record.user_id,
            )
            raise


# Module-level singletons. Tests reach in via ``reset_in_memory_backend``
# or by monkeypatching ``_BACKEND`` directly. Production resolves to the
# Supabase backend automatically once the env vars are set.
_IN_MEMORY_BACKEND = _InMemoryFeedbackBackend()
_SUPABASE_BACKEND = _SupabaseFeedbackBackend()


def _select_backend():
    if _SUPABASE_BACKEND.is_configured():
        return _SUPABASE_BACKEND
    return _IN_MEMORY_BACKEND


def reset_in_memory_backend() -> None:
    """Wipe the process-local fallback store. Test-only -- production
    runs through Supabase and has no equivalent.
    """
    _IN_MEMORY_BACKEND.reset()


def in_memory_rows() -> list[dict]:
    """Read-only access to the in-memory backend's rows.

    Test helper: when a test wants to assert ``record_feedback`` actually
    persisted a row, it can read here without monkey-patching the
    backend object. Production callers never hit this — the path goes
    through Supabase.
    """
    return _IN_MEMORY_BACKEND.rows()


# ── Public API ────────────────────────────────────────────────────────────


class InvalidFeedbackError(ValueError):
    """Raised by ``record_feedback`` when the surface or rating is
    not in the allowed set. The route converts this to a 400.

    Using a dedicated exception class (rather than a bare ValueError)
    lets the route discriminate between "client sent garbage" (400)
    and "Supabase blew up" (502).
    """


def record_feedback(
    *,
    user_id: str,
    surface: str,
    rating: str,
    trace_id: Optional[str] = None,
    comment: str = "",
) -> dict:
    """Insert a row into ``aijobagent_feedback``.

    Called from POST /workspace/feedback after the route resolves the
    authenticated user. Validates the surface / rating against the
    CHECK constraints (raising InvalidFeedbackError on miss) and
    truncates a long comment so the row stays indexable.

    Returns ``{"status": "recorded", "surface": ..., "rating": ...}``
    so the route can echo the persisted shape back to the frontend's
    optimistic-UI hook. The feedback_id is generated by the DB and not
    surfaced — the application never reads back by id (aggregate
    queries filter on user_id / surface / created_at).
    """
    normalized_surface = str(surface or "").strip()
    if normalized_surface not in VALID_SURFACES:
        raise InvalidFeedbackError(
            f"Unsupported feedback surface: {normalized_surface!r}. "
            f"Allowed: {sorted(VALID_SURFACES)}."
        )
    normalized_rating = str(rating or "").strip()
    if normalized_rating not in VALID_RATINGS:
        raise InvalidFeedbackError(
            f"Rating must be 'up' or 'down', got {normalized_rating!r}."
        )
    if not user_id:
        raise InvalidFeedbackError("user_id is required to record feedback.")

    # Truncate a long comment so a malicious 1 GB body can't bloat the
    # row + index. The cap is defense-in-depth on top of the route's
    # Pydantic max_length check.
    normalized_comment = str(comment or "")
    if len(normalized_comment) > COMMENT_MAX_CHARS:
        normalized_comment = normalized_comment[:COMMENT_MAX_CHARS]

    normalized_trace_id = str(trace_id or "").strip() or None

    record = FeedbackRecord(
        user_id=str(user_id),
        surface=normalized_surface,
        rating=normalized_rating,
        trace_id=normalized_trace_id,
        comment=normalized_comment,
    )
    backend = _select_backend()
    backend.insert(record)
    return {
        "status": "recorded",
        "surface": normalized_surface,
        "rating": normalized_rating,
    }


__all__ = [
    "COMMENT_MAX_CHARS",
    "FeedbackRecord",
    "InvalidFeedbackError",
    "VALID_RATINGS",
    "VALID_SURFACES",
    "in_memory_rows",
    "record_feedback",
    "reset_in_memory_backend",
]
