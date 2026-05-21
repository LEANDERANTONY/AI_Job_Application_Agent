import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
# Demo / fixture assets live under docs/ alongside the architecture
# diagram, ADRs, and supabase schema files. They are not served at
# runtime by the FastAPI app — they're inputs for tests + the
# eval_resume_parser runner under tests/quality/.
STATIC_DIR = BASE_DIR / "docs" / "static"
DEMO_RESUME_DIR = STATIC_DIR / "demo_resume"
DEMO_JOB_DESCRIPTION_DIR = STATIC_DIR / "demo_job_description"
OPENAI_KEY_PATH = BASE_DIR / "openai_key.txt"
OPENAI_MODEL_DEFAULT = os.getenv(
    "OPENAI_MODEL_DEFAULT",
    os.getenv("OPENAI_MODEL", "gpt-5.4-mini"),
)
OPENAI_MODEL_HIGH_TRUST = os.getenv("OPENAI_MODEL_HIGH_TRUST", "gpt-5.4")
# Premium tier upgrade for the three high-trust agents (review,
# resume_generation, cover_letter) when the caller passes premium=True
# AND the user's tier supports it (Pro / Business). Tailoring stays on
# mini regardless — the COGS analysis showed that only the three
# review-grade agents benefit from the upgrade.
#
# Selection is enforced in `backend/model_routing.select_workflow_model`;
# the global default below stays at gpt-5.5 so a premium override can be
# resolved through `get_openai_model_for_task("premium_high_trust")`
# without callers having to know the env var name.
OPENAI_MODEL_PREMIUM = os.getenv("OPENAI_MODEL_PREMIUM", "gpt-5.5")
OPENAI_MODEL_MID_TIER = os.getenv("OPENAI_MODEL_MID_TIER", OPENAI_MODEL_DEFAULT)
OPENAI_MODEL_PRODUCT_HELP = os.getenv(
    "OPENAI_MODEL_PRODUCT_HELP", OPENAI_MODEL_MID_TIER
)
OPENAI_MODEL_APPLICATION_QA = os.getenv(
    "OPENAI_MODEL_APPLICATION_QA", OPENAI_MODEL_HIGH_TRUST
)
OPENAI_MODEL_ASSISTANT = os.getenv(
    "OPENAI_MODEL_ASSISTANT", "gpt-5.4-mini"
)
OPENAI_REASONING_DEFAULT = os.getenv("OPENAI_REASONING_DEFAULT", "medium").strip().lower()
OPENAI_REASONING_HIGH_TRUST = os.getenv(
    "OPENAI_REASONING_HIGH_TRUST", "high"
).strip().lower()
# Workspace-assistant reasoning effort. Default lowered from "medium"
# to "low" on 2026-05-21 after the Slice 1K eval matrix showed
# gpt-5.4-mini@low matched gpt-5.4-mini@medium with a PERFECT 1.000
# score on the same 12 scenarios (product-knowledge fluency, honest
# refusals, grounding discipline, multi-turn memory) at 32% lower
# latency and 15% lower cost. The assistant is a retrieve-and-refuse
# surface — thinking-token spend beyond "low" earns nothing on this
# rubric. Operators can still override via env var if a future
# regression surfaces. See
# `docs/eval-runs/2026-05-21-assistant-eval-report.md`
# (addendum: gpt-5.4-mini@low sweep) for the data.
OPENAI_REASONING_ASSISTANT = os.getenv(
    "OPENAI_REASONING_ASSISTANT", "low"
).strip().lower()
OPENAI_MODEL_ROUTING = {
    "jd_summary": os.getenv("OPENAI_MODEL_JD_SUMMARY", OPENAI_MODEL_MID_TIER),
    "fit": os.getenv("OPENAI_MODEL_FIT", OPENAI_MODEL_MID_TIER),
    "tailoring": os.getenv("OPENAI_MODEL_TAILORING", OPENAI_MODEL_MID_TIER),
    "review": os.getenv("OPENAI_MODEL_REVIEW", OPENAI_MODEL_HIGH_TRUST),
    "cover_letter": os.getenv("OPENAI_MODEL_COVER_LETTER", OPENAI_MODEL_HIGH_TRUST),
    "resume_generation": os.getenv(
        "OPENAI_MODEL_RESUME_GENERATION", OPENAI_MODEL_HIGH_TRUST
    ),
    # Premium upgrade slot — used by `select_workflow_model` when the
    # request opts into premium AND the user's tier supports it. The
    # task-name "premium_high_trust" doesn't appear in any agent's
    # own task_name (agents always set their own task name like
    # "review" / "cover_letter"); it's looked up via
    # `get_openai_model_for_task("premium_high_trust")` from the
    # routing helper, then passed as an explicit `model=` override
    # into `run_json_prompt`.
    "premium_high_trust": OPENAI_MODEL_PREMIUM,
    "assistant": OPENAI_MODEL_ASSISTANT,
    "assistant_product_help": OPENAI_MODEL_PRODUCT_HELP,
    "assistant_application_qa": OPENAI_MODEL_APPLICATION_QA,
    # Resume-builder intake: short conversational turns over a small
    # JSON envelope. Mini-tier is fine; the work is interview-style
    # parsing rather than long-form reasoning.
    "resume_builder": os.getenv("OPENAI_MODEL_RESUME_BUILDER", OPENAI_MODEL_ASSISTANT),
    # Resume-builder structuring: bigger structured output (multiple
    # arrays + categories + summary). Use the higher-trust tier so the
    # JSON stays well-formed and fact preservation is reliable.
    "resume_builder_structuring": os.getenv(
        "OPENAI_MODEL_RESUME_BUILDER_STRUCTURING", OPENAI_MODEL_HIGH_TRUST
    ),
}
OPENAI_REASONING_ROUTING = {
    "jd_summary": os.getenv("OPENAI_REASONING_JD_SUMMARY", "low").strip().lower(),
    "fit": os.getenv("OPENAI_REASONING_FIT", "low").strip().lower(),
    "tailoring": os.getenv("OPENAI_REASONING_TAILORING", OPENAI_REASONING_DEFAULT).strip().lower(),
    "review": os.getenv("OPENAI_REASONING_REVIEW", OPENAI_REASONING_DEFAULT).strip().lower(),
    "cover_letter": os.getenv("OPENAI_REASONING_COVER_LETTER", OPENAI_REASONING_DEFAULT).strip().lower(),
    "resume_generation": os.getenv(
        "OPENAI_REASONING_RESUME_GENERATION", OPENAI_REASONING_DEFAULT
    ).strip().lower(),
    "assistant": OPENAI_REASONING_ASSISTANT,
    "assistant_product_help": os.getenv(
        "OPENAI_REASONING_PRODUCT_HELP", "low"
    ).strip().lower(),
    "assistant_application_qa": os.getenv(
        "OPENAI_REASONING_APPLICATION_QA", OPENAI_REASONING_HIGH_TRUST
    ).strip().lower(),
    "resume_builder": os.getenv("OPENAI_REASONING_RESUME_BUILDER", "low").strip().lower(),
}
OPENAI_MODEL = OPENAI_MODEL_DEFAULT


def _load_int_env(name: str, default=None):
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    return int(raw_value)


def _load_bool_env(name: str, default: bool = False):
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def resolve_job_backend_base_url(
    explicit_base_url: str = "",
    hostport: str = "",
    default_base_url: str = "http://localhost:8000",
):
    normalized_base_url = str(explicit_base_url or "").strip().rstrip("/")
    if normalized_base_url:
        return normalized_base_url

    normalized_hostport = str(hostport or "").strip()
    if normalized_hostport:
        return f"http://{normalized_hostport}"

    return default_base_url


OPENAI_MAX_COMPLETION_TOKENS_ROUTING = {
    "jd_summary": _load_int_env("OPENAI_MAX_COMPLETION_TOKENS_JD_SUMMARY", 1400),
    "fit": _load_int_env("OPENAI_MAX_COMPLETION_TOKENS_FIT", 1600),
    "tailoring": _load_int_env("OPENAI_MAX_COMPLETION_TOKENS_TAILORING", 3200),
    "review": _load_int_env("OPENAI_MAX_COMPLETION_TOKENS_REVIEW", 4000),
    "cover_letter": _load_int_env("OPENAI_MAX_COMPLETION_TOKENS_COVER_LETTER", 2200),
    "resume_generation": _load_int_env("OPENAI_MAX_COMPLETION_TOKENS_RESUME_GENERATION", 3000),
    "assistant": _load_int_env(
        "OPENAI_MAX_COMPLETION_TOKENS_ASSISTANT",
        _load_int_env("OPENAI_MAX_COMPLETION_TOKENS_APPLICATION_QA", 1400),
    ),
    # Matches the `assistant` / `assistant_application_qa` siblings
    # (1400). product_help routes to a gpt-5-class reasoning model, so
    # max_output_tokens caps reasoning + visible output COMBINED — the
    # old 700 left only ~300-550 tokens for the answer JSON
    # (answer + sources + follow-ups) after "low"-effort reasoning,
    # truncating thorough help answers into invalid JSON and silently
    # falling back to the canned reply. It's a ceiling, not a
    # reservation, so short answers (most of them) cost the same; only
    # the long ones get room to finish. Fast-fail (no budget retry)
    # stays — this fixes the cause, not the interactive behaviour.
    "assistant_product_help": _load_int_env("OPENAI_MAX_COMPLETION_TOKENS_PRODUCT_HELP", 1400),
    "assistant_application_qa": _load_int_env("OPENAI_MAX_COMPLETION_TOKENS_APPLICATION_QA", 1400),
    "resume_builder": _load_int_env("OPENAI_MAX_COMPLETION_TOKENS_RESUME_BUILDER", 1200),
    # Structuring pass — converts free-form experience_notes /
    # education_notes / projects_notes into structured arrays AND
    # optionally produces skill_categories + an expanded
    # professional_summary. Bumped to 4000 once projects + skill
    # categories + summary expansion landed; smaller budgets were
    # truncating the model's JSON mid-output and triggering parse
    # failures (manifesting as `_structure_via_llm` returning None and
    # the regex fallback taking over for the entire payload).
    "resume_builder_structuring": _load_int_env(
        "OPENAI_MAX_COMPLETION_TOKENS_RESUME_BUILDER_STRUCTURING", 4000
    ),
}


# Hard ceiling the output-budget escalation can grow a single request
# to. A task starts at its routed base budget above; if the model
# truncates (status=incomplete, reason=max_output_tokens) the request
# is re-issued with a progressively larger max_output_tokens until the
# response is complete OR this ceiling is hit. The point is that a
# content-rich résumé / JD / tailored analysis should NEVER fall back
# to the deterministic path just because it needed more output room —
# only a genuine provider outage should. 16000 is comfortable headroom
# for every JSON payload we emit (the largest realistic one is a few
# thousand tokens) and well within the gpt-5 / gpt-4.1-class output
# limit. max_output_tokens is a ceiling, not a reservation, so a high
# value is free for ordinary requests. Env-overridable for tuning.
OPENAI_MAX_OUTPUT_TOKENS_CEILING = _load_int_env(
    "OPENAI_MAX_OUTPUT_TOKENS_CEILING", 16000
)


DAILY_QUOTA_CACHE_TTL_SECONDS = _load_int_env("DAILY_QUOTA_CACHE_TTL_SECONDS", 15)
APP_BASE_URL = os.getenv("APP_BASE_URL", "").strip()
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "").strip()
# Service role key — bypasses RLS. Used ONLY by the cached_jobs writer
# (the /admin/refresh-cache endpoint) and the cached_jobs reader (the
# /jobs/search endpoint). Never sent to the frontend, never used for
# user-scoped tables (saved_jobs, etc. — those keep using the anon
# key + per-user JWT so RLS protects them).
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
SUPABASE_AUTH_REDIRECT_URL = os.getenv(
    "SUPABASE_AUTH_REDIRECT_URL",
    APP_BASE_URL or "http://localhost:3000",
).strip()
AUTH_REQUIRED_FOR_ASSISTED_WORKFLOW = _load_bool_env(
    "AUTH_REQUIRED_FOR_ASSISTED_WORKFLOW", True
)
SUPABASE_APP_USERS_TABLE = os.getenv("SUPABASE_APP_USERS_TABLE", "app_users").strip()
SUPABASE_USAGE_EVENTS_TABLE = os.getenv(
    "SUPABASE_USAGE_EVENTS_TABLE", "usage_events"
).strip()
SUPABASE_SAVED_WORKSPACES_TABLE = os.getenv(
    "SUPABASE_SAVED_WORKSPACES_TABLE", "saved_workspaces"
).strip()
SUPABASE_SAVED_JOBS_TABLE = os.getenv(
    "SUPABASE_SAVED_JOBS_TABLE", "saved_jobs"
).strip()
SUPABASE_RESUME_BUILDER_SESSIONS_TABLE = os.getenv(
    "SUPABASE_RESUME_BUILDER_SESSIONS_TABLE", "resume_builder_sessions"
).strip()
SUPABASE_CACHED_JOBS_TABLE = os.getenv(
    "SUPABASE_CACHED_JOBS_TABLE", "cached_jobs"
).strip()
# ── Tier 2 hybrid (lexical + semantic) job search ───────────────────
# Tier 2 adds pgvector embedding search fused with the Tier 1 lexical
# search via Reciprocal Rank Fusion. The embedding model + its output
# dimensionality must agree with the `cached_jobs.embedding vector(N)`
# column (see docs/sql/supabase-cached-jobs-pgvector.sql) and with the
# backfill script. `text-embedding-3-small` emits 1536-dim vectors.
OPENAI_EMBEDDING_MODEL = os.getenv(
    "OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"
).strip()
OPENAI_EMBEDDING_DIMENSIONS = _load_int_env(
    "OPENAI_EMBEDDING_DIMENSIONS", 1536
)
# Master switch for the Tier 2 hybrid search path. Default OFF: the
# hybrid RPC + the embedding column only exist after the operator has
# (1) applied the pgvector schema, (2) run the backfill, and (3)
# applied the hybrid RPC — see the Day 69 DEVLOG runbook. Until then
# the store stays on the Tier 1 lexical `search_cached_jobs_ranked`
# path. Flip this true only AFTER the backfill completes.
JOB_SEARCH_HYBRID_ENABLED = _load_bool_env("JOB_SEARCH_HYBRID_ENABLED", False)
# Shared secret guarding the /admin/refresh-cache endpoint. Set BOTH
# in the backend env (so the endpoint can verify the bearer token)
# AND in the Supabase pg_cron job's HTTP headers (so the cron can
# include it). Anyone holding this secret can trigger a refresh —
# rotate if leaked.
REFRESH_CACHE_SECRET = os.getenv("REFRESH_CACHE_SECRET", "").strip()
ENABLE_JOB_SEARCH_BACKEND = _load_bool_env("ENABLE_JOB_SEARCH_BACKEND", False)
JOB_BACKEND_HOSTPORT = os.getenv("JOB_BACKEND_HOSTPORT", "").strip()
JOB_BACKEND_BASE_URL = resolve_job_backend_base_url(
    os.getenv("JOB_BACKEND_BASE_URL", ""),
    JOB_BACKEND_HOSTPORT,
)
GREENHOUSE_BOARD_TOKENS = tuple(
    token.strip()
    for token in os.getenv("GREENHOUSE_BOARD_TOKENS", "").split(",")
    if token.strip()
)
ASHBY_BOARD_TOKENS = tuple(
    token.strip()
    for token in os.getenv("ASHBY_BOARD_TOKENS", "").split(",")
    if token.strip()
)
# Workday tokens are 3-tuples joined by ":"
# (e.g. "nvidia:wd5:NVIDIAExternalCareerSite") because each company
# runs its own tenant on a numbered host. See workday.py for the
# parser.
WORKDAY_BOARD_TOKENS = tuple(
    token.strip()
    for token in os.getenv("WORKDAY_BOARD_TOKENS", "").split(",")
    if token.strip()
)
LEVER_SITE_NAMES = tuple(
    token.strip()
    for token in os.getenv("LEVER_SITE_NAMES", "").split(",")
    if token.strip()
)
SAVED_WORKSPACE_TTL_HOURS = _load_int_env("SAVED_WORKSPACE_TTL_HOURS", 24)
# Resume-builder drafts live longer than saved workspaces — a draft is
# something the user actively iterates on across multiple sessions
# (e.g. picking it up the next weekend), whereas a saved workspace is
# a post-analysis snapshot. The Supabase column default + the cron
# `cleanup-expired-resume-builder-sessions` use this same value via
# the migration in docs/sql/supabase-resume-builder.sql; if you change
# the days here you also need to migrate the column default and update
# `expires_at` on the row when writing.
RESUME_BUILDER_SESSION_TTL_DAYS = _load_int_env(
    "RESUME_BUILDER_SESSION_TTL_DAYS", 7
)
AUTH_DEFAULT_PLAN_TIER = os.getenv("AUTH_DEFAULT_PLAN_TIER", "free").strip()
AUTH_DEFAULT_ACCOUNT_STATUS = os.getenv(
    "AUTH_DEFAULT_ACCOUNT_STATUS", "active"
).strip()
AUTH_INTERNAL_USER_EMAILS = tuple(
    email.strip().lower()
    for email in os.getenv("AUTH_INTERNAL_USER_EMAILS", "").split(",")
    if email.strip()
)
FREE_TIER_MAX_CALLS_PER_DAY = _load_int_env("FREE_TIER_MAX_CALLS_PER_DAY", 12)
FREE_TIER_MAX_TOKENS_PER_DAY = _load_int_env("FREE_TIER_MAX_TOKENS_PER_DAY", 60000)
PAID_TIER_MAX_CALLS_PER_DAY = _load_int_env("PAID_TIER_MAX_CALLS_PER_DAY", 80)
PAID_TIER_MAX_TOKENS_PER_DAY = _load_int_env("PAID_TIER_MAX_TOKENS_PER_DAY", 400000)


def get_daily_quota_for_plan(plan_tier: str):
    normalized_plan = (plan_tier or AUTH_DEFAULT_PLAN_TIER).strip().lower()
    if normalized_plan in {"admin", "internal"}:
        return {"max_calls": None, "max_total_tokens": None, "plan_tier": normalized_plan}
    if normalized_plan in {"paid", "pro", "plus"}:
        return {
            "max_calls": PAID_TIER_MAX_CALLS_PER_DAY,
            "max_total_tokens": PAID_TIER_MAX_TOKENS_PER_DAY,
            "plan_tier": normalized_plan,
        }
    return {
        "max_calls": FREE_TIER_MAX_CALLS_PER_DAY,
        "max_total_tokens": FREE_TIER_MAX_TOKENS_PER_DAY,
        "plan_tier": normalized_plan,
    }


def get_default_plan_tier_for_email(email: str, fallback: str = None):
    normalized_email = str(email or "").strip().lower()
    if normalized_email and normalized_email in AUTH_INTERNAL_USER_EMAILS:
        return "internal"
    return (fallback or AUTH_DEFAULT_PLAN_TIER).strip().lower()


def _load_text_file(path: Path):
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return None


def load_openai_key(required: bool = False):
    key = os.getenv("OPENAI_API_KEY") or _load_text_file(OPENAI_KEY_PATH)
    if key or not required:
        return key
    raise RuntimeError(
        "Missing OpenAI API key. Set OPENAI_API_KEY or add openai_key.txt."
    )


def get_openai_model_for_task(task_name: str = None, fallback: str = None):
    if task_name:
        return OPENAI_MODEL_ROUTING.get(task_name, fallback or OPENAI_MODEL_DEFAULT)
    return fallback or OPENAI_MODEL_DEFAULT


def get_openai_reasoning_effort_for_task(task_name: str = None, fallback: str = None):
    if task_name:
        return OPENAI_REASONING_ROUTING.get(task_name, fallback or OPENAI_REASONING_DEFAULT)
    return fallback or OPENAI_REASONING_DEFAULT


def get_openai_max_completion_tokens_for_task(task_name: str = None, fallback: int = 1200):
    if task_name:
        return OPENAI_MAX_COMPLETION_TOKENS_ROUTING.get(task_name, fallback)
    return fallback


def describe_openai_model_policy(default_model: str = None):
    policies = sorted(
        set(
            "{model}[{reasoning}]".format(
                model=model,
                reasoning=OPENAI_REASONING_ROUTING.get(task_name, OPENAI_REASONING_DEFAULT),
            )
            for task_name, model in OPENAI_MODEL_ROUTING.items()
        )
    )
    if not policies:
        return "{model}[{reasoning}]".format(
            model=default_model or OPENAI_MODEL_DEFAULT,
            reasoning=OPENAI_REASONING_DEFAULT,
        )
    if len(policies) == 1:
        return policies[0]
    return "routed({policies})".format(policies=", ".join(policies))


def is_supabase_auth_configured():
    return bool(SUPABASE_URL and SUPABASE_ANON_KEY)


def assisted_workflow_requires_login():
    return AUTH_REQUIRED_FOR_ASSISTED_WORKFLOW


def is_job_search_backend_enabled():
    return ENABLE_JOB_SEARCH_BACKEND


def is_job_search_hybrid_enabled():
    """True when the Tier 2 hybrid (lexical + semantic) search path is
    enabled. The store consults this; when False it stays on the Tier 1
    lexical RPC. See JOB_SEARCH_HYBRID_ENABLED above."""
    return JOB_SEARCH_HYBRID_ENABLED
