from typing import Iterable, List


def coerce_string(value, default=""):
    if value is None:
        return default
    return str(value).strip() or default


def coerce_string_list(value, limit=None):
    if not isinstance(value, list):
        return []
    cleaned = []
    seen = set()
    for item in value:
        normalized = str(item or "").strip()
        if normalized and normalized.lower() not in seen:
            cleaned.append(normalized)
            seen.add(normalized.lower())
    return cleaned[:limit] if limit is not None else cleaned


def unique_strings(values: Iterable[str], limit=None) -> List[str]:
    cleaned = []
    seen = set()
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized.lower() not in seen:
            cleaned.append(normalized)
            seen.add(normalized.lower())
    return cleaned[:limit] if limit is not None else cleaned


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
