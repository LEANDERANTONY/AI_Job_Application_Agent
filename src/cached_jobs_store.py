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

import logging
from datetime import datetime, timezone
from typing import Any, Iterable

try:
    from supabase import create_client
    from supabase.client import ClientOptions
except Exception:  # noqa: BLE001 — supabase is optional in dev / tests
    create_client = None
    ClientOptions = None

from src.config import (
    OPENAI_EMBEDDING_INPUT_DESCRIPTION_CHARS,
    SUPABASE_CACHED_JOBS_TABLE,
    SUPABASE_SAVED_JOBS_TABLE,
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_URL,
    is_job_search_hybrid_enabled,
)
from src.errors import AppError
from src.job_search_synonyms import expand_query
from src.logging_utils import get_logger, log_event

LOGGER = get_logger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_job_embedding_input(
    *,
    title: str,
    company: str,
    description: str,
    description_chars: int = OPENAI_EMBEDDING_INPUT_DESCRIPTION_CHARS,
) -> str:
    """Compose the text embedded for one job (Tier 2 semantic search).

    title + company + a capped description snippet. This is the SINGLE
    source of truth for the embedding input format — both the corpus
    backfill (`scripts/backfill_job_embeddings.py`) and the embed-on-
    write path (`CachedJobsStore.upsert_postings`) call it, so a
    backfilled vector and an embed-on-write vector for the same job are
    built identically and therefore comparable.

    The description is truncated to `description_chars` to bound the
    per-row token cost. Empty fields are dropped; a row with no usable
    text still yields a non-empty placeholder (the embeddings API
    rejects empty input).
    """
    title_clean = str(title or "").strip()
    company_clean = str(company or "").strip()
    description_clean = str(description or "").strip()
    if description_chars > 0 and len(description_clean) > description_chars:
        description_clean = description_clean[:description_chars]

    parts: list[str] = []
    if title_clean:
        parts.append(f"Job title: {title_clean}")
    if company_clean:
        parts.append(f"Company: {company_clean}")
    if description_clean:
        parts.append(f"Description: {description_clean}")
    return "\n".join(parts) if parts else "(no job details)"


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
        openai_service=None,
    ):
        self._url = supabase_url
        self._service_role_key = service_role_key
        self._table = table_name
        self._saved_jobs_table = saved_jobs_table_name
        self._client = None
        # Tier 2 hybrid search needs an OpenAIService to embed the query
        # (and to embed newly-cached jobs on write). Constructed lazily
        # so a store built in an environment with no OpenAI key — or
        # with hybrid disabled — never pays for it. Tests inject a fake.
        self._openai_service = openai_service

    def is_configured(self) -> bool:
        return bool(
            self._url
            and self._service_role_key
            and self._table
            and create_client is not None
        )

    def _get_openai_service(self):
        """Lazily build the OpenAIService used for Tier 2 embeddings.

        Imported lazily (not at module load) to avoid a heavy import on
        the cheap-FTS-only path and to keep the import graph shallow.
        Returns None if the service can't be constructed — every caller
        treats a None / unavailable service as "skip embeddings", which
        is the graceful-degradation contract.
        """
        if self._openai_service is None:
            try:
                from src.openai_service import OpenAIService

                self._openai_service = OpenAIService()
            except Exception as exc:  # noqa: BLE001 — embeddings are optional
                log_event(
                    LOGGER,
                    logging.WARNING,
                    "cached_jobs_openai_service_init_failed",
                    "Could not build OpenAIService for job embeddings; "
                    "Tier 2 features degrade to lexical.",
                    error=f"{type(exc).__name__}: {exc}",
                )
                return None
        return self._openai_service

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

        Tier 2 embed-on-write: when hybrid search is enabled, each row's
        `embedding` is computed in the same call so the corpus stays
        current without a re-run of the backfill. This is STRICTLY
        non-fatal — if the embeddings call fails, the jobs are still
        upserted (without an embedding; the hybrid RPC degrades those
        rows to lexical until the next backfill / refresh fills them).
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
        # Tier 2 embed-on-write — non-fatal. Attaches an `embedding` to
        # each row dict in place. Any failure inside leaves the rows
        # embedding-free and the upsert proceeds regardless.
        self._attach_embeddings_on_write(rows)
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

    def _attach_embeddings_on_write(self, rows: list[dict]) -> None:
        """Compute + attach an `embedding` to each upsert row in place.

        The Tier 2 embed-on-write path. Mutates `rows`: on success each
        dict gains an `embedding` key (a list[float]); on ANY failure
        the rows are left untouched and the caller upserts them without
        embeddings. This method NEVER raises — embed-on-write must not
        be able to break the refresh worker.

        Skipped entirely when hybrid search is disabled (no point
        spending tokens on a column nothing queries yet).
        """
        if not rows:
            return
        if not is_job_search_hybrid_enabled():
            return
        service = self._get_openai_service()
        if service is None or not service.is_available():
            return
        try:
            inputs = [
                build_job_embedding_input(
                    title=row.get("title", ""),
                    company=row.get("company", ""),
                    description=row.get("description", ""),
                )
                for row in rows
            ]
            vectors = service.create_embeddings(
                inputs, task_name="job_embedding_on_write"
            )
        except Exception as exc:  # noqa: BLE001 — embed-on-write is non-fatal
            log_event(
                LOGGER,
                logging.WARNING,
                "cached_jobs_embed_on_write_failed",
                "Embed-on-write failed; jobs cached without embeddings "
                "(they fall back to lexical until the next backfill).",
                row_count=len(rows),
                error=f"{type(exc).__name__}: {exc}",
            )
            return
        if len(vectors) != len(rows):
            # Count mismatch — can't safely pair vectors to rows; skip
            # attaching rather than risk the wrong vector on a job.
            log_event(
                LOGGER,
                logging.WARNING,
                "cached_jobs_embed_on_write_count_mismatch",
                "Embed-on-write returned a mismatched vector count; "
                "jobs cached without embeddings.",
                row_count=len(rows),
                vector_count=len(vectors),
            )
            return
        for row, vector in zip(rows, vectors):
            row["embedding"] = vector

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

    # Allowed values for the dropdown-driven filters. Anything outside
    # these whitelists silently drops so the RPC never sees a value
    # that won't match a row anyway.
    _ALLOWED_WORK_MODES = ("remote", "hybrid", "onsite")
    _ALLOWED_EMPLOYMENT_TYPES = (
        "fulltime", "parttime", "contract", "internship", "temporary",
    )
    _ALLOWED_SORT_BY = ("relevance", "newest", "oldest", "company_az")

    def search(
        self,
        *,
        query: str,
        location: str = "",
        sources: list[str] | None = None,
        remote_only: bool = False,
        posted_within_days: int | None = None,
        limit: int = 20,
        work_modes: list[str] | None = None,
        employment_types: list[str] | None = None,
        sort_by: str = "relevance",
        offset: int = 0,
    ) -> list[dict]:
        """Relevance-ranked Postgres full-text search against cached_jobs.

        Delegates to the search_cached_jobs_ranked RPC — see the
        migration of the same name. The RPC builds the tsquery once,
        applies the FTS filter + facets, and ORDERs by the requested
        sort key. We can't do the rank-ordering through PostgREST's
        filter chain directly: text_search() returns a terminating
        builder that doesn't chain into .order(), and plain .order()
        can't reference a function call. Wrapping it as an RPC keeps
        the round-trip count at one.

        New since v2:
          work_modes — optional list filter on the work_mode generated
            column ('remote' / 'hybrid' / 'onsite'). UI dropdown.
          employment_types — optional list filter on
            employment_type_norm ('fulltime' / 'parttime' / 'contract'
            / 'internship' / 'temporary'). UI dropdown.
          sort_by — 'relevance' (default), 'newest', 'oldest',
            'company_az'. Drives the RPC's ORDER BY branch.

        Empty `query` returns most-recent active jobs (the RPC
        short-circuits the FTS filter when the query is empty).

        Synonym expansion: the raw query is run through
        `expand_query` (src/job_search_synonyms.py) before it becomes
        `p_query`. That turns e.g. "ml engineer" into the
        `to_tsquery`-syntax string
        `(ml | machine<->learning) & (engineer | developer | dev)`
        so abbreviations match their long forms. The RPC's `p_query`
        is therefore a `to_tsquery` expression, NOT raw user text —
        the migration uses `to_tsquery` (not `websearch_to_tsquery`)
        to parse it. `expand_query` returns '' for empty / all-
        punctuation / lone-stopword input, which the RPC still treats
        as "no FTS filter" -> recent jobs.

        Tier 2 hybrid search: when JOB_SEARCH_HYBRID_ENABLED is on,
        this embeds the (expanded) query with text-embedding-3-small
        and calls the `search_cached_jobs_hybrid` RPC, which fuses the
        lexical ranking above with a pgvector semantic ranking via
        Reciprocal Rank Fusion. GRACEFUL DEGRADATION is mandatory: if
        the query-embedding call fails (or hybrid is disabled), this
        falls back to the Tier 1 lexical `search_cached_jobs_ranked`
        path. Search NEVER hard-fails because of Tier 2.
        """
        client = self._require_client()
        # `expand_query` handles its own trimming/lowercasing and emits
        # a to_tsquery-format string (or '' for nothing-searchable).
        normalized_query = expand_query(query)
        normalized_location = str(location or "").strip()
        normalized_sources = (
            [str(s).strip().lower() for s in sources if str(s).strip()]
            if sources
            else None
        )
        # Whitelist the dropdown values so a malformed UI param can't
        # generate a query that returns 0 rows just because of casing
        # ('Remote' vs 'remote') or unknown enums.
        normalized_work_modes = (
            [
                value.strip().lower()
                for value in work_modes
                if value and value.strip().lower() in self._ALLOWED_WORK_MODES
            ]
            if work_modes
            else None
        )
        normalized_employment_types = (
            [
                value.strip().lower()
                for value in employment_types
                if value and value.strip().lower() in self._ALLOWED_EMPLOYMENT_TYPES
            ]
            if employment_types
            else None
        )
        sort_normalized = (sort_by or "relevance").strip().lower()
        if sort_normalized not in self._ALLOWED_SORT_BY:
            sort_normalized = "relevance"

        rpc_args = {
            "p_query": normalized_query,
            "p_location": normalized_location,
            "p_sources": normalized_sources,
            "p_remote_only": bool(remote_only),
            "p_posted_within_days": (
                int(posted_within_days) if posted_within_days else None
            ),
            "p_limit": max(1, min(int(limit or 20), 50)),
            "p_work_modes": normalized_work_modes,
            "p_employment_types": normalized_employment_types,
            "p_sort_by": sort_normalized,
            # Pagination window start. The RPC defaults p_offset to 0,
            # so this is also safe against an older function revision
            # (named-arg call simply uses the default if absent).
            "p_offset": max(0, int(offset or 0)),
        }
        # Tier 2: try the hybrid path first when enabled. It returns
        # None to signal "fall through to lexical" (hybrid disabled, or
        # the query embedding couldn't be produced) — graceful
        # degradation, search must never hard-fail because of Tier 2.
        hybrid_rows = self._search_hybrid(client, rpc_args, normalized_query)
        if hybrid_rows is not None:
            return hybrid_rows

        try:
            response = client.rpc("search_cached_jobs_ranked", rpc_args).execute()
        except Exception as exc:
            raise AppError(
                "Failed to query cached jobs.",
                details=f"{type(exc).__name__}: {exc}",
            ) from exc
        return self._extract_rows(response)

    def _search_hybrid(
        self, client, rpc_args: dict, normalized_query: str
    ) -> list[dict] | None:
        """Run the Tier 2 hybrid search RPC, or return None to fall back.

        Returns the result rows on success; returns None when the
        caller should use the Tier 1 lexical path instead — that
        happens when:
          * hybrid search is disabled (JOB_SEARCH_HYBRID_ENABLED off),
          * the query embedding can't be produced (no OpenAI service,
            service unavailable, or the embeddings call raised), or
          * the `search_cached_jobs_hybrid` RPC call itself raises
            (e.g. the operator hasn't applied the hybrid RPC yet).

        This method NEVER raises — every failure becomes a None return
        so `search()` degrades cleanly to lexical. That is the core
        Tier 2 safety guarantee.
        """
        if not is_job_search_hybrid_enabled():
            return None

        query_embedding = self._embed_search_query(normalized_query)
        if query_embedding is None:
            # Couldn't embed the query — fall back to pure lexical.
            return None

        hybrid_args = dict(rpc_args)
        hybrid_args["p_query_embedding"] = query_embedding
        try:
            response = client.rpc(
                "search_cached_jobs_hybrid", hybrid_args
            ).execute()
        except Exception as exc:  # noqa: BLE001 — degrade to lexical
            log_event(
                LOGGER,
                logging.WARNING,
                "cached_jobs_hybrid_rpc_failed",
                "Hybrid search RPC failed; falling back to lexical search.",
                error=f"{type(exc).__name__}: {exc}",
            )
            return None
        return self._extract_rows(response)

    def _embed_search_query(self, normalized_query: str) -> list[float] | None:
        """Embed the (already synonym-expanded) search query for hybrid
        search. Returns the vector, or None on ANY failure.

        A None return makes `_search_hybrid` fall back to lexical — so
        this is allowed (and expected) to fail softly: no OpenAI key,
        provider outage, etc. all just mean "no semantic signal this
        time".

        The expanded query is a `to_tsquery`-syntax string (e.g.
        `(ml | machine<->learning)`). Embedding that operator-decorated
        string is fine — the embedding model reads it as text and the
        meaningful tokens (ml, machine, learning) still dominate the
        vector. An empty expanded query (browse mode) is not embedded:
        there is no semantic intent to capture, and the hybrid RPC
        treats a NULL embedding as pure-lexical anyway.
        """
        if not str(normalized_query or "").strip():
            return None
        service = self._get_openai_service()
        if service is None or not service.is_available():
            return None
        try:
            vectors = service.create_embeddings(
                [normalized_query], task_name="job_search_query"
            )
        except Exception as exc:  # noqa: BLE001 — degrade to lexical
            log_event(
                LOGGER,
                logging.WARNING,
                "cached_jobs_query_embed_failed",
                "Query embedding failed; hybrid search falls back to "
                "lexical for this query.",
                error=f"{type(exc).__name__}: {exc}",
            )
            return None
        if not vectors or not vectors[0]:
            return None
        return vectors[0]

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
