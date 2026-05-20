"""Compare two multi-provider eval JSON reports + classify failure modes.

Reads the JSON reports produced by
``tests/quality/resume_builder_agentic_runner.py --json <path>`` for two
runs (e.g. v1 = before the markdown-fence fix, v2 = after) and prints:

  1. Per-candidate score deltas (v1 score -> v2 score, change).
  2. Per-scenario × per-candidate matrix of PASS/FAIL across both runs
     so it's obvious where a fix landed and where a real model-behavior
     gap remains.
  3. For each remaining v2 failure, classify whether the cause was:
       - ``regex_fallback`` — every assistant_reply matches a canonical
         step-machine message AND no tool_events fired. The
         OpenRouter adapter raised on every turn; the resume-builder
         service caught the exception and ran the deterministic
         intake. Indicates an ADAPTER / parse bug, not a model
         capability gap.
       - ``partial_fallback`` — some turns ran the model, some fell
         back. Mixed cause; usually a sporadic parse failure or a
         flaky provider.
       - ``model_behavior`` — model ran cleanly, behavior didn't
         match. This IS a real capability signal — what the eval
         is meant to measure.

Usage:
    python scripts/compare_multi_provider_eval.py v1.json v2.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# Canonical step-machine messages from _build_next_message() in
# backend/services/resume_builder_service.py. These appear ONLY when
# the LLM-first path raised and the deterministic step-machine ran
# the turn instead — so spotting them in every assistant_reply of a
# scenario tells us the adapter died on every turn.
STEP_MACHINE_MARKERS = (
    "I’ve captured your contact details",
    "I’ve got the role direction",
    "I’ve saved your experience notes",
    "I’ve added your education details",
    "I’ve captured the skills you want highlighted",
    "Everything is collected. Review the draft",
    "I've captured your contact details",  # straight apostrophe fallback
    "I've got the role direction",
    "I've saved your experience notes",
    "I've added your education details",
    "I've captured the skills you want highlighted",
)


def _is_step_machine_reply(text: str) -> bool:
    text = str(text or "")
    return any(marker in text for marker in STEP_MACHINE_MARKERS)


def classify_failure(result: dict) -> str:
    """Categorise a failed result by its root cause.

    Returns one of: ``regex_fallback`` / ``partial_fallback`` /
    ``model_behavior``.
    """
    replies = result.get("assistant_replies") or []
    tool_events = result.get("tool_events") or []
    if not replies:
        return "model_behavior"  # nothing to compare; treat as model
    fallback_replies = sum(1 for r in replies if _is_step_machine_reply(r))
    if fallback_replies == len(replies) and not tool_events:
        return "regex_fallback"
    if fallback_replies > 0:
        return "partial_fallback"
    return "model_behavior"


def _load_report(path: str) -> dict[str, list[dict]]:
    """Load a runner JSON report and return ``{candidate: [results]}``.

    Tolerates both the single-provider shape ``{provider, results}`` and
    the multi-candidate shape ``{candidates, results: {...}}`` so old
    reports stay readable.
    """
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, list):
        # Original shape: a bare list of results. No candidate key.
        return {"(unknown)": raw}
    if "results" in raw and isinstance(raw["results"], dict):
        return raw["results"]
    if "results" in raw and isinstance(raw["results"], list):
        return {raw.get("provider", "(unknown)"): raw["results"]}
    raise ValueError(f"Unrecognized report shape in {path!r}")


def _score(results: list[dict]) -> tuple[int, int]:
    return sum(1 for r in results if r.get("passed")), len(results)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("v1_json", help="Earlier eval report JSON.")
    parser.add_argument("v2_json", help="Later eval report JSON (after a fix).")
    args = parser.parse_args()

    v1 = _load_report(args.v1_json)
    v2 = _load_report(args.v2_json)

    candidates = []
    seen = set()
    for c in (*v1.keys(), *v2.keys()):
        if c not in seen:
            candidates.append(c)
            seen.add(c)

    print("=" * 80)
    print("SCORE DELTAS — v1 -> v2")
    print("=" * 80)
    print(f"{'candidate':<14} | {'v1':>6} | {'v2':>6} | change")
    print("-" * 60)
    for cand in candidates:
        v1_results = v1.get(cand, [])
        v2_results = v2.get(cand, [])
        v1_p, v1_t = _score(v1_results)
        v2_p, v2_t = _score(v2_results)
        delta = v2_p - v1_p
        delta_str = f"{delta:+d}" if delta else "  "
        print(
            f"{cand:<14} | {v1_p}/{v1_t:>2}  | {v2_p}/{v2_t:>2}  | {delta_str}"
        )

    print()
    print("=" * 80)
    print("V2 REMAINING FAILURES — classified")
    print("=" * 80)
    print(f"{'candidate':<14} | {'scenario':<48} | classification")
    print("-" * 100)
    for cand in candidates:
        for r in v2.get(cand, []):
            if r.get("passed"):
                continue
            cls = classify_failure(r)
            print(f"{cand:<14} | {r.get('name', '?'):<48} | {cls}")

    # Roll-up of remaining causes — useful tldr for the DEVLOG.
    print()
    print("=" * 80)
    print("V2 FAILURE-CAUSE ROLL-UP")
    print("=" * 80)
    counts: dict[str, int] = {}
    for cand in candidates:
        for r in v2.get(cand, []):
            if r.get("passed"):
                continue
            cls = classify_failure(r)
            counts[cls] = counts.get(cls, 0) + 1
    for cls in ("regex_fallback", "partial_fallback", "model_behavior"):
        n = counts.get(cls, 0)
        print(f"  {cls:<20} : {n}")
    print()
    print(
        "regex_fallback / partial_fallback = adapter or parse bug; not a "
        "model capability signal. model_behavior = the actual cross-"
        "provider comparison data."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
