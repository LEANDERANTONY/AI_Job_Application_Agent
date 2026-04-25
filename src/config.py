import os
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
STATIC_DIR = BASE_DIR / "static"
DEMO_RESUME_DIR = STATIC_DIR / "demo_resume"
DEMO_JOB_DESCRIPTION_DIR = STATIC_DIR / "demo_job_description"
OPENAI_KEY_PATH = BASE_DIR / "openai_key.txt"
OPENAI_MODEL_DEFAULT = os.getenv(
    "OPENAI_MODEL_DEFAULT",
    os.getenv("OPENAI_MODEL", "gpt-5.4-mini"),
)
OPENAI_MODEL_HIGH_TRUST = os.getenv("OPENAI_MODEL_HIGH_TRUST", "gpt-5.4")
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
    "assistant": OPENAI_MODEL_ASSISTANT,
    "assistant_product_help": OPENAI_MODEL_PRODUCT_HELP,
    "assistant_application_qa": OPENAI_MODEL_APPLICATION_QA,
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
    "assistant_product_help": _load_int_env("OPENAI_MAX_COMPLETION_TOKENS_PRODUCT_HELP", 700),
    "assistant_application_qa": _load_int_env("OPENAI_MAX_COMPLETION_TOKENS_APPLICATION_QA", 1400),
}


DAILY_QUOTA_CACHE_TTL_SECONDS = _load_int_env("DAILY_QUOTA_CACHE_TTL_SECONDS", 15)
APP_BASE_URL = os.getenv("APP_BASE_URL", "").strip()
SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_ANON_KEY = os.getenv("SUPABASE_ANON_KEY", "").strip()
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
LEVER_SITE_NAMES = tuple(
    token.strip()
    for token in os.getenv("LEVER_SITE_NAMES", "").split(",")
    if token.strip()
)
SAVED_WORKSPACE_TTL_HOURS = _load_int_env("SAVED_WORKSPACE_TTL_HOURS", 24)
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


