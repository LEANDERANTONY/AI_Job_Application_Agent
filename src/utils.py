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


def slugify_text(value: str, fallback: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return normalized or fallback


def safe_join_strings(
    values: Iterable[str],
    fallback: str = "N/A",
    limit: Optional[int] = None,
) -> str:
    cleaned = dedupe_strings(values, limit=limit)
    return ", ".join(cleaned) if cleaned else fallback


def render_markdown_list(items: Iterable[str], empty_state: str) -> str:
    cleaned = [str(item or "").strip() for item in items if str(item or "").strip()]
    if not cleaned:
        return "- {empty}".format(empty=empty_state)
    return "\n".join("- {item}".format(item=item) for item in cleaned)


def markdown_to_text(
    markdown: str,
    *,
    bullet_marker: str = "-",
    strip_bold: bool = False,
) -> str:
    text = re.sub(r"^#{1,6}\s*", "", markdown, flags=re.MULTILINE)
    if strip_bold:
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    if bullet_marker != "-":
        text = re.sub(r"^- ", bullet_marker + " ", text, flags=re.MULTILINE)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
