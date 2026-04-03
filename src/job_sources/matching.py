import re


_QUERY_TOKEN_RE = re.compile(r"[a-z0-9]+")
_LOCATION_TOKEN_ALIASES = {
    "bangalore": {"bangaluru", "bengaluru"},
    "bangaluru": {"bangalore", "bengaluru"},
    "bengaluru": {"bangalore", "bangaluru"},
    "mumbai": {"bombay"},
    "bombay": {"mumbai"},
    "delhi": {"new delhi"},
    "nyc": {"new york", "new york city"},
    "sf": {"san francisco", "bay area"},
    "wfh": {"remote", "work from home"},
    "remote": {"wfh", "work from home", "distributed"},
    "hybrid": {"flexible hybrid"},
    "onsite": {"on site", "on-site", "in office", "office based", "office-based"},
}

_ROLE_FAMILY_ALIASES = {
    "backend": {"backend", "back-end", "back end", "api", "platform", "distributed"},
    "frontend": {
        "frontend",
        "front-end",
        "front end",
        "ui engineer",
        "ui developer",
        "web engineer",
        "web developer",
        "design system",
        "design systems",
    },
    "fullstack": {"fullstack", "full-stack", "full stack"},
    "data_engineering": {"data engineer", "data engineering", "etl", "pipeline", "pipelines", "analytics engineer"},
    "data_science": {
        "data scientist",
        "data science",
        "applied scientist",
        "research scientist",
        "decision scientist",
        "statistician",
    },
    "machine_learning": {"machine learning", "ml engineer", "machine learning engineer", "mlops", "llm", "rag"},
    "ai_engineering": {"ai engineer", "artificial intelligence engineer", "genai engineer", "ai platform", "applied ai", "forward deployed ai", "llm engineer"},
    "devops": {"devops", "sre", "site reliability", "infrastructure", "platform"},
    "qa": {"qa", "quality assurance", "test automation"},
}


def extract_query_terms(value: str) -> list[str]:
    return _QUERY_TOKEN_RE.findall(str(value or "").lower())


def detect_role_families(query_text: str) -> set[str]:
    normalized = str(query_text or "").strip().lower()
    detected = set()
    for family, aliases in _ROLE_FAMILY_ALIASES.items():
        if any(alias in normalized for alias in aliases):
            detected.add(family)
    return detected


def title_matches_role_families(title_text: str, families: set[str]) -> bool:
    if not families:
        return True
    normalized_title = str(title_text or "").strip().lower()
    for family in families:
        aliases = _ROLE_FAMILY_ALIASES.get(family, set())
        if family == "ai_engineering":
            engineering_terms = ("engineer", "engineering", "developer", "architect")
            if any(alias in normalized_title for alias in aliases) and any(term in normalized_title for term in engineering_terms):
                return True
            continue
        if any(alias in normalized_title for alias in aliases):
            return True
    return False


def location_matches_text(haystack_text: str, location_query: str) -> bool:
    normalized_query = str(location_query or "").strip().lower()
    if not normalized_query:
        return True

    haystack = str(haystack_text or "").strip().lower()
    if normalized_query in haystack:
        return True

    query_terms = extract_query_terms(normalized_query)
    if not query_terms:
        return True

    for term in query_terms:
        aliases = {term, *(_LOCATION_TOKEN_ALIASES.get(term, set()))}
        if not any(alias in haystack for alias in aliases):
            return False
    return True
