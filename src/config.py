import os
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
DEMO_RESUME_DIR = STATIC_DIR / "demo_resume"
DEMO_JOB_DESCRIPTION_DIR = STATIC_DIR / "demo_job_description"
OPENAI_KEY_PATH = BASE_DIR / "openai_key.txt"
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")


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


def list_demo_files(directory: Path, suffixes):
    if not directory.exists():
        return []
    normalized_suffixes = tuple(s.lower() for s in suffixes)
    return sorted(
        file.name
        for file in directory.iterdir()
        if file.is_file() and file.suffix.lower() in normalized_suffixes
    )

