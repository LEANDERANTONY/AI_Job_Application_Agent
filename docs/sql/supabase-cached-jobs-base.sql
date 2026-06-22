-- ---------------------------------------------------------------------------
-- supabase-cached-jobs-base — the cached_jobs base table (Tier 1 schema)
-- ---------------------------------------------------------------------------
-- THE TRACKED, REPRODUCIBLE DEFINITION OF `cached_jobs`. Closes the PERFDB-4
-- finding: until this file existed, the base table — the generated columns,
-- the GIN/trgm/partial indexes, the unique key — lived ONLY in the prod
-- Supabase DB and could not be rebuilt from version control. A
-- disaster-recovery rebuild, a fresh staging/preview env, or a project
-- migration that recreated `cached_jobs` WITHOUT (say) the `search_tsv` GIN
-- index would silently turn every `search_cached_jobs_ranked` call into a
-- seq-scan + ts_rank sort over ~14k rows, reproducing the documented
-- statement-timeout collapse. This file is the source of truth; it was
-- captured from the live prod catalog (pg_get_indexdef + pg_attribute +
-- pg_get_expr) on 2026-06-22, not hand-written.
--
-- THIS IS THE COMPLETE *LEAN* (Tier 1, lexical-only) SCHEMA. It includes
-- everything EXCEPT the Tier 2 semantic add-ons:
--   * the `embedding vector(1536)` column  -> docs/sql/supabase-cached-jobs-pgvector.sql
--   * the HNSW cosine index                -> same file
-- Keeping the embedding column in pgvector.sql (not here) gives it ONE
-- source of truth and makes this file double as the "rebuild from scratch on
-- the Supabase free tier" definition — see the "Hybrid-search lean/full
-- switch" runbook in docs/deployment.md.
--
-- REBUILD ORDER (fresh DB):
--   Lean (free tier):  apply THIS file -> apply supabase-cached-jobs-search.sql
--                      (the lexical RPC) -> the 4-hourly refresh fills rows.
--   Full (paid plan):  the above, THEN supabase-cached-jobs-pgvector.sql ->
--                      run scripts/backfill_job_embeddings.py ->
--                      supabase-cached-jobs-hybrid.sql -> flip
--                      JOB_SEARCH_HYBRID_ENABLED=true.
--
-- IDEMPOTENT: CREATE TABLE/INDEX IF NOT EXISTS + guarded constraint adds, so
-- re-applying against the live DB is a safe no-op (it will NOT alter the
-- existing table). Use it to rebuild, or to diff against prod.
--
-- SECURITY: RLS is enabled with NO policies (verified: relrowsecurity=true,
-- 0 policies). The table is reached only by the service-role client, which
-- bypasses RLS; enabling RLS with no policies is defence-in-depth so a
-- mis-scoped anon/authenticated client can never read it. Do NOT add policies
-- — that would imply non-service-role access this table is not designed for.
-- ---------------------------------------------------------------------------

-- pg_trgm backs the title/company trigram GIN indexes (fuzzy company/title
-- matching in lexical search). The `vector` extension is NOT enabled here —
-- it belongs with the embedding column in pgvector.sql.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ---- table -----------------------------------------------------------------
-- `bigserial` reproduces the prod `id bigint DEFAULT nextval('cached_jobs_id_seq')`
-- (bigserial auto-creates the same-named sequence + default). The three
-- GENERATED ALWAYS AS (...) STORED columns are transcribed verbatim from the
-- prod generation expressions — do NOT paraphrase the CASE arms; the partial
-- indexes and the search RPCs depend on these exact normalizations.
CREATE TABLE IF NOT EXISTS public.cached_jobs (
    id              bigserial PRIMARY KEY,
    source          text NOT NULL,
    job_id          text NOT NULL,
    title           text NOT NULL DEFAULT ''::text,
    company         text NOT NULL DEFAULT ''::text,
    location        text NOT NULL DEFAULT ''::text,
    employment_type text NOT NULL DEFAULT ''::text,
    url             text NOT NULL DEFAULT ''::text,
    summary         text NOT NULL DEFAULT ''::text,
    description     text NOT NULL DEFAULT ''::text,
    remote          boolean NOT NULL DEFAULT false,
    posted_at       timestamptz,
    metadata        jsonb NOT NULL DEFAULT '{}'::jsonb,
    first_seen_at   timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
    last_seen_at    timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
    removed_at      timestamptz,

    -- Lexical search vector: title weighted A, company B, description C.
    search_tsv tsvector GENERATED ALWAYS AS (
        (
            setweight(to_tsvector('english'::regconfig, COALESCE(title,   ''::text)), 'A')
         || setweight(to_tsvector('english'::regconfig, COALESCE(company, ''::text)), 'B')
        )
         || setweight(to_tsvector('english'::regconfig, COALESCE(description, ''::text)), 'C')
    ) STORED,

    -- Work-mode dropdown filter, derived from remote flag + metadata + location.
    work_mode text GENERATED ALWAYS AS (
        CASE
            WHEN (remote IS TRUE) THEN 'remote'::text
            WHEN ((metadata ->> 'is_remote'::text) = 'true'::text) THEN 'remote'::text
            WHEN ((metadata ->> 'workplace_type'::text) ~~* 'remote%'::text) THEN 'remote'::text
            WHEN ((metadata ->> 'workplace_type'::text) ~~* 'hybrid%'::text) THEN 'hybrid'::text
            WHEN ((metadata ->> 'workplace_type'::text) ~~* 'in%office%'::text) THEN 'onsite'::text
            WHEN ((metadata ->> 'workplace_type'::text) ~~* 'in%person%'::text) THEN 'onsite'::text
            WHEN (location ~~* '%remote%'::text) THEN 'remote'::text
            WHEN (location ~~* '%hybrid%'::text) THEN 'hybrid'::text
            WHEN (location ~~* '%anywhere%'::text) THEN 'remote'::text
            WHEN (location <> ''::text) THEN 'onsite'::text
            ELSE ''::text
        END
    ) STORED,

    -- Employment-type dropdown filter, normalized from title + raw employment_type.
    employment_type_norm text GENERATED ALWAYS AS (
        CASE
            WHEN (title ~* '\mintern(s|ship|ships)?\M'::text) THEN 'internship'::text
            WHEN (employment_type ~* '\mintern(s|ship|ships)?\M'::text) THEN 'internship'::text
            WHEN (employment_type ~~* '%contract%'::text) THEN 'contract'::text
            WHEN (employment_type ~~* '%contractor%'::text) THEN 'contract'::text
            WHEN ((employment_type ~~* '%temporary%'::text) OR (employment_type ~~* '%temp '::text)) THEN 'temporary'::text
            WHEN ((employment_type ~~* '%part%time%'::text) OR (employment_type ~~* '%parttime%'::text)) THEN 'parttime'::text
            WHEN ((employment_type ~~* '%full%time%'::text) OR (employment_type ~~* '%fulltime%'::text)) THEN 'fulltime'::text
            WHEN (employment_type = 'FullTime'::text) THEN 'fulltime'::text
            WHEN (employment_type = 'PartTime'::text) THEN 'parttime'::text
            ELSE ''::text
        END
    ) STORED
);

-- ---- unique key (the upserts depend on this) -------------------------------
-- on_conflict="source,job_id" in CachedJobsStore.upsert_postings targets this.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'cached_jobs_source_job_id_unique'
    ) THEN
        ALTER TABLE public.cached_jobs
            ADD CONSTRAINT cached_jobs_source_job_id_unique UNIQUE (source, job_id);
    END IF;
END$$;

-- ---- indexes (verbatim from pg_get_indexdef; HNSW lives in pgvector.sql) ----
-- Lexical: the GIN on search_tsv is the hard prerequisite for the search RPC.
CREATE INDEX IF NOT EXISTS cached_jobs_search_idx
    ON public.cached_jobs USING gin (search_tsv);
-- Fuzzy title/company matching (pg_trgm).
CREATE INDEX IF NOT EXISTS cached_jobs_title_trgm_idx
    ON public.cached_jobs USING gin (title gin_trgm_ops);
CREATE INDEX IF NOT EXISTS cached_jobs_company_trgm_idx
    ON public.cached_jobs USING gin (company gin_trgm_ops);
-- Filter dropdowns (partial — only live, non-empty rows).
CREATE INDEX IF NOT EXISTS cached_jobs_work_mode_idx
    ON public.cached_jobs USING btree (work_mode)
    WHERE ((removed_at IS NULL) AND (work_mode <> ''::text));
CREATE INDEX IF NOT EXISTS cached_jobs_employment_type_idx
    ON public.cached_jobs USING btree (employment_type_norm)
    WHERE ((removed_at IS NULL) AND (employment_type_norm <> ''::text));
CREATE INDEX IF NOT EXISTS cached_jobs_remote_idx
    ON public.cached_jobs USING btree (remote)
    WHERE ((removed_at IS NULL) AND (remote = true));
CREATE INDEX IF NOT EXISTS cached_jobs_source_idx
    ON public.cached_jobs USING btree (source)
    WHERE (removed_at IS NULL);
-- Recency sort.
CREATE INDEX IF NOT EXISTS cached_jobs_posted_at_idx
    ON public.cached_jobs USING btree (posted_at DESC NULLS LAST)
    WHERE (removed_at IS NULL);
-- Refresh worker keep-alive scan (source, last_seen_at).
CREATE INDEX IF NOT EXISTS cached_jobs_refresh_idx
    ON public.cached_jobs USING btree (source, last_seen_at);

-- ---- RLS (enabled, no policies — service-role-only) ------------------------
ALTER TABLE public.cached_jobs ENABLE ROW LEVEL SECURITY;
