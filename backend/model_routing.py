"""Tier-aware workflow model selection (Step 7a of tier-enforcement).

Today every workflow agent (tailoring, review, resume_generation,
cover_letter) reads its model from `OPENAI_MODEL_ROUTING` keyed by the
agent's `task_name`. When a user opts into premium (premium=True on
/workspace/analyze) AND their tier supports it (Pro or Business), the
three "high-trust" agents — review, resume_generation, cover_letter —
should route to the premium model (gpt-5.5) instead of gpt-5.4. The
tailoring agent stays on mini regardless: the COGS analysis showed that
only the three review-grade agents benefit from the upgrade, and
keeping tailoring on mini is the difference between premium being
sustainable and not.

This module exposes a single helper, `select_workflow_model`. It's
intentionally separate from `src/config.py::get_openai_model_for_task`
because:

  1. Tier resolution is a backend concern (`backend.tiers`), not an
     `src/` concern. Pulling `Tier` into `src/config.py` would invert
     the dependency direction we've established (backend uses src,
     never the other way around).
  2. The function returns `None` when no override is warranted, so the
     caller can keep using the default per-task lookup without a
     branch. None means "the standard model for this task is fine".
  3. The premium flag is the source of truth — never autodetect from
     the user's session or sniff from a cookie. The route hands it to
     the service, the service hands it here.

Free tier passing premium=True is already blocked at the gate in
`/workspace/analyze` (Step 3 of the series), so this code never sees a
Free user with premium=True on the happy path. Defensive code below
still falls back gracefully (no upgrade) if it ever does, so a future
gate regression can't silently leak premium credits.
"""
from __future__ import annotations

from typing import Optional

from src.config import OPENAI_MODEL_ROUTING

from backend.tiers import Tier


# Tasks that DO get the premium upgrade when (premium=True, tier in
# {pro, business}). Anything not in this set keeps its standard model
# even on a premium run.
#
# Tailoring is deliberately omitted — the COGS analysis pinned tailoring
# at gpt-5.4-mini regardless of plan. Skill summaries / resume builder
# / assistant turns are even further away from the workflow path; this
# helper only deals with the four orchestrator agents.
_PREMIUM_UPGRADE_TASKS: frozenset[str] = frozenset(
    {"review", "resume_generation", "cover_letter"}
)


# Tiers that have a non-zero premium_applications cap. Hardcoding is
# acceptable here — the per-tier flag also lives in
# `TIER_CAPS[tier]["premium_applications"]`, but we don't want to take
# a hard dependency on the cap matrix to answer a yes/no question.
# If a future tier (e.g. "enterprise") wants premium, add it here AND
# bump its premium_applications cap in TIER_CAPS.
_PREMIUM_ELIGIBLE_TIERS: frozenset[Tier] = frozenset({"pro", "business"})


def select_workflow_model(
    *,
    task: str,
    tier: Tier,
    premium: bool,
) -> Optional[str]:
    """Decide whether to override the default model for this task.

    Returns the override model name (e.g. ``"gpt-5.5"``) when premium
    routing applies, or ``None`` when the caller should use the
    standard `OPENAI_MODEL_ROUTING[task]` lookup. ``None`` is the
    sentinel for "no override" — callers branch on falsy / None and
    fall through to their existing model-resolution path.

    Logic:
      * `premium=False` → always None. Standard models everywhere.
      * `tier` not in {pro, business} → None. The gate at
        /workspace/analyze already rejected this combination with a
        429, so reaching here is defensive only.
      * `task` not in {review, resume_generation, cover_letter} →
        None. Tailoring + everything else stays on the standard tier.
      * Otherwise → return the configured premium model (default
        ``"gpt-5.5"`` via ``OPENAI_MODEL_PREMIUM``).
    """
    if not premium:
        return None
    if tier not in _PREMIUM_ELIGIBLE_TIERS:
        # Defensive: the gate should have caught this. Fall back to
        # standard routing so a regression in the gate can't quietly
        # bill the user for premium credits without delivering the
        # upgraded model. The gate's the source of truth for what
        # gets *charged*; this helper only decides what gets *served*.
        return None
    if task not in _PREMIUM_UPGRADE_TASKS:
        return None
    # `premium_high_trust` is a routing-table key, not a real task
    # name passed to an agent. The lookup returns the configured
    # premium model (default OPENAI_MODEL_PREMIUM = "gpt-5.5"). If the
    # key is somehow missing (test isolation, malformed env), fall
    # back to None rather than to a hardcoded model string — the
    # default-routing path is then the safe choice.
    return OPENAI_MODEL_ROUTING.get("premium_high_trust")


def build_workflow_model_overrides(
    *,
    tier: Tier,
    premium: bool,
) -> dict[str, Optional[str]]:
    """Pre-compute the model override for each workflow agent task.

    The orchestrator hands its agents the map at construction time so
    each agent's `run_json_prompt` call can pass `model=...` directly
    rather than re-deriving the tier on every prompt. Returns a dict
    keyed by task name; values are either an override model string or
    None (meaning "use the default for this task").
    """
    return {
        "tailoring": select_workflow_model(
            task="tailoring", tier=tier, premium=premium
        ),
        "review": select_workflow_model(
            task="review", tier=tier, premium=premium
        ),
        "resume_generation": select_workflow_model(
            task="resume_generation", tier=tier, premium=premium
        ),
        "cover_letter": select_workflow_model(
            task="cover_letter", tier=tier, premium=premium
        ),
    }


__all__ = [
    "build_workflow_model_overrides",
    "select_workflow_model",
]
