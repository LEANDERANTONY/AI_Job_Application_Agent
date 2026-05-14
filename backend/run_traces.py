"""Cost-per-LLM-call recorder for AI Job Application Agent.

Each call to ``OpenAIService.run_*`` records one row in
``aijobagent_run_traces`` (see ``docs/sql/supabase-run-traces.sql``)
carrying prompt + completion tokens and a USD cost computed from the
pricing map in ``src/openai_service``. The point is tier-margin
validation — every model-routing decision should be grounded in actual
$ spent per task, not estimated COGS.

This module mirrors the structure of ``backend/quota.py``:

  * A ``_SupabaseRunTracesBackend`` that lazily creates a service-role
    Supabase client and writes rows via the standard
    ``client.table(...).insert(...)`` path. The migration provides an
    RLS policy that lets users read their own rows; writes bypass RLS
    because we use the service-role key, identical to the quota RPC.
  * A ``_InMemoryRunTracesBackend`` fallback when Supabase isn't
    configured (CI without secrets, local dev). The fallback is
    process-local — production must run with the Supabase client.
  * A single public ``record_trace`` helper that the OpenAIService
    bridge can invoke without knowing which backend is active.

Cost computation lives in ``src/openai_service`` next to the rest of
the model-routing surface (pricing-map + token-usage record). This
module is the persistence layer.
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


# Module-level config knob. The table name should match the DDL in
# ``docs/sql/supabase-run-traces.sql``; the env-var override exists for
# the same reason the quota table has one — running parallel staging
# environments off a single Supabase project without colliding rows.
_RUN_TRACES_TABLE = os.getenv("SUPABASE_RUN_TRACES_TABLE", "aijobagent_run_traces").strip()


# ── Public data shape ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class TraceRecord:
    """A single recorded LLM call.

    Mirrors the SQL columns 1:1. ``trace_id`` is filled in by the DB
    default; the application doesn't need to compute it client-side.
    """

    user_id: Optional[str]
    task_name: str
    model_name: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    success: bool = True
    created_at: str = ""


# ── Backend abstraction (parity with backend.quota) ──────────────────────


class _InMemoryRunTracesBackend:
    """Process-local backend used when Supabase isn't configured.

    Mirrors ``_InMemoryQuotaBackend`` in ``backend/quota.py`` — tests
    and local dev still hit the same code path that production uses,
    they just write into an in-process list instead of Postgres.

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

    def insert(self, record: TraceRecord) -> None:
        with self._lock:
            row = {
                "user_id": record.user_id,
                "task_name": record.task_name,
                "model_name": record.model_name,
                "prompt_tokens": int(record.prompt_tokens),
                "completion_tokens": int(record.completion_tokens),
                "cost_usd": float(record.cost_usd),
                "success": bool(record.success),
                "created_at": record.created_at or datetime.now(timezone.utc).isoformat(),
            }
            self._rows.append(row)


class _SupabaseRunTracesBackend:
    """Service-role-backed run-traces persister.

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
        table_name: str = _RUN_TRACES_TABLE,
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

    def insert(self, record: TraceRecord) -> None:
        client = self._require_client()
        row = {
            "user_id": record.user_id,
            "task_name": record.task_name,
            "model_name": record.model_name,
            "prompt_tokens": int(record.prompt_tokens),
            "completion_tokens": int(record.completion_tokens),
            # Postgres numeric accepts a string or a float; passing as
            # str avoids any floating-point surprise on the wire.
            "cost_usd": "{:.6f}".format(float(record.cost_usd)),
            "success": bool(record.success),
        }
        # ``trace_id`` and ``created_at`` are filled in by column defaults;
        # we don't send them client-side so they can't drift from the
        # server clock or the gen_random_uuid() default.
        try:
            client.table(self._table).insert(row).execute()
        except Exception:  # noqa: BLE001 - boundary translation
            # Cost tracking is best-effort: a Supabase outage must not
            # turn a successful OpenAI call into a workflow failure.
            # Re-raise after logging so the caller can decide to swallow
            # (the OpenAI bridge does swallow by design).
            logger.exception(
                "run_trace_insert_failed task=%s model=%s user_id=%s",
                record.task_name,
                record.model_name,
                record.user_id,
            )
            raise


# Module-level singletons. Tests reach in via ``reset_in_memory_backend``
# or by monkeypatching ``_BACKEND`` directly. Production resolves to the
# Supabase backend automatically once the env vars are set.
_IN_MEMORY_BACKEND = _InMemoryRunTracesBackend()
_SUPABASE_BACKEND = _SupabaseRunTracesBackend()


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

    Test helper: when a test wants to assert ``record_trace`` actually
    persisted a row, it can read here without monkey-patching the
    backend object. Production callers never hit this — the path goes
    through Supabase.
    """
    return _IN_MEMORY_BACKEND.rows()


# ── Public API ────────────────────────────────────────────────────────────


def record_trace(
    *,
    task_name: str,
    model_name: str,
    prompt_tokens: int,
    completion_tokens: int,
    cost_usd: float,
    user_id: Optional[str] = None,
    success: bool = True,
) -> None:
    """Insert a row into ``aijobagent_run_traces``.

    Called from the OpenAIService bridge after every successful LLM
    response. Best-effort: any backend error is logged and swallowed so
    cost-tracking outages don't propagate into a workflow failure.

    ``user_id`` is ``None`` when the caller is unauthenticated (e.g.
    the assistant in product-help mode). The DB schema permits NULL on
    that column for this reason -- the row is still useful for fleet-
    wide aggregates even without a user attribution.
    """
    record = TraceRecord(
        user_id=user_id,
        task_name=task_name or "",
        model_name=model_name or "",
        prompt_tokens=int(prompt_tokens or 0),
        completion_tokens=int(completion_tokens or 0),
        cost_usd=float(cost_usd or 0.0),
        success=bool(success),
    )
    backend = _select_backend()
    try:
        backend.insert(record)
    except Exception:
        # Already logged inside the Supabase branch; the in-memory
        # branch never raises. Swallow so the caller's hot path stays
        # clean.
        return


__all__ = [
    "TraceRecord",
    "record_trace",
    "reset_in_memory_backend",
    "in_memory_rows",
]
