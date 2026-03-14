import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
DEMO_RESUME_DIR = STATIC_DIR / "demo_resume"
DEMO_JOB_DESCRIPTION_DIR = STATIC_DIR / "demo_job_description"
OPENAI_KEY_PATH = BASE_DIR / "openai_key.txt"
OPENAI_MODEL_DEFAULT = os.getenv(
    "OPENAI_MODEL_DEFAULT",
    os.getenv("OPENAI_MODEL", "gpt-5-mini-2025-08-07"),
)
OPENAI_MODEL_HIGH_TRUST = os.getenv("OPENAI_MODEL_HIGH_TRUST", "gpt-5.4")
OPENAI_MODEL_MID_TIER = os.getenv("OPENAI_MODEL_MID_TIER", OPENAI_MODEL_DEFAULT)
OPENAI_MODEL_PRODUCT_HELP = os.getenv(
    "OPENAI_MODEL_PRODUCT_HELP", OPENAI_MODEL_MID_TIER
)
OPENAI_MODEL_APPLICATION_QA = os.getenv(
    "OPENAI_MODEL_APPLICATION_QA", OPENAI_MODEL_HIGH_TRUST
)
OPENAI_MODEL_ROUTING = {
    "profile": os.getenv("OPENAI_MODEL_PROFILE", OPENAI_MODEL_MID_TIER),
    "job": os.getenv("OPENAI_MODEL_JOB", OPENAI_MODEL_MID_TIER),
    "fit": os.getenv("OPENAI_MODEL_FIT", OPENAI_MODEL_MID_TIER),
    "tailoring": os.getenv("OPENAI_MODEL_TAILORING", OPENAI_MODEL_MID_TIER),
    "strategy": os.getenv("OPENAI_MODEL_STRATEGY", OPENAI_MODEL_MID_TIER),
    "review": os.getenv("OPENAI_MODEL_REVIEW", OPENAI_MODEL_HIGH_TRUST),
    "resume_generation": os.getenv(
        "OPENAI_MODEL_RESUME_GENERATION", OPENAI_MODEL_HIGH_TRUST
    ),
    "assistant_product_help": OPENAI_MODEL_PRODUCT_HELP,
    "assistant_application_qa": OPENAI_MODEL_APPLICATION_QA,
}
OPENAI_MODEL = OPENAI_MODEL_DEFAULT


def _load_int_env(name: str, default=None):
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    return int(raw_value)


OPENAI_MAX_CALLS_PER_SESSION = _load_int_env("OPENAI_MAX_CALLS_PER_SESSION", 24)
OPENAI_MAX_TOKENS_PER_SESSION = _load_int_env("OPENAI_MAX_TOKENS_PER_SESSION", 120000)


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


def describe_openai_model_policy(default_model: str = None):
    models = sorted(set(OPENAI_MODEL_ROUTING.values()))
    if not models:
        return default_model or OPENAI_MODEL_DEFAULT
    if len(models) == 1:
        return models[0]
    return "routed({models})".format(models=", ".join(models))


def list_demo_files(directory: Path, suffixes):
    if not directory.exists():
        return []
    normalized_suffixes = tuple(s.lower() for s in suffixes)
    return sorted(
        file.name
        for file in directory.iterdir()
        if file.is_file() and file.suffix.lower() in normalized_suffixes
    )

