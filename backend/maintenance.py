"""Tier-aware retention sweeper for saved_workspaces (Step 8).

The sweeper applies per-tier retention to the `saved_workspaces`
table. Today every user resolves to "free" (the shim still returns
free for everyone), so in practice the 7-day Free retention is what
fires; the Pro / Business branches are exercised by the tests against
a patched `resolve_user_tier` so the wiring is locked in for the
Stripe cutover.

Retention table (locked by the brief):
    free       7 days
    pro        30 days
    business   unbounded (no deletion on age)

Implementation notes vs HelpmateAI's `sweep_local_workspace_storage`:
  * HelpmateAI's sweeper also cleans up FileStorage objects, orphan
    upload paths, orphan index dirs, etc. AI Job Agent saved workspaces
    are JSON blobs in a Supabase row -- there are no bucket objects or
    on-disk files to chase, so this sweeper is a pure DELETE pass.
  * We resolve each row's owner via `resolve_user_tier(app_user)` per
    the brief, so a future Stripe-aware resolver doesn't need to be
    revisited. App-user records ride in `aijobagent_app_users`; we
    fetch the row by user_id, then hand it to the resolver.
  * Service-role client only -- the sweeper bypasses RLS because it
    crosses user_id partitions. Mirrors `CachedJobsStore`'s
    service-role pattern.

CLI entry point at the bottom mirrors HelpmateAI's
`if __name__ == "__main__": main()`. Operators (or a cron job in the
VPS docker-compose) invoke this directly. The function returns a
`SweepSummary` so the cron log carries a structured record of how
many rows were touched.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from backend.tiers import Tier, resolve_user_tier, retention_days_for_tier
from src.config import (
    SUPABASE_SAVED_WORKSPACES_TABLE,
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_URL,
)
from src.schemas import AppUserRecord


try:  # supabase is an optional dep in some test paths
    from supabase import create_client as _create_supabase_client  # type: ignore
except Exception:  # pragma: no cover - defensive import
    _create_supabase_client = None  # type: ignore


logger = logging.getLogger(__name__)


# Auth-table name. The same constant lives in `src.app_user_store`;
# we recompute it here so the sweeper has no runtime coupling to the
# auth module (which pulls in supabase as well). When SUPABASE_APP_USERS_TABLE
# is renamed via env, this falls through to the default just like the
# auth module does.
_APP_USERS_TABLE = os.getenv("SUPABASE_APP_USERS_TABLE", "app_users").strip()


@dataclass
class SweepSummary:
    """Per-run summary returned by the sweeper.

    `expired_workspaces_deleted` is the count of saved_workspaces rows
    whose `updated_at` was older than the owner's tier retention and
    that we actually deleted. `business_workspaces_skipped` is the
    count of rows whose owner resolved to Business (None retention)
    and were therefore exempted -- separated so operators can sanity-
    check that Business retention is firing.

    `errors` is a count of rows we tried to process but couldn't
    (missing user record, Supabase delete failure, etc.). Per-row
    failures don't abort the sweep -- we want to make progress on
    the rest of the table.
    """

    expired_workspaces_deleted: int = 0
    business_workspaces_skipped: int = 0
    rows_inspected: int = 0
    errors: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


def _parse_timestamp(value: Any) -> Optional[datetime]:
    """Parse the row's `updated_at` (ISO 8601 string or datetime).

    Supabase returns timestamps as strings; the deserialization path
    in some tests hands us a real datetime instead. Both branches
    return a tz-aware UTC datetime so the cutoff math is uniform.
    Returns None on parse failure -- the row gets skipped at the
    call site.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        moment = value
    elif isinstance(value, str):
        if not value.strip():
            return None
        try:
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _service_role_client():
    """Build a service-role Supabase client or return None.

    The sweeper crosses user_id partitions, so it has to bypass RLS;
    only the service role can do that. Returns None when the env
    vars / supabase dep aren't configured -- the caller logs and
    exits cleanly so a misconfigured cron doesn't crash on import.
    """
    if not (SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY):
        return None
    if _create_supabase_client is None:
        return None
    return _create_supabase_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def _load_app_user(client, user_id: str) -> Optional[AppUserRecord]:
    """Fetch the app_users row for a given user_id.

    Used by the sweeper to feed `resolve_user_tier`. We accept None
    on missing/error -- the caller falls back to the Free retention
    in that branch so a tombstoned auth row can't make a workspace
    immortal.
    """
    if not user_id:
        return None
    try:
        response = (
            client.table(_APP_USERS_TABLE)
            .select("*")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001 - boundary
        logger.warning(
            "sweep_app_user_lookup_failed user_id=%s error=%s",
            user_id,
            exc,
        )
        return None
    rows = getattr(response, "data", None) or []
    if not rows:
        return None
    first = rows[0]
    if not isinstance(first, dict):
        return None
    # Reuse the dataclass for a faithful representation of the row.
    # Field shape mirrors `_build_fallback_app_user_record`'s output.
    try:
        return AppUserRecord(
            id=str(first.get("id", "") or ""),
            email=str(first.get("email", "") or ""),
            plan_tier=str(first.get("plan_tier", "free") or "free"),
            account_status=str(
                first.get("account_status", "active") or "active"
            ),
        )
    except Exception:  # pragma: no cover - defensive
        return None


def _delete_workspace(client, user_id: str, table_name: str) -> bool:
    """Delete the saved-workspace row for `user_id`. Returns True on
    success, False on failure (logged). The store upserts on user_id
    so there's at most one row to delete per user."""
    try:
        client.table(table_name).delete().eq("user_id", user_id).execute()
    except Exception as exc:  # noqa: BLE001 - boundary
        logger.warning(
            "sweep_workspace_delete_failed user_id=%s error=%s",
            user_id,
            exc,
        )
        return False
    return True


def _row_should_be_deleted(
    *,
    tier: Tier,
    updated_at: datetime,
    now: datetime,
) -> bool:
    """Decide if a single row's age has exceeded its tier retention.

    Business tier (retention=None) always returns False -- workspaces
    never auto-delete for unbounded retention. Capped tiers compute
    `cutoff = now - retention` and return True when `updated_at <= cutoff`.
    """
    retention_days = retention_days_for_tier(tier)
    if retention_days is None:
        return False
    cutoff = now - timedelta(days=int(retention_days))
    return updated_at <= cutoff


def sweep_expired_workspaces(
    *,
    now: Optional[datetime] = None,
    table_name: str = SUPABASE_SAVED_WORKSPACES_TABLE,
    client=None,
) -> SweepSummary:
    """Delete saved_workspaces rows older than their owner's tier
    retention window. Returns a SweepSummary the caller can log.

    `now` and `client` exist as parameters for the test suite -- the
    happy production path leaves them defaulted. `table_name` exists
    so a future schema migration can run the sweep against a shadow
    table without code change.

    The function is idempotent: a no-op call right after a real sweep
    finds no rows to delete and returns zeros across the board.
    """
    summary = SweepSummary()
    sweep_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    sweep_client = client if client is not None else _service_role_client()
    if sweep_client is None:
        logger.warning(
            "sweep_skipped_no_service_role_client "
            "url_configured=%s key_configured=%s table=%s",
            bool(SUPABASE_URL),
            bool(SUPABASE_SERVICE_ROLE_KEY),
            table_name,
        )
        return summary

    try:
        response = (
            sweep_client.table(table_name)
            .select("user_id,updated_at")
            .execute()
        )
    except Exception as exc:  # noqa: BLE001 - boundary
        logger.exception(
            "sweep_list_failed table=%s error=%s", table_name, exc
        )
        summary.errors += 1
        return summary

    rows = getattr(response, "data", None) or []
    for row in rows:
        if not isinstance(row, dict):
            summary.errors += 1
            continue
        summary.rows_inspected += 1
        user_id = str(row.get("user_id", "") or "")
        updated_at = _parse_timestamp(row.get("updated_at"))
        if not user_id or updated_at is None:
            summary.errors += 1
            continue

        # Tier resolution per the brief: load the auth row and hand
        # it to the resolver. Returning None falls through to Free
        # retention so a missing user record can't make a workspace
        # immortal.
        app_user = _load_app_user(sweep_client, user_id)
        tier = resolve_user_tier(app_user)

        if retention_days_for_tier(tier) is None:
            # Business tier -- skip on age. The row stays until the
            # user explicitly deletes it.
            summary.business_workspaces_skipped += 1
            continue

        if not _row_should_be_deleted(
            tier=tier, updated_at=updated_at, now=sweep_now
        ):
            continue

        if _delete_workspace(sweep_client, user_id, table_name):
            summary.expired_workspaces_deleted += 1
        else:
            summary.errors += 1

    logger.info(
        "sweep_completed expired=%d business_skipped=%d inspected=%d errors=%d",
        summary.expired_workspaces_deleted,
        summary.business_workspaces_skipped,
        summary.rows_inspected,
        summary.errors,
    )
    return summary


def main() -> None:
    """CLI entry point. Mirrors HelpmateAI's `main()` in
    `backend/maintenance.py`.  The cron job (or a one-off operator
    run) invokes this with `python -m backend.maintenance`; output
    is JSON so structured-log pipelines can ingest it directly.
    """
    summary = sweep_expired_workspaces()
    print(json.dumps(summary.to_dict(), indent=2))


if __name__ == "__main__":
    main()


__all__ = [
    "SweepSummary",
    "main",
    "sweep_expired_workspaces",
]
