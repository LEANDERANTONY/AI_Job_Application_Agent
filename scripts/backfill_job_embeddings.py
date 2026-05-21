"""Backfill pgvector embeddings for the cached_jobs corpus (Tier 2).

Tier 2 of the job-search relevance upgrade adds semantic (embedding)
retrieval fused with the Tier 1 lexical search. Before the hybrid RPC
can return anything useful, every active `cached_jobs` row needs an
`embedding` vector. This script computes those vectors with OpenAI
`text-embedding-3-small` and writes them back.

It is a ONE-TIME corpus backfill — after it runs, the embed-on-write
path in `CachedJobsStore.upsert_postings` keeps new rows current, so
this script is normally never needed again. It stays useful as a
re-sync tool if embed-on-write was ever disabled for a stretch.

DESIGN
------
  * Selects only rows where `embedding IS NULL` — so it is idempotent
    and RESUMABLE: a crashed / interrupted run leaves the done rows
    done, and re-running just picks up the remaining NULLs. Running it
    when everything is already embedded is a no-op.
  * Builds the embedding input per row from title + company + a
    description snippet, with the description capped (~2000 chars) to
    bound token cost. `text-embedding-3-small` accepts up to 8191
    tokens; ~2000 chars of description plus the title/company is
    comfortably under that.
  * Calls the embeddings API in BATCHES (the endpoint accepts an array
    — default 100 inputs/call) to respect rate limits: ~14k rows is
    ~140 HTTP round-trips, not 14k.
  * Writes each row's vector back individually keyed on the primary
    `id`. A failed batch is logged and SKIPPED (those rows stay NULL
    and a later run retries them) — one bad batch never aborts the
    whole backfill.

COST ESTIMATE
-------------
~14k jobs * ~800 tokens average input * $0.02 / 1M tokens
  ~= $0.25 - $0.50, one-time. (text-embedding-3-small is $0.02/1M
  input tokens; the per-row input is title + company + a <=2000-char
  description snippet, averaging well under 1k tokens.)

RUN COMMAND
-----------
This is an OPERATOR ACTION — see the Day 69 DEVLOG "OPERATOR ACTION
REQUIRED" runbook. Run it AFTER applying
`docs/sql/supabase-cached-jobs-pgvector.sql` (the `embedding` column
must exist) and BEFORE applying the hybrid RPC.

  Requires env: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, and an
  OpenAI key (OPENAI_API_KEY or openai_key.txt).

  # dry run — counts rows, embeds nothing, costs nothing:
  python scripts/backfill_job_embeddings.py --dry-run

  # real backfill:
  python scripts/backfill_job_embeddings.py

  # tuning knobs (defaults shown):
  python scripts/backfill_job_embeddings.py --batch-size 100 \
      --description-chars 2000 --limit 0

`--limit N` caps how many rows to process this run (0 = all); handy
for a small canary batch before committing to the full corpus.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# Allow `python scripts/backfill_job_embeddings.py` to import `src.*`
# when run directly from the repo root (scripts/ is not a package).
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.cached_jobs_store import build_job_embedding_input  # noqa: E402
from src.config import (  # noqa: E402 — after sys.path bootstrap
    OPENAI_EMBEDDING_INPUT_DESCRIPTION_CHARS,
    OPENAI_EMBEDDING_MODEL,
    SUPABASE_CACHED_JOBS_TABLE,
    SUPABASE_SERVICE_ROLE_KEY,
    SUPABASE_URL,
)
from src.openai_service import OpenAIService  # noqa: E402

LOGGER = logging.getLogger("backfill_job_embeddings")

# Defaults. The embeddings endpoint accepts arrays — 100 inputs/call
# keeps round-trips low without risking an oversized request.
DEFAULT_BATCH_SIZE = 100
# Cap the description slice fed into the embedding input. Shared with the
# embed-on-write path via the config constant so a backfilled vector and
# an embed-on-write vector for the same job are built identically.
DEFAULT_DESCRIPTION_CHARS = OPENAI_EMBEDDING_INPUT_DESCRIPTION_CHARS


def build_embedding_input(row: dict, *, description_chars: int) -> str:
    """Compose the text to embed for one cached_jobs row.

    A thin row-dict adapter over `cached_jobs_store.build_job_embedding_
    input` — the SINGLE source of truth for the job-embedding input
    format. Sharing it guarantees the backfill and the embed-on-write
    path produce identical inputs (hence comparable vectors).
    """
    return build_job_embedding_input(
        title=row.get("title", ""),
        company=row.get("company", ""),
        description=row.get("description", ""),
        description_chars=description_chars,
    )


def _build_supabase_client():
    """Service-role Supabase client for the backfill.

    Mirrors `CachedJobsStore`'s posture — the service role bypasses RLS,
    which the cached_jobs table relies on (RLS enabled, no policies).
    """
    if not (SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY):
        raise SystemExit(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set to "
            "run the embedding backfill."
        )
    try:
        from supabase import create_client
    except Exception as exc:  # noqa: BLE001 — supabase optional in some envs
        raise SystemExit(
            f"supabase-py is not importable: {type(exc).__name__}: {exc}"
        ) from exc
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def fetch_unembedded_rows(client, table: str, *, limit: int) -> list[dict]:
    """Load cached_jobs rows that still need an embedding.

    Only `embedding IS NULL` rows — that NULL filter is what makes the
    backfill idempotent + resumable. Selects just the columns the
    embedding input needs plus the `id` primary key for the write-back.
    `limit <= 0` means "all".
    """
    query = (
        client.table(table)
        .select("id,title,company,description")
        .is_("embedding", "null")
        .order("id", desc=False)
    )
    if limit and limit > 0:
        query = query.limit(limit)
    response = query.execute()
    return list(getattr(response, "data", None) or [])


def write_embedding(client, table: str, row_id, vector: list[float]) -> None:
    """Persist one row's embedding vector, keyed on the primary id."""
    client.table(table).update({"embedding": vector}).eq("id", row_id).execute()


def _chunked(items: list, size: int):
    """Yield successive `size`-length slices of `items`."""
    for start in range(0, len(items), max(1, size)):
        yield items[start : start + size]


def run_backfill(
    *,
    client,
    openai_service: OpenAIService,
    table: str,
    batch_size: int,
    description_chars: int,
    limit: int,
    dry_run: bool,
) -> dict:
    """Embed every NULL-embedding row and write the vectors back.

    Returns a summary dict: rows considered, embedded, failed, batches.
    Injectable `client` + `openai_service` make this unit-testable with
    a fake Supabase client and a mocked OpenAI client.
    """
    rows = fetch_unembedded_rows(client, table, limit=limit)
    summary = {
        "rows_considered": len(rows),
        "rows_embedded": 0,
        "rows_failed": 0,
        "batches_total": 0,
        "batches_failed": 0,
        "dry_run": dry_run,
    }
    if not rows:
        LOGGER.info("No rows need embeddings — nothing to do.")
        return summary

    LOGGER.info(
        "Backfilling embeddings for %d row(s) in '%s' (batch_size=%d, "
        "description_chars=%d, dry_run=%s).",
        len(rows),
        table,
        batch_size,
        description_chars,
        dry_run,
    )

    for batch in _chunked(rows, batch_size):
        summary["batches_total"] += 1
        inputs = [
            build_embedding_input(row, description_chars=description_chars)
            for row in batch
        ]

        if dry_run:
            # Count what WOULD be embedded; make no API call, no write.
            summary["rows_embedded"] += len(batch)
            continue

        try:
            vectors = openai_service.create_embeddings(
                inputs, task_name="job_embedding_backfill"
            )
        except Exception as exc:  # noqa: BLE001 — skip the batch, keep going
            summary["batches_failed"] += 1
            summary["rows_failed"] += len(batch)
            LOGGER.warning(
                "Embedding batch %d failed (%d rows skipped, stay NULL "
                "for a later re-run): %s: %s",
                summary["batches_total"],
                len(batch),
                type(exc).__name__,
                exc,
            )
            continue

        if len(vectors) != len(batch):
            # Defensive: a count mismatch means we cannot reliably pair
            # vectors to rows — skip the whole batch rather than risk
            # writing the wrong vector onto a job.
            summary["batches_failed"] += 1
            summary["rows_failed"] += len(batch)
            LOGGER.warning(
                "Embedding batch %d returned %d vectors for %d inputs — "
                "skipping batch to avoid misaligned writes.",
                summary["batches_total"],
                len(vectors),
                len(batch),
            )
            continue

        for row, vector in zip(batch, vectors):
            row_id = row.get("id")
            if row_id is None:
                summary["rows_failed"] += 1
                continue
            try:
                write_embedding(client, table, row_id, vector)
            except Exception as exc:  # noqa: BLE001 — per-row, keep going
                summary["rows_failed"] += 1
                LOGGER.warning(
                    "Failed to write embedding for row id=%s (stays NULL "
                    "for a later re-run): %s: %s",
                    row_id,
                    type(exc).__name__,
                    exc,
                )
                continue
            summary["rows_embedded"] += 1

    LOGGER.info(
        "Backfill done: %d embedded, %d failed, %d/%d batches failed.",
        summary["rows_embedded"],
        summary["rows_failed"],
        summary["batches_failed"],
        summary["batches_total"],
    )
    return summary


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill pgvector embeddings for cached_jobs (Tier 2)."
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Inputs per embeddings API call (default {DEFAULT_BATCH_SIZE}).",
    )
    parser.add_argument(
        "--description-chars",
        type=int,
        default=DEFAULT_DESCRIPTION_CHARS,
        help=(
            "Max description characters fed into each embedding input "
            f"(default {DEFAULT_DESCRIPTION_CHARS}; 0 = uncapped)."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Cap rows processed this run (0 = all). Useful for a canary.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Count rows + build inputs but make no API calls and no writes.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _parse_args(argv)

    client = _build_supabase_client()
    openai_service = OpenAIService()
    if not args.dry_run and not openai_service.is_available():
        raise SystemExit(
            "OpenAI is not configured (set OPENAI_API_KEY or add "
            "openai_key.txt) — required for a real backfill. Use "
            "--dry-run to count rows without embedding."
        )

    started = time.perf_counter()
    summary = run_backfill(
        client=client,
        openai_service=openai_service,
        table=SUPABASE_CACHED_JOBS_TABLE,
        batch_size=args.batch_size,
        description_chars=args.description_chars,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    elapsed = time.perf_counter() - started
    LOGGER.info(
        "Embedding model=%s, elapsed=%.1fs, summary=%s",
        OPENAI_EMBEDDING_MODEL,
        elapsed,
        summary,
    )
    # Non-zero exit if any row failed so an operator / CI notices.
    return 1 if summary["rows_failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
