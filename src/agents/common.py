from typing import Iterable

from src.utils import dedupe_strings


def coerce_string(value, default=""):
    if value is None:
        return default
    return str(value).strip() or default


def coerce_string_list(value, limit=None):
    if not isinstance(value, list):
        return []
    return unique_strings(value, limit=limit)


def unique_strings(values: Iterable[str], limit=None) -> list[str]:
    return dedupe_strings(values, limit=limit)


def coerce_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0"}:
            return False
    return False
