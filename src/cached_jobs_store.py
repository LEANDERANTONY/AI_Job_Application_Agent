"""Supabase store for the cached_jobs table.

Unlike `saved_jobs_store.py` (which queries per-user with the anon
key + user JWT so RLS protects each user's bookmarks), this store
operates on a global, non-user-scoped table. Reads and writes go
through the SERVICE ROLE key, which bypasses RLS — the table itself
has RLS enabled with no policies as defence-in-depth so nothing else
can touch it.

The store is intentionally narrow: bulk upsert (used by the refresh
worker), search (used by /jobs/search), and the smart-cleanup
operations (delete missing-and-unsaved + tombstone missing-but-saved).
Per-row CRUD is not exposed — this table isn't user-editable.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

try:
    from supabase import create_client
    from supabase.client import ClientOptions
except Exception:  # noqa: BLE001 — supabase is optional in dev / tests
    create_client = None
    ClientOptions = None

from src.config import (
    SUPABASE_CACHED_JOBS_TABLE,
    SUPABASE_SAVED_JOBS_TABLE,
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_URL,
)
from src.errors import AppError


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_iso(value) -> str | None:
    """Best-effort normalize a posted_at value to an ISO-8601 string.

    JobPosting.posted_at is a string from upstream (sometimes already
    ISO, sometimes 'Z'-suffixed, sometimes empty). Return None when
    we can't parse it — the column is nullable.
    """
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.isoformat()
    except ValueError:
        return None


def _normalize_metadata(value) -> dict:
    if isinstance(value, dict):
        return value
    return {}


class CachedJobsStore:
    """Service-role-backed access layer for cached_jobs.

    All methods require Supabase to be fully configured (URL + service
    role key). They raise AppError otherwise so the caller can surface
    a clean message instead of crashing.
    """

    def __init__(
        self,
        *,
        supabase_url: str = SUPABASE_URL,
        service_role_key: str = SUPABASE_SERVICE_ROLE_KEY,
        table_name: str = SUPABASE_CACHED_JOBS_TABLE,
        saved_jobs_table_name: str = SUPABASE_SAVED_JOBS_TABLE,
    ):
        self._url = supabase_url
        self._service_role_key = service_role_key
        self._table = table_name
        self._saved_jobs_table = saved_jobs_table_name
        self._client = None

    def is_configured(self) -> bool:
        return bool(
            self._url
            and self._service_role_key
            and self._table
            and create_client is not None
        )

    def _require_client(self):
        if not self.is_configured():
            raise AppError(
                "cached_jobs store is not configured. Set SUPABASE_URL and "
                "SUPABASE_SERVICE_ROLE_KEY."
            )
        if self._client is None:
            # ClientOptions defaults are fine for service-role usage —
            # no PKCE, no session storage, just a stateless admin client.
            self._client = create_client(self._url, self._service_role_key)
        return self._client

    # -- Writes ---------------------------------------------------------

    def upsert_postings(self, source: str, postings: Iterable) -> int:
        """Bulk-upsert one source's postings. Returns row count touched.

        Each posting is a `JobPosting` dataclass (or anything with
        matching attributes — `id`, `source`, `title`, `company`, etc.).
        Conflict key is (source, job_id) so re-runs are idempotent.
        """
        client = self._require_client()
        rows = []
        now = _utc_now_iso()
        for posting in postings:
            job_id = str(getattr(posting, "id", "") or "").strip()
            if not job_id:
                continue
            rows.append(
                {
                    "source": source,
                    "job_id": job_id,
                    "title": str(getattr(posting, "title", "") or ""),
                    "company": str(getattr(posting, "company", "") or ""),
                    "location": str(getattr(posting, "location", "") or ""),
                    "employment_type": str(getattr(posting, "employment_type", "") or ""),
                    "url": str(getattr(posting, "url", "") or ""),
                    "summary": str(getattr(posting, "summary", "") or ""),
                    "description": str(getattr(posting, "description_text", "") or ""),
                    "posted_at": _coerce_iso(getattr(posting, "posted_at", "")),
                    "metadata": _normalize_metadata(getattr(posting, "metadata", {})),
                    # `last_seen_at` is updated on every refresh — drives
                    # the "missing from this run" detection later. We set
                    # it client-side instead of relying on a DB DEFAULT
                    # so the timestamp is identical for every row in this
                    # batch (makes the cleanup query simpler to reason
                    # about).
                    "last_seen_at": now,
                    # `removed_at` reset to NULL — if a tombstoned job
                    # came back upstream, it's active again.
                    "removed_at": None,
                }
            )
        if not rows:
            return 0
        try:
            response = (
                client.table(self._table)
                .upsert(rows, on_conflict="source,job_id")
                .execute()
            )
        except Exception as exc:
            raise AppError(
                "Failed to upsert cached jobs.",
                details=f"{type(exc).__name__}: {exc}",
            ) from exc
        return len(self._extract_rows(response))

    def cleanup_missing(
        self,
        *,
        sources_refreshed: list[str],
        cutoff_iso: str,
    ) -> tuple[int, int]:
        """Run the smart cleanup for a refresh cycle.

        For each source in `sources_refreshed`, find rows whose
        `last_seen_at < cutoff_iso` (i.e., they didn't get touched
        in the latest refresh). Then split into two buckets:
          - rows that some user has saved → tombstone (removed_at=NOW)
          - rows nobody saved → hard delete

        Returns (tombstoned_count, deleted_count).

        Sources NOT in `sources_refreshed` are left alone — if a
        Greenhouse refresh fails entirely we don't want to vaporise
        every Greenhouse cache row just because one HTTP call timed
        out. Only successfully-refreshed sources are eligible for
        cleanup.
        """
        if not sources_refreshed:
            return (0, 0)

        client = self._require_client()
        now = _utc_now_iso()

        # Step 1: load all (source, job_id) for saved bookmarks across
        # all users — this is the "keep alive even if dead upstream" set.
        try:
            saved_response = (
                client.table(self._saved_jobs_table)
                .select("source,job_id")
                .in_("source", sources_refreshed)
                .execute()
            )
        except Exception as exc:
            raise AppError(
                "Failed to load saved-jobs anchors for cleanup.",
                details=f"{type(exc).__name__}: {exc}",
            ) from exc
        saved_keys: set[tuple[str, str]] = set()
        for row in self._extract_rows(saved_response):
            saved_keys.add(
                (
                    str(row.get("source", "") or "").strip(),
                    str(row.get("job_id", "") or "").strip(),
                )
            )

        # Step 2: load missing rows for the refreshed sources. Limited
        # column select (id + source + job_id) keeps the payload small
        # even at 10k+ rows.
        try:
            missing_response = (
                client.table(self._table)
                .select("id,source,job_id")
                .in_("source", sources_refreshed)
                .lt("last_seen_at", cutoff_iso)
                .is_("removed_at", "null")
                .execute()
            )
        except Exception as exc:
            raise AppError(
                "Failed to enumerate missing cached jobs.",
                details=f"{type(exc).__name__}: {exc}",
            ) from exc
        missing_rows = self._extract_rows(missing_response)

        tombstone_ids: list[int] = []
        delete_ids: list[int] = []
        for row in missing_rows:
            row_id = row.get("id")
            if row_id is None:
                continue
            key = (
                str(row.get("source", "") or "").strip(),
                str(row.get("job_id", "") or "").strip(),
            )
            if key in saved_keys:
                tombstone_ids.append(int(row_id))
            else:
                delete_ids.append(int(row_id))

        tombstoned = 0
        deleted = 0

        if tombstone_ids:
            try:
                (
                    client.table(self._table)
                    .update({"removed_at": now})
                    .in_("id", tombstone_ids)
                    .execute()
                )
            except Exception as exc:
                raise AppError(
                    "Failed to tombstone missing cached jobs.",
                    details=f"{type(exc).__name__}: {exc}",
                ) from exc
            tombstoned = len(tombstone_ids)

        if delete_ids:
            try:
                (
                    client.table(self._table)
                    .delete()
                    .in_("id", delete_ids)
                    .execute()
                )
            except Exception as exc:
                raise AppError(
                    "Failed to delete unsaved missing cached jobs.",
                    details=f"{type(exc).__name__}: {exc}",
                ) from exc
            deleted = len(delete_ids)

        return (tombstoned, deleted)

    # -- Reads ----------------------------------------------------------

    def search(
        self,
        *,
        query: str,
        location: str = "",
        sources: list[str] | None = None,
        remote_only: bool = False,
        posted_within_days: int | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Postgres full-text search against cached_jobs.

        Built via Supabase's PostgREST `text_search` filter (delegates
        to `to_tsquery` server-side). When `query` is empty we skip
        text-search and return the most recent active jobs — useful
        for the "browse all" / front-page use case.
        """
        client = self._require_client()
        builder = (
            client.table(self._table)
            .select(
                "id,source,job_id,title,company,location,employment_type,"
                "url,summary,description,remote,posted_at,metadata,"
                "first_seen_at,last_seen_at,removed_at"
            )
            .is_("removed_at", "null")
        )
        normalized_query = str(query or "").strip()
        if normalized_query:
            # PostgREST exposes Postgres FTS via the `fts` filter on
            # tsvector columns. `wfts` ('websearch_to_tsquery') is the
            # most user-friendly variant — handles "machine learning"
            # / "ml engineer" / quoted phrases naturally.
            builder = builder.text_search(
                "search_tsv", normalized_query, config="english", type_="websearch"
            )
        normalized_location = str(location or "").strip()
        if normalized_location:
            builder = builder.ilike("location", f"%{normalized_location}%")
        if sources:
            builder = builder.in_("source", [str(s).strip().lower() for s in sources])
        if remote_only:
            builder = builder.eq("remote", True)
        if posted_within_days:
            cutoff = (
                datetime.now(timezone.utc).timestamp()
                - int(posted_within_days) * 86400
            )
            cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat()
            builder = builder.gte("posted_at", cutoff_iso)
        try:
            response = (
                builder.order("posted_at", desc=True)
                .limit(max(1, min(int(limit or 20), 50)))
                .execute()
            )
        except Exception as exc:
            raise AppError(
                "Failed to query cached jobs.",
                details=f"{type(exc).__name__}: {exc}",
            ) from exc
        return self._extract_rows(response)

    def get_listing_status_map(
        self, keys: list[tuple[str, str]]
    ) -> dict[tuple[str, str], bool]:
        """Look up listing-active status for a batch of (source, job_id)
        pairs.

        Returns a dict {(source, job_id): is_active}. The is_active
        bool reflects:
          - True: row exists in cache AND removed_at IS NULL (or row
            doesn't exist in cache at all — defaults to optimistic
            for jobs from sources we don't track)
          - False: row exists AND removed_at IS NOT NULL (the upstream
            board stopped listing it; row was kept around because the
            user has it bookmarked)

        Used by the saved-jobs list endpoint to render an "Expired"
        badge on bookmarks whose listings have gone away.
        """
        if not keys:
            return {}
        client = self._require_client()
        # PostgREST doesn't support tuple-IN, so query in two phases:
        # filter by sources first (one round trip), then look up
        # job_ids per source. For our scale (typical user has < 50
        # bookmarks across < 5 sources) this is fine.
        sources = sorted({k[0] for k in keys if k[0]})
        job_ids = sorted({k[1] for k in keys if k[1]})
        if not sources or not job_ids:
            return {}
        try:
            response = (
                client.table(self._table)
                .select("source,job_id,removed_at")
                .in_("source", sources)
                .in_("job_id", job_ids)
                .execute()
            )
        except Exception:
            # Cache lookup failure → return everything as active so the
            # UI doesn't flag good listings as expired.
            return {key: True for key in keys}

        rows = self._extract_rows(response)
        cache_map = {
            (str(row.get("source", "") or ""), str(row.get("job_id", "") or "")): row.get(
                "removed_at"
            )
            is None
            for row in rows
        }
        # Default unknown keys to True (optimistic — don't flag jobs
        # from sources we don't cache as expired).
        return {key: cache_map.get(key, True) for key in keys}

    def count_active(self) -> int:
        """Total active rows. Useful for /admin/refresh-cache health
        checks and for the /api/health endpoint."""
        client = self._require_client()
        try:
            response = (
                client.table(self._table)
                .select("id", count="exact")
                .is_("removed_at", "null")
                .limit(1)
                .execute()
            )
        except Exception:
            return 0
        return int(getattr(response, "count", 0) or 0)

    # -- Helpers --------------------------------------------------------

    @staticmethod
    def _extract_rows(response: Any):
        if response is None:
            return []
        if isinstance(response, list):
            return response
        if isinstance(response, dict):
            return response.get("data") or []
        return getattr(response, "data", None) or []
