# ADR-033: Hybrid Lexical + Semantic Job Search

- Status: Accepted
- Date: 2026-05-22

## Context

[ADR-014](ADR-014-postgres-rpc-for-ranked-search.md) shipped
`search_cached_jobs_ranked` — lexical full-text search over the
`cached_jobs` index ([ADR-013](ADR-013-cached-jobs-cache-layer-with-scheduled-refresh.md))
with `ts_rank`, filters, and sort. It is fast and precise on exact
keywords, but lexical FTS has a structural ceiling: it can only rank a
job that literally shares tokens with the query.

A relevance audit of the ~14k-row corpus (DEVLOG Day 68 — a fixed
query set scored against the results it returned) found the two
failure modes that ceiling produces:

- **Abbreviation / synonym misses.** "ml engineer" does not match a
  posting titled "Machine Learning Engineer"; "frontend" misses
  "React Developer"; "k8s" misses "Kubernetes".
- **Conceptual misses.** A job that is a strong fit but shares no
  surface tokens with the query never surfaces at all.

ADR-014's own follow-up anticipated this ("if the cache grows … add a
tsvector index … consider pg_trgm"). The decision here is the
relevance upgrade itself.

## Decision

**A three-tier relevance design. Tiers 1 and 2 are shipped; Tier 3 is
explicitly out of scope at this stage.**

### Tier 1 — deterministic synonym / abbreviation query expansion

`src/job_search_synonyms.py` `expand_query()` rewrites the raw user
query into a `to_tsquery`-syntax boolean expression before it reaches
Postgres. "ml engineer" becomes
`(ml | machine<->learning) & (engineer | developer | dev)`. The
synonym map is curated from the corpus's own vocabulary (DEVLOG
Day 68); each query token expands to an OR-group of its known
equivalents, and the groups are AND-ed.

- **Deterministic, no LLM, no added latency.** Tier 1 is a pure string
  transform — it cannot fail, cost money, or slow a search down.
- The RPC parses the result with `to_tsquery`, not the
  `websearch_to_tsquery` ADR-014 used, because the expanded string is
  already operator-decorated. Empty / all-stopword input expands to
  `''`, which the RPC treats as "no lexical filter".

### Tier 2 — hybrid lexical + semantic search with RRF

Lexical search, even synonym-expanded, still only matches declared
equivalents. Tier 2 adds a semantic retriever and fuses the two.

1. **pgvector embedding column.** `cached_jobs` gains
   `embedding vector(1536)` (`text-embedding-3-small`) with an HNSW
   cosine index.
2. **A new `search_cached_jobs_hybrid` RPC** runs two retrievers, each
   a top-N query over `cached_jobs` so the index drives candidate
   selection: a lexical pool (`ts_rank` over the GIN index) and a
   semantic pool (cosine distance `<=>` over the HNSW index).
3. **Reciprocal Rank Fusion.** The two pools are fused on their
   *rankings*, not their raw scores: `rrf = 1/(k+lex_rank) +
   1/(k+sem_rank)`, `k = 60`. `ts_rank` and cosine distance live on
   incomparable scales; RRF sidesteps normalization entirely — a job
   ranked highly by *either* signal surfaces.
4. **Embeddings are produced two ways.** A one-time corpus backfill
   (`scripts/backfill_job_embeddings.py`) seeds the existing rows;
   embed-on-write embeds *newly-cached* jobs during the 4-hour refresh
   (only new rows — see DEVLOG Day 75).
5. **Gated and graceful.** The hybrid path is behind the
   `JOB_SEARCH_HYBRID_ENABLED` flag. The query embedding is computed
   backend-side; on *any* failure (flag off, no OpenAI key, embedding
   error, RPC error) the store falls back to the Tier 1 lexical RPC.
   Search never hard-fails because of Tier 2.

The hybrid RPC keeps ADR-014's posture: `SECURITY DEFINER`,
`SET search_path = public`, `EXECUTE` granted to `service_role` only.

### Tier 3 — learned ranker — out of scope

A learned re-ranker trained on click / save / apply signals is the
natural Tier 3. It is deliberately not built: pre-revenue, there is no
interaction data to train on and no labels. RRF is a strong,
zero-training baseline that a Tier 3 ranker would later refine, not
replace.

## Alternatives Considered

### 1. Stay pure lexical (synonym expansion only)
Rejected as the endpoint. Tier 1 alone closes the abbreviation gap but
not the conceptual one — it can only match equivalences someone
thought to add to the map. It ships as Tier 1 *inside* this design,
not instead of it.

### 2. Pure semantic search (replace lexical)
Rejected. Embedding similarity drifts off precise terms — an exact
title or company query underperforms, and rare tokens get washed out.
Lexical precision and semantic recall are complementary; dropping
either loses real results.

### 3. Weighted score blending instead of RRF
Rejected. Blending `ts_rank` and cosine distance needs both on a
common scale; any fixed normalization is a guess that drifts as the
corpus changes. RRF fuses ranks, which are already comparable, and is
the documented production default for hybrid retrieval.

### 4. A managed vector database (Pinecone / Weaviate)
Rejected. pgvector keeps the vectors in the same Postgres that already
holds `cached_jobs` — one datastore, one backup, one access path, the
same `service_role` RPC posture. A separate vector service adds infra,
cost, and a second consistency problem for no gain at this scale.

### 5. IVFFlat index instead of HNSW
Rejected. IVFFlat needs a training pass over a populated table and
re-tuning as the corpus grows. HNSW is correct immediately — which
matters because the `embedding` column is backfilled *after* the index
is created.

## Consequences

### Positive

- Recall improves on both failure modes — abbreviations match their
  long forms, and conceptually-related jobs surface even with zero
  shared tokens.
- Graceful degradation is structural: hybrid is one flag, and every
  Tier 2 failure path falls back to the proven Tier 1 lexical RPC.
- The vector layer is pure Postgres — no new infrastructure, no second
  datastore.

### Negative

- An OpenAI embedding cost: a one-time corpus backfill (the
  \$0.25–0.50 range estimated in DEVLOG Day 70) plus embed-on-write
  for new jobs each refresh (cents/day). Small, but the refresh path
  is no longer strictly \$0 — see `deployment.md`.
- The hybrid path adds a query-embedding round trip (~200–500 ms), and
  the HNSW index adds write cost to the refresh upserts. The Day 75
  incident — re-embedding the whole corpus every refresh churned the
  index and timed the refresh out — is the cautionary tail of that
  write cost; the fix bounds embed-on-write to genuinely new rows.
- Search logic now spans Python (synonym expansion, query embedding,
  fallback orchestration) and two SQL RPCs. The Tier 1 RPC is retained
  as both the fallback and the hybrid-disabled path, so the contract
  surface is two RPCs, not one.

### Neutral

- `JOB_SEARCH_HYBRID_ENABLED` is the operational switch — Tier 2 can
  be turned off without a deploy if the semantic side ever misbehaves.
- The hybrid RPC was revised once post-launch: v1 ranked both sides
  with window functions over the full corpus and hit the statement
  timeout; v2 uses HNSW / GIN candidate pools (DEVLOG Day 74).

## References

- [ADR-013](ADR-013-cached-jobs-cache-layer-with-scheduled-refresh.md)
  — the `cached_jobs` cache layer this search reads from.
- [ADR-014](ADR-014-postgres-rpc-for-ranked-search.md) — the Tier 1
  lexical `search_cached_jobs_ranked` RPC this extends and falls back
  to.
- DEVLOG Days 68 (Tier 1), 70 (Tier 2), 74 (hybrid RPC rewrite), 75
  (embed-on-write fix).
- SQL: `docs/sql/supabase-cached-jobs-search.sql` (Tier 1),
  `supabase-cached-jobs-pgvector.sql` (embedding column + HNSW index),
  `supabase-cached-jobs-hybrid.sql` (hybrid RPC).
- Code: `src/job_search_synonyms.py`, `src/cached_jobs_store.py`,
  `scripts/backfill_job_embeddings.py`.
