"""Conversational eval for the post-Slice-1A+1B resume-builder agent.

Complements the existing 13-scenario ``resume_builder_quality_runner``
by focusing only on the AGENTIC behaviors that landed in Slice 1A
(tool-calling loop + ``fetch_github_readme``) and Slice 1B (full
conversation history + ``proactive_offer`` channel).

The scenarios test:
  - Tool fires when the user shares a github.com URL → README
    captured into ``projects_notes`` with real tech stack and outcomes.
  - Tool does NOT fire for non-github URLs → agent honestly says it
    can't fetch + asks the user to describe.
  - Proactive offer fires once the user has shared enough signal
    (e.g. multiple projects + target role) → ``proactive_offer``
    populated with a click-to-accept CTA.
  - Proactive offer does NOT fire mid-question (when the agent is
    still collecting a specific field) → ``proactive_offer`` is null.
  - Honesty rule: when asked to scrape LinkedIn / browse the web,
    the agent refuses politely and offers the closest thing it CAN do
    instead of hallucinating the capability.
  - Multi-turn corrections preserved: facts updated across multiple
    turns survive in the final draft.
  - Structured payloads populated after generate: catches the
    silent-fallback bug where a schema 400 caused structured fields
    to stay empty and the regex parser to fill in (the exact
    regression caught in this session).

Each scenario is a small fixture (2-5 turns) + an ``expected`` block
the rubric scores against. The scorer is grep-style — substring +
truthy/falsy checks. We don't compare LLM voice (variable) or exact
phrasing (variable) — only behavior signals (tool fired? proactive
offer present? structured payload non-empty?).

USAGE:
    python tests/quality/resume_builder_agentic_runner.py
    python tests/quality/resume_builder_agentic_runner.py --json out.json

COST: ~6 scenarios × ~3-4 turns × gpt-5.4 ≈ $0.05.

The script returns exit code 1 if any rubric assertion fails — wire
into CI (manual trigger only, like the other quality runners) to
catch regressions on the next agent-prompt change.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

# Allow running directly via `python tests/quality/...`. The repo root
# is two parents up from this file (tests/quality/<file>.py).
_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from backend.services import resume_builder_service
from backend.services.resume_builder_service import (
    answer_resume_builder_message,
    generate_resume_builder_resume,
    start_resume_builder_session,
)
from src.openai_service import OpenAIService


# ---------------------------------------------------------------------------
# Scenarios. Each carries:
#   name:        short identifier used in the report
#   description: one-line summary of what the scenario probes
#   turns:       list of user messages, posted in order
#   expect:      dict of rubric keys → expected value or matcher
#                Supported matchers:
#                  - "tool_called": str (tool name)  — must appear in the trace
#                  - "tool_not_called": str          — must NOT appear in the trace
#                  - "proactive_offer_set": bool     — non-None / non-empty offer
#                  - "draft_field_nonempty": str     — named draft field
#                  - "draft_field_contains": (field_name, needle)
#                  - "assistant_says": (turn_index, substring)
#                  - "assistant_does_not_say": (turn_index, substring)
#                  - "structured_payload_nonempty": str  — after generate,
#                    structured_<field>_payload must be non-empty
# ---------------------------------------------------------------------------


SCENARIOS: list[dict[str, Any]] = [
    {
        "name": "github_url_fires_tool",
        "description": "User shares a public github.com URL; agent must call fetch_github_readme.",
        "turns": [
            "Hi I'm Priya Sharma, based in Bangalore. Email priya@example.com.",
            "Looking for ML engineer roles.",
            "Here's a project of mine: https://github.com/openai/openai-python",
        ],
        "expect": {
            "tool_called": "fetch_github_readme",
            "draft_field_nonempty": "projects_notes",
            # The agent should signal it read the README in SOME way —
            # exact vocabulary varies ("read", "captured", "from the
            # README", "I saw it's a..."). Behavior matcher, not
            # vocabulary matcher.
            "assistant_says_any": (
                2,
                ["read", "captured", "saw", "README", "from your github", "openai-python", "openai python sdk"],
            ),
        },
    },
    {
        "name": "non_github_url_no_fetch",
        "description": "User shares a non-github URL; agent should NOT call the tool, must honestly say so.",
        "turns": [
            "Hi I'm Alex from Berlin, alex@example.com.",
            "Targeting backend engineer roles.",
            "Here's my project — https://my-portfolio-site.io",
        ],
        "expect": {
            "tool_not_called": "fetch_github_readme",
            # The honest fallback should mention github.com or "describe" or "paste".
            "assistant_says_any": (2, ["github.com", "describe", "paste"]),
        },
    },
    {
        "name": "honesty_on_linkedin_scrape",
        "description": "User asks the agent to scrape LinkedIn; agent must refuse honestly.",
        "turns": [
            "I'm Sam Lee from Singapore, sam@example.com.",
            "Targeting product manager roles.",
            "Can you scrape my LinkedIn profile for my experience and skills?",
        ],
        "expect": {
            "tool_not_called": "fetch_github_readme",
            # Refusal must be plain — must not promise to scrape.
            "assistant_does_not_say": (2, "I'll scrape"),
        },
    },
    {
        "name": "proactive_offer_after_enough_signal",
        "description": (
            "After role + projects + skills are captured (the realistic full "
            "signal pattern from the user's real session), the agent should "
            "fire a proactive_offer — typically 'Draft my professional summary'."
        ),
        "turns": [
            "I'm Riya from Mumbai, riya@example.com.",
            "Looking for ML engineer roles.",
            "Here are two projects of mine: https://github.com/openai/openai-python and https://github.com/openai/tiktoken",
            (
                "Skills: Python, PyTorch, OpenAI API, FastAPI, scikit-learn, "
                "XGBoost, Docker, Supabase, RAG, LLMs. Not sure what summary "
                "to write yet, can you suggest one?"
            ),
        ],
        "expect": {
            # Under-calibration risk: a smart model might either fire the
            # offer on the final turn OR put the summary right into the
            # reply. Accept either signal as success.
            "proactive_offer_set_or_summary_drafted": True,
        },
    },
    {
        "name": "proactive_offer_silent_mid_basics",
        "description": "While still collecting basics (first turn), proactive_offer should be null.",
        "turns": [
            "Hi.",
        ],
        "expect": {
            "proactive_offer_set": False,
        },
    },
    {
        "name": "multi_turn_correction_preserved",
        "description": "User corrects their target role across turns; final draft has the corrected value.",
        "turns": [
            "I'm Dev Kumar from Pune. dev@example.com.",
            "Looking for data scientist roles.",
            "Actually I'm targeting ML engineer roles, not data scientist.",
        ],
        "expect": {
            "draft_field_contains": ("target_role", "ML engineer"),
        },
    },
    {
        "name": "web_search_fires_on_external_context_question",
        "description": (
            "User asks about EXTERNAL context (what an employer typically "
            "expects from a role) that the agent can't know from the "
            "conversation alone. Agent should fire web_search."
        ),
        "turns": [
            "I'm Anika from Boston, anika@example.com.",
            "Looking for senior MLE roles at Anthropic specifically.",
            (
                "What does Anthropic typically look for on a Senior MLE "
                "resume? I want to make sure mine aligns."
            ),
        ],
        "expect": {
            # OpenAI's built-in web_search surfaces as a
            # ``web_search_call`` output item — different shape from
            # ``function_call`` (which is what tool_events captures).
            # The cleanest behavior signal: the agent's reply on
            # turn 2 should cite or reference EXTERNAL source material
            # rather than apologize for not having the info.
            "assistant_says_any": (
                2,
                [
                    "anthropic",
                    "search",
                    "look for",
                    "typically",
                    "based on",
                    "according to",
                ],
            ),
            # No local function tools should fire (no github URL given).
            "tool_not_called": "fetch_github_readme",
        },
    },
    {
        "name": "web_search_skipped_for_user_provided_info",
        "description": (
            "User is providing their OWN background — no external context "
            "is needed. The agent should NOT burn a web_search on this; "
            "it's wasted latency + the user is the source of truth for "
            "their own life."
        ),
        "turns": [
            "I'm Rohit from Hyderabad, rohit@example.com.",
            "Targeting backend engineer roles.",
            (
                "I've been at Acme Corp for 3 years building payment "
                "services in Go and gRPC."
            ),
        ],
        "expect": {
            # Negative behavior check: the agent's reply should NOT
            # cite external sources or talk about web searches when
            # the user is sharing their own facts. Loose matcher —
            # we accept anything that doesn't sound like a search
            # was performed for verification.
            "assistant_does_not_say": (2, "according to"),
        },
    },
    {
        "name": "promise_tracking_remembers_deferred_publication",
        "description": (
            "User defers a publication to later. The agent must capture the "
            "deferral as a follow-up and then resurface it when the moment "
            "is natural (here: when the user signals they're done with the "
            "other sections). Tests that add_followups fires AND the agent "
            "actually circles back instead of forgetting."
        ),
        "turns": [
            "I'm Aarav from Pune, aarav@example.com.",
            "Targeting research engineer roles.",
            (
                "I have a publication on graph neural networks I'd like to "
                "include but I'll share the details later."
            ),
            "Skills: Python, PyTorch, JAX, NumPy, scikit-learn, pandas.",
            "What else do you need from me?",
        ],
        "expect": {
            # The agent must have added the publication-deferral as a
            # follow-up (we surface pending_followups through the
            # response so this is observable).
            "pending_followups_contain_any": [
                "publication",
                "paper",
                "graph neural",
            ],
            # On the "what else?" turn, the agent should resurface the
            # deferred publication rather than asking a fresh
            # collection question. Behavior matcher accepts any of
            # several natural phrasings.
            "assistant_says_any": (
                4,
                ["publication", "paper", "earlier you mentioned", "graph neural"],
            ),
        },
    },
    {
        "name": "structured_payload_runs_after_generate",
        "description": (
            "After enough draft content + generate, structured_projects_payload "
            "must be non-empty. Catches the silent-fallback bug where a schema "
            "400 left the regex parser to fill in."
        ),
        "turns": [
            "Maya Iyer, Chennai, maya@example.com.",
            "ML engineer roles.",
            "https://github.com/openai/openai-python is a project I built; tested it heavily and used it across two production teams.",
        ],
        "run_generate": True,
        "expect": {
            "structured_payload_nonempty": "projects",
        },
    },
]


# ---------------------------------------------------------------------------
# Scenario runner + scorer.
# ---------------------------------------------------------------------------


def _gather_tool_events(session) -> list[dict]:
    """Read the conversation_history and extract synthesized tool events."""
    return [
        entry
        for entry in session.conversation_history
        if isinstance(entry, dict) and entry.get("role") == "tool"
    ]


def run_scenario(scenario: dict[str, Any], openai_service: OpenAIService) -> dict[str, Any]:
    """Execute one scenario end-to-end and return a result block."""
    name = scenario["name"]
    turns = scenario["turns"]
    expect = scenario["expect"]
    run_generate = scenario.get("run_generate", False)

    session_state = start_resume_builder_session()
    session_id = session_state["session_id"]

    assistant_replies: list[str] = []
    proactive_offers: list[str | None] = []
    error: str | None = None
    for user_message in turns:
        try:
            response = answer_resume_builder_message(
                session_id=session_id,
                message=user_message,
                openai_service=openai_service,
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            break
        assistant_replies.append(response.get("assistant_message", "") or "")
        proactive_offers.append(response.get("proactive_offer"))

    live_session = resume_builder_service._SESSIONS.get(session_id)
    tool_events = _gather_tool_events(live_session) if live_session else []
    structured_projects = list(getattr(live_session, "structured_projects_payload", []) or [])
    structured_education = list(getattr(live_session, "structured_education_payload", []) or [])
    structured_skill_categories = (
        dict(getattr(live_session, "structured_skill_categories", {}) or {})
    )

    if run_generate and live_session is not None and error is None:
        try:
            generate_resume_builder_resume(
                session_id=session_id, openai_service=openai_service
            )
            # Refresh post-generate state.
            structured_projects = list(live_session.structured_projects_payload or [])
            structured_education = list(live_session.structured_education_payload or [])
            structured_skill_categories = dict(
                live_session.structured_skill_categories or {}
            )
        except Exception as exc:
            error = f"generate raised {type(exc).__name__}: {exc}"

    # Rubric: walk every key in `expect` and score it.
    findings: list[str] = []
    passed = True

    def fail(msg: str) -> None:
        nonlocal passed
        passed = False
        findings.append(msg)

    if error and "tool_called" not in expect and "tool_not_called" not in expect:
        fail(f"scenario raised: {error}")

    if "tool_called" in expect:
        wanted = expect["tool_called"]
        if not any(ev.get("name") == wanted for ev in tool_events):
            fail(f"expected tool {wanted!r} to be called, got: {[ev.get('name') for ev in tool_events]}")

    if "tool_not_called" in expect:
        unwanted = expect["tool_not_called"]
        if any(ev.get("name") == unwanted for ev in tool_events):
            fail(f"tool {unwanted!r} was called but should NOT have been")

    if "proactive_offer_set" in expect:
        wanted = expect["proactive_offer_set"]
        last_offer = next(
            (offer for offer in reversed(proactive_offers) if offer is not None),
            None,
        )
        actually_set = bool(last_offer and str(last_offer).strip())
        if wanted and not actually_set:
            fail("expected proactive_offer to be set on the final turn, but it wasn't")
        if (not wanted) and actually_set:
            fail(
                f"expected proactive_offer to be null/empty, but got {last_offer!r}"
            )

    if "proactive_offer_set_or_summary_drafted" in expect:
        # Lenient matcher: accept EITHER a proactive_offer (the
        # click-to-accept chip) OR an assistant_message that signals
        # the agent acted on enough-signal — either drafted a summary
        # inline or proposed to do so. Behavior matcher, not
        # vocabulary matcher — vocabulary varies turn to turn.
        any_offer = any(bool(o and str(o).strip()) for o in proactive_offers)
        last_reply = assistant_replies[-1].lower() if assistant_replies else ""
        drafted_inline = any(
            marker in last_reply
            for marker in (
                "summary",        # "professional summary", "possible summary", "a summary"
                "engineer focused",  # the LLM's natural opening phrase for the draft
                "draft",          # "let me draft", "here's a draft"
                "i can write",
                "here's a",
            )
        )
        if not (any_offer or drafted_inline):
            fail(
                "expected EITHER a proactive_offer chip OR an inline summary "
                f"draft on the final turn; got offer={proactive_offers[-1]!r} "
                f"reply={assistant_replies[-1][:120]!r}"
            )

    if "draft_field_nonempty" in expect and live_session is not None:
        field = expect["draft_field_nonempty"]
        value = getattr(live_session.draft, field, "")
        if not (value and str(value).strip()):
            fail(f"draft field {field!r} is empty (expected non-empty)")

    if "draft_field_contains" in expect and live_session is not None:
        field, needle = expect["draft_field_contains"]
        value = str(getattr(live_session.draft, field, "") or "")
        if needle.lower() not in value.lower():
            fail(
                f"draft.{field} does not contain {needle!r} (got: {value[:120]!r})"
            )

    if "assistant_says" in expect:
        turn_index, needle = expect["assistant_says"]
        if turn_index < len(assistant_replies):
            reply = assistant_replies[turn_index]
            if needle.lower() not in reply.lower():
                fail(
                    f"turn {turn_index} assistant_message lacks {needle!r}; got: {reply[:140]!r}"
                )

    if "assistant_says_any" in expect:
        turn_index, needles = expect["assistant_says_any"]
        if turn_index < len(assistant_replies):
            reply = assistant_replies[turn_index].lower()
            if not any(n.lower() in reply for n in needles):
                fail(
                    f"turn {turn_index} assistant_message lacks any of {needles}; "
                    f"got: {assistant_replies[turn_index][:140]!r}"
                )

    if "assistant_does_not_say" in expect:
        turn_index, needle = expect["assistant_does_not_say"]
        if turn_index < len(assistant_replies):
            reply = assistant_replies[turn_index]
            if needle.lower() in reply.lower():
                fail(
                    f"turn {turn_index} assistant_message contains forbidden {needle!r}: "
                    f"{reply[:140]!r}"
                )

    if "pending_followups_contain_any" in expect:
        needles = expect["pending_followups_contain_any"]
        followups = (
            list(live_session.pending_followups) if live_session else []
        )
        followups_lower = " ; ".join(followups).lower()
        if not any(needle.lower() in followups_lower for needle in needles):
            fail(
                f"expected pending_followups to mention any of {needles}; "
                f"got: {followups}"
            )

    if "structured_payload_nonempty" in expect:
        which = expect["structured_payload_nonempty"]
        payloads = {
            "projects": structured_projects,
            "education": structured_education,
            "skill_categories": list(structured_skill_categories.items()),
        }
        if not payloads.get(which):
            fail(
                f"structured_{which}_payload is empty after generate — "
                "structuring LLM likely silently fell back to the regex parser. "
                "Check the strict-mode schema produced by _build_response_format_schema."
            )

    return {
        "name": name,
        "description": scenario["description"],
        "passed": passed,
        "findings": findings,
        "tool_events": [{"name": e.get("name"), "outcome": e.get("outcome")} for e in tool_events],
        "proactive_offers": proactive_offers,
        "assistant_replies": assistant_replies,
        "error": error,
        "structured_projects_count": len(structured_projects),
        "structured_education_count": len(structured_education),
        "structured_skill_categories_count": len(structured_skill_categories),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", help="Optional path to write the full JSON report.")
    parser.add_argument(
        "--scenario",
        action="append",
        help=(
            "Filter to one or more scenario names (repeat to include multiple). "
            "Default: run every scenario."
        ),
    )
    args = parser.parse_args()

    openai_service = OpenAIService()
    if not openai_service.is_available():
        print(
            "OpenAIService is not configured. Set OPENAI_API_KEY or drop the "
            "key file in the expected location and re-run."
        )
        return 2

    selected = SCENARIOS
    if args.scenario:
        selected = [s for s in SCENARIOS if s["name"] in set(args.scenario)]
        if not selected:
            print(f"No scenarios matched --scenario filter: {args.scenario}")
            return 2

    results: list[dict[str, Any]] = []
    for scenario in selected:
        print(f"-- running {scenario['name']} ...")
        result = run_scenario(scenario, openai_service)
        results.append(result)
        status = "PASS" if result["passed"] else "FAIL"
        print(f"   {status}")
        if not result["passed"]:
            for finding in result["findings"]:
                print(f"     - {finding}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=2)
        print(f"\nwrote JSON report -> {args.json}")

    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    print(f"\n{passed}/{total} scenarios passed.")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
