import re
from typing import Iterable, List, Optional


def dedupe_strings(values: Iterable[str], limit: Optional[int] = None) -> List[str]:
    cleaned = []
    seen = set()
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized.lower() not in seen:
            cleaned.append(normalized)
            seen.add(normalized.lower())
    return cleaned[:limit] if limit is not None else cleaned


def match_keywords(text: str, keywords: Iterable[str]) -> List[str]:
    lowered_text = text.lower()
    matches = []
    for keyword in keywords:
        pattern = re.compile(r"\b" + re.escape(keyword.lower()) + r"\b")
        match = pattern.search(lowered_text)
        if match:
            matches.append((match.start(), keyword))
    matches.sort(key=lambda item: item[0])
    return [keyword for _, keyword in matches]
