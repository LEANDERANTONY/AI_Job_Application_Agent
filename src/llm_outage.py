"""Single source of truth for honest "AI provider degraded" copy.

Every LLM-backed surface (the analysis pipeline, the résumé parser,
the JD parser, the JD-summary panel) degrades gracefully to a
deterministic fallback. The PHILOSOPHY: that's fine for a content
issue, but a genuine provider OUTAGE must never be shipped silently —
the user gets told, in cause-accurate language, so they can re-run
when it clears instead of trusting a quietly worse result.

The copy is surface-neutral on purpose: the banner's LOCATION already
tells the user which step degraded (résumé upload vs JD vs analysis);
the message only needs to explain the cause + remediation. Keeping it
in one place stops the wording drifting per surface.
"""
from __future__ import annotations

from typing import Any, Optional

from src.errors import OpenAIUnavailableError

OUTAGE_USER_MESSAGE = {
    "outage": (
        "Our AI provider (OpenAI) is having a moment, so we used a "
        "basic fallback here. Try again in a few minutes for the full "
        "AI-quality result."
    ),
    "rate_limited": (
        "OpenAI is rate-limiting us right now, so we used a basic "
        "fallback. Try again in a minute for the full AI-quality result."
    ),
    "misconfigured": (
        "AI assistance is temporarily unavailable, so we used a basic "
        "fallback. Please try again shortly."
    ),
}


def message_for_category(category: Optional[str]) -> str:
    """Cause-accurate banner copy for an outage category. Unknown /
    missing → the generic outage message."""
    return OUTAGE_USER_MESSAGE.get(
        category or "outage", OUTAGE_USER_MESSAGE["outage"]
    )


def outage_notice(exc: BaseException) -> Optional[dict[str, Any]]:
    """If ``exc`` is a genuine provider outage, return a small
    serialisable notice the route can put on its response; otherwise
    ``None`` (a content / other failure still degrades silently — the
    deterministic result is good enough and there's nothing for the
    user to wait out)."""
    if not isinstance(exc, OpenAIUnavailableError):
        return None
    category = getattr(exc, "category", "outage") or "outage"
    return {
        "unavailable": True,
        "category": category,
        "message": message_for_category(category),
    }
