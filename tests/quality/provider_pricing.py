"""Per-million-token pricing for every model in the eval candidate slate.

Used by the multi-provider agentic eval to compute USD cost per
scenario from each call's ``response.usage.{prompt_tokens,
completion_tokens}``. Rates are *current pricing snapshot 2026-05-21*;
they will drift — update from the provider's pricing page or the
OpenRouter catalogue when re-running the eval.

Convention: all rates are **USD per million tokens**. The eval
divides by 1e6 at compute time so the small numbers stay readable
in the report.

Why this file (not a sibling constant in the adapter): pricing is
slug-specific (e.g. ``anthropic/claude-sonnet-4.5`` vs ``-haiku``
have different rates) and changes more often than the adapter
itself; isolating it makes it cheap to refresh.

Unknown slug -> ``(0.0, 0.0)`` rather than raising — the eval still
runs, the cost column just shows $0.00 for that arm.  The runner
emits a warning when this happens so silent under-reporting is
visible.
"""
from __future__ import annotations


# (input_per_million_usd, output_per_million_usd)
_RATES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    # OpenAI native (gpt-5.4 baseline — billed through the project's
    # OpenAI key, not OpenRouter).
    "gpt-5.4": (2.50, 10.00),
    "gpt-5.4-mini": (0.50, 2.00),
    # gpt-5.4 routed via OpenRouter — same model, prefix is what the
    # ``--candidates openai-via-or`` arm in the agentic runner uses.
    # OpenRouter's markup on top of OpenAI's wholesale rate is ~5%
    # for direct-from-provider models; close enough to use the same
    # numbers for an eval-budget estimate.
    "openai/gpt-5.4": (2.50, 10.00),
    "openai/gpt-5.4-mini": (0.50, 2.00),

    # OpenRouter catalogue — the 4-candidate shortlist plus the
    # adjacent models we might compare to (Opus for judge runs, etc).
    "anthropic/claude-sonnet-4.5": (3.00, 15.00),
    "anthropic/claude-opus-4.7": (15.00, 75.00),
    "google/gemini-3.1-pro-preview": (2.00, 12.00),
    "deepseek/deepseek-v4-pro": (0.50, 2.00),

    # Slugs from the broader provider_ab_runner candidate slate.
    # Kept current so an apples-to-apples comparison stays possible
    # without per-eval edits.
    "moonshotai/kimi-k2.6": (0.95, 0.95),
    "z-ai/glm-5.1": (0.50, 2.00),
    "x-ai/grok-4.20": (3.00, 15.00),
    "qwen/qwen3.6-max-preview": (0.80, 3.20),
}


def lookup_rate(model_slug: str) -> tuple[float, float]:
    """Return (input_usd_per_mtok, output_usd_per_mtok) for ``model_slug``.

    Falls back to (0.0, 0.0) for unknown slugs so the eval still
    completes (cost just reads $0 for that arm). Callers should
    cross-check the report for any $0 rows — that's the signal a
    slug needs adding here.
    """
    # Direct hit.
    if model_slug in _RATES_USD_PER_MTOK:
        return _RATES_USD_PER_MTOK[model_slug]
    # Tolerate the routing-label variants the runner uses
    # ("openai:gpt-5.4 (default routing)" -> trim the label).
    if ":" in model_slug:
        try_slug = model_slug.split(":", 1)[1].strip()
        # Drop a trailing parenthetical label like " (default routing)".
        if "(" in try_slug:
            try_slug = try_slug.split("(", 1)[0].strip()
        if try_slug in _RATES_USD_PER_MTOK:
            return _RATES_USD_PER_MTOK[try_slug]
    return (0.0, 0.0)


def estimate_cost_usd(
    model_slug: str, prompt_tokens: int, completion_tokens: int
) -> float:
    """Return USD cost for a single call.

    ``(prompt_tokens * input_rate + completion_tokens * output_rate) / 1e6``
    """
    input_rate, output_rate = lookup_rate(model_slug)
    return (
        (prompt_tokens or 0) * input_rate
        + (completion_tokens or 0) * output_rate
    ) / 1_000_000


__all__ = ["lookup_rate", "estimate_cost_usd"]
