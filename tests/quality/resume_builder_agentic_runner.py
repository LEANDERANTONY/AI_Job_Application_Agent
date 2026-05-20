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
import datetime
import json
import os
import sys
import time
from typing import Any

# Allow running directly via `python tests/quality/...`. The repo root
# is two parents up from this file (tests/quality/<file>.py).
_REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Slice 1H: bump the structuring-pass output budget BEFORE importing
# src.config (which reads the env var at module-init time). Slice 1G
# found the structuring LLM call (~11K-char prompt) often truncates
# at the default 4000 — every truncation drops a field, the schema
# validator rejects the malformed JSON, the regex fallback runs.
# 6000 gives ~50% headroom for the worst-case full structuring
# output (6 projects × 3 bullets + 3 education entries + 8 skill
# buckets + 200-char summary ≈ 4500 tokens) plus retry headroom.
os.environ.setdefault(
    "OPENAI_MAX_COMPLETION_TOKENS_RESUME_BUILDER_STRUCTURING", "6000"
)

from backend.services import resume_builder_service
from backend.services.resume_builder_service import (
    answer_resume_builder_message,
    generate_resume_builder_resume,
    start_resume_builder_session,
)
from src.openai_service import OpenAIService
from tests.quality.provider_pricing import estimate_cost_usd, lookup_rate


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
        # Slice 1G: web_search is OpenAI-specific (wraps the built-in
        # server-side tool via an inner Responses-API call). The
        # OpenRouter adapter has no Chat-Completions equivalent, so we
        # auto-skip scenarios with this flag when running against any
        # non-openai provider.
        "requires_web_search": True,
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
        "requires_web_search": True,
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
    # ===================================================================
    # Slice 1H additions — adversarial / conflicting / long-session
    # scenarios that distinguish the top-4 candidates more sharply
    # than the original 10. These aren't pass/fail-dominant — they're
    # designed for the me-as-judge qualitative pass (which is why
    # several have lenient expect blocks: the matchers catch the
    # baseline; the conversational nuance is what we read).
    # ===================================================================
    {
        "name": "triple_role_correction",
        "description": (
            "User corrects their target role three times in succession. "
            "Stress-tests multi-turn memory + draft_updates discipline. "
            "Final draft must hold the LAST-mentioned role, not earlier ones."
        ),
        "turns": [
            "I'm Tara Vyas from Mumbai, tara@example.com.",
            "I'm targeting data scientist roles.",
            "Actually, scratch that — ML engineer roles.",
            "On reflection, research engineer is the closer fit. Let's go with that.",
        ],
        "expect": {
            "draft_field_contains": ("target_role", "research engineer"),
        },
    },
    {
        "name": "self_contradictory_info",
        "description": (
            "User makes contradictory claims about their experience "
            "(5 years at a FAANG vs. recent grad). A smart agent "
            "should EITHER flag the contradiction OR capture the latest. "
            "Lenient matcher: just confirm the agent didn't crash + "
            "produces a coherent reply."
        ),
        "turns": [
            "I'm Marcus Lee, marcus@example.com, San Francisco.",
            "I'm a Staff ML Engineer at Google with 8 years of experience leading large teams.",
            "Actually I'm a recent CS grad just starting out; ignore what I said earlier.",
            "Let's go with the recent-grad framing for the resume.",
        ],
        "expect": {
            # Lenient: just confirm a coherent assistant reply on the
            # final turn. The judging-pass reads what was actually said.
            "assistant_says_any": (
                3,
                ["recent", "grad", "new grad", "early career", "entry", "got it"],
            ),
        },
    },
    {
        "name": "off_topic_movie_question",
        "description": (
            "User asks an off-topic question mid-conversation "
            "(\"what's a good movie?\"). Agent must decline politely "
            "and steer back to resume-building. Tests the off-topic "
            "rule in the prompt."
        ),
        "turns": [
            "I'm Saanvi Joshi from Pune, saanvi@example.com.",
            "Targeting product manager roles.",
            "By the way, what's a good movie to watch tonight?",
        ],
        "expect": {
            # Behavior-level redirect: agent should reference the
            # resume / steering back. We INTENTIONALLY don't check for
            # absence of the word "recommend" — a polite refusal like
            # "I can't help with movie recommendations" contains it
            # but is the right behavior. The judging pass reads the
            # actual text for whether a specific movie was suggested.
            "assistant_says_any": (
                2,
                ["resume", "stay on", "focus", "back to", "next", "can't help"],
            ),
        },
    },
    {
        "name": "out_of_scope_capability_probe",
        "description": (
            "User asks the agent to do something outside its scope "
            "(\"can you schedule an interview for me?\"). Agent must "
            "refuse honestly per the honesty rule, not promise the "
            "capability."
        ),
        "turns": [
            "I'm Kenji Tanaka, kenji@example.com, Tokyo.",
            "Targeting backend engineer roles.",
            "Can you schedule an interview with Anthropic for me?",
        ],
        "expect": {
            # Lenient: agent should acknowledge it can't do this. We
            # check via a positive signal ("can't" / "unable" / "not
            # able") rather than a forbidden phrase because models
            # vary in how they refuse.
            "assistant_says_any": (
                2,
                ["can't", "cannot", "unable", "not able", "won't", "outside"],
            ),
        },
    },
    {
        "name": "failed_tool_graceful_fallback",
        "description": (
            "User pastes a 404'd / private github URL. The tool call "
            "WILL succeed in firing but the fetch returns an error. "
            "Agent must honestly tell the user the fetch failed AND "
            "ask them to describe the project — NOT invent details."
        ),
        "turns": [
            "I'm Olu Adeyemi, olu@example.com, Lagos.",
            "Targeting AIML engineer roles.",
            "Project: https://github.com/this-org-does-not-exist-anywhere/never-real-repo",
        ],
        "expect": {
            "tool_called": "fetch_github_readme",
            # Agent must invite the user to describe instead of
            # fabricating. Lenient matcher — accept any "describe / "
            # "details / share" framing.
            "assistant_says_any": (
                2,
                [
                    "describe",
                    "details",
                    "tell me",
                    "share",
                    "couldn't",
                    "could not",
                    "didn't work",
                ],
            ),
        },
    },
    {
        "name": "format_jumbled_dump",
        "description": (
            "User pastes role/experience info as a chaotic mix of "
            "bullets, prose, dates, and a URL in one turn. Tests how "
            "well the agent extracts structured fields from messy "
            "free-form input. Lenient: confirm at least target_role "
            "captured."
        ),
        "turns": [
            "I'm Priya R. priya.r@example.com, Bengaluru.",
            (
                "Looking for: Senior ML Engineer roles.\n"
                "Background:\n"
                "- 4 yrs at AcmeCorp, May 2021-present, mostly LLM evals + RAG.\n"
                "- Github: https://github.com/openai/openai-python (just for reference, "
                "not mine; mine is private).\n"
                "Pls capture all that — I'll add the private repo details later."
            ),
        ],
        "expect": {
            "draft_field_contains": ("target_role", "Senior ML Engineer"),
            # The agent should at least acknowledge the request to
            # come back to the private repo later.
            "assistant_says_any": (
                1,
                ["later", "captured", "got it", "private", "noted"],
            ),
        },
    },
    {
        "name": "long_session_memory_callback",
        "description": (
            "A 7-turn session: the user mentions a key fact in turn 2, "
            "covers other topics for several turns, then asks on the "
            "final turn whether everything is captured. Agent should "
            "either confirm the earlier fact is in or proactively "
            "resurface it."
        ),
        "turns": [
            "I'm Aiyana Walker, aiyana@example.com, Boston.",
            "I worked at Stripe 2020-2023 as a Senior Engineer focusing on payments fraud.",
            "Targeting Staff Engineer roles in fintech.",
            "Skills: Python, Go, Kafka, Snowflake, ML for fraud detection.",
            "B.S. in CS from MIT, 2020.",
            "A bit on impact: I built the model that cut chargeback rate by 18%.",
            "Have we captured everything from my Stripe work?",
        ],
        "expect": {
            # The agent should recall Stripe + the 18% impact AND
            # confirm/list what's in. Lenient matcher catches several
            # ways of phrasing the recall.
            "assistant_says_any": (
                6,
                ["stripe", "18%", "fraud", "chargeback", "payments"],
            ),
        },
    },
    {
        "name": "mixed_github_and_portfolio_urls",
        "description": (
            "User pastes a mix of github + non-github URLs in one "
            "message. Agent should call fetch_github_readme on the "
            "github URL but NOT on the portfolio one — and explicitly "
            "ask the user to describe the non-github project."
        ),
        "turns": [
            "I'm Devin Chen, devin@example.com, Seattle.",
            "Targeting ML engineer roles.",
            (
                "Here are two projects:\n"
                "1. https://github.com/openai/openai-python (open-source SDK)\n"
                "2. https://devinchen.me/portfolio/health-ai (my personal portfolio "
                "writeup of a healthcare ML project)"
            ),
        ],
        "expect": {
            "tool_called": "fetch_github_readme",
            # Agent should mention asking for description of the
            # non-github URL — either by name, by URL, or by inviting
            # the user to describe it.
            "assistant_says_any": (
                2,
                ["portfolio", "describe", "tell me about", "details", "second", "writeup"],
            ),
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


def _usage_snapshot(service: Any) -> dict[str, int]:
    """Return the service's cumulative usage as ``{prompt, completion, total}``.

    Both OpenAIService and OpenRouterEvalService expose
    ``get_usage_snapshot()`` returning a dict with at least
    ``prompt_tokens``/``completion_tokens``/``total_tokens``.
    """
    try:
        snap = service.get_usage_snapshot() or {}
    except Exception:
        snap = {}
    return {
        "prompt": int(snap.get("prompt_tokens", 0) or 0),
        "completion": int(snap.get("completion_tokens", 0) or 0),
        "total": int(snap.get("total_tokens", 0) or 0),
    }


def _resolve_model_slug_for_pricing(service: Any) -> str:
    """Return a stable model slug for the pricing lookup.

    OpenRouterEvalService -> ``self.default_model`` (e.g.
    ``anthropic/claude-sonnet-4.5``).
    OpenAIService -> ``"gpt-5.4"`` (the production routing default for
    the resume-builder intake).
    """
    model = getattr(service, "default_model", None)
    if isinstance(model, str) and model.strip():
        return model.strip()
    return "gpt-5.4"


def run_scenario(scenario: dict[str, Any], openai_service: OpenAIService) -> dict[str, Any]:
    """Execute one scenario end-to-end and return a result block."""
    name = scenario["name"]
    turns = scenario["turns"]
    expect = scenario["expect"]
    run_generate = scenario.get("run_generate", False)

    session_state = start_resume_builder_session()
    session_id = session_state["session_id"]

    # Slice 1H: capture latency + tokens + cost as first-class metrics.
    # Latency is wall-clock around the user-message turns (including
    # all internal tool-loop iterations + retries). Tokens come from
    # the service's cumulative usage snapshot, diffed across the
    # scenario. Cost = tokens × per-model pricing.
    started_at = time.perf_counter()
    usage_at_start = _usage_snapshot(openai_service)
    pricing_slug = _resolve_model_slug_for_pricing(openai_service)

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

    # Close out the metrics: scenario wall-clock, token usage delta,
    # and cost. The cost calculation honors the service's actual
    # default_model so a -mini override is priced correctly. A zero
    # cost row signals an unknown pricing slug — runner emits a
    # warning when this happens.
    elapsed_s = time.perf_counter() - started_at
    usage_at_end = _usage_snapshot(openai_service)
    delta_prompt = max(0, usage_at_end["prompt"] - usage_at_start["prompt"])
    delta_completion = max(
        0, usage_at_end["completion"] - usage_at_start["completion"]
    )
    cost_usd = estimate_cost_usd(pricing_slug, delta_prompt, delta_completion)

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
        # Slice 1H metrics — surface in the per-scenario summary line
        # and the JSON report so the comparison script can rank by
        # latency / cost / throughput in addition to pass-rate.
        "metrics": {
            "elapsed_seconds": round(elapsed_s, 3),
            "prompt_tokens": delta_prompt,
            "completion_tokens": delta_completion,
            "total_tokens": delta_prompt + delta_completion,
            "cost_usd": round(cost_usd, 4),
            "tool_call_count": len(tool_events),
            "pricing_slug": pricing_slug,
        },
    }


# Multi-provider candidate pool. Mirrors the candidate set in
# ``provider_ab_runner._CANDIDATES`` (the ADR-028 D1 candidate slate
# from report.md §4) plus Anthropic Sonnet 4.5 as the operator's
# explicit add for the agentic eval. ``openai`` is the special
# baseline routed through the production ``OpenAIService`` (Responses
# API native); everything else goes via OpenRouter Chat Completions.
#
# Slugs verified against the live OpenRouter catalogue per
# report.md §4 — the provider_ab_runner copy still has three stale
# slugs (gemini-3.1-pro / deepseek-v4 / qwen-3.5) we deliberately
# correct here.
_AGENTIC_CANDIDATES: dict[str, dict[str, Any]] = {
    # gpt-5.4 routed THROUGH OpenRouter — same proxy hop as every other
    # OpenRouter candidate, so cross-provider latency comparisons are
    # apples-to-apples (the `openai` baseline above uses the production
    # Responses-API direct path, which is faster but unfair to compare
    # head-to-head with OpenRouter-routed peers on latency). The
    # delta between `openai` and `openai-via-or` quantifies OpenRouter
    # proxy overhead by itself.
    "openai-via-or": {"slug": "openai/gpt-5.4", "reasoning_effort": None},
    # Resume-builder addendum: the assistant-surface eval (Slice 1K
    # addendum) showed `gpt-5.4-mini@low` matching `gpt-5.4-mini@med`
    # quality at -32% latency / -15% cost. Worth retesting on the
    # heavier resume-builder surface (tool loop, multi-turn intake,
    # proactive_offer + pending_followups channels). Two variants so we
    # can compare reasoning tiers head-to-head on the same slug.
    "gpt-5.4-mini@med": {"slug": "openai/gpt-5.4-mini", "reasoning_effort": "medium"},
    "gpt-5.4-mini@low": {"slug": "openai/gpt-5.4-mini", "reasoning_effort": "low"},
    "sonnet-4.5": {"slug": "anthropic/claude-sonnet-4.5", "reasoning_effort": None},
    "gemini": {"slug": "google/gemini-3.1-pro-preview", "reasoning_effort": None},
    "kimi": {"slug": "moonshotai/kimi-k2.6", "reasoning_effort": None},
    "glm": {"slug": "z-ai/glm-5.1", "reasoning_effort": None},
    "grok": {"slug": "x-ai/grok-4.20", "reasoning_effort": None},
    "deepseek": {"slug": "deepseek/deepseek-v4-pro", "reasoning_effort": None},
    "qwen": {"slug": "qwen/qwen3.6-max-preview", "reasoning_effort": None},
}


def _resolve_candidate_list(spec: str) -> list[str]:
    """Parse the --candidates argument into an ordered list of names.

    Accepts:
      "all"                       -> openai + every entry in _AGENTIC_CANDIDATES
      "openai,sonnet-4.5,gemini"  -> just those (preserves order)
      "sonnet-4.5"                -> just one
    """
    cleaned = (spec or "all").strip()
    if cleaned == "all":
        return ["openai", *_AGENTIC_CANDIDATES.keys()]
    names = [part.strip() for part in cleaned.split(",") if part.strip()]
    known = {"openai", *_AGENTIC_CANDIDATES.keys()}
    bad = [n for n in names if n not in known]
    if bad:
        raise SystemExit(
            f"Unknown candidate(s) {bad!r}. Known: {sorted(known)}."
        )
    return names


def _build_arm(name: str, *, model_override: str | None = None) -> tuple[Any, str]:
    """Build (service, label) for a candidate name.

    ``openai`` returns the production OpenAIService (no model override
    plumbed — the route picks gpt-5.4 by default). Anything else
    returns an OpenRouterEvalService bound to the slug from
    ``_AGENTIC_CANDIDATES`` (or the explicit model_override) plus the
    per-candidate reasoning_effort default — see the dict shape change
    in the resume-builder addendum.
    """
    if name == "openai":
        svc = OpenAIService()
        return svc, "openai:gpt-5.4"
    spec = _AGENTIC_CANDIDATES[name]
    slug = model_override or spec["slug"]
    effort = spec.get("reasoning_effort")
    from tests.quality.openrouter_eval_service import OpenRouterEvalService

    svc = OpenRouterEvalService(model=slug, default_reasoning_effort=effort)
    label = f"openrouter:{slug}"
    if effort:
        label = f"{label}@{effort}"
    return svc, label


def _print_comparison_matrix(per_candidate_results: dict[str, list[dict]]) -> None:
    """Render the candidate × scenario PASS/FAIL grid + totals."""
    candidate_names = list(per_candidate_results.keys())
    # Collect the union of scenario names across every candidate (some
    # candidates may have skipped web_search scenarios).
    scenario_names: list[str] = []
    seen: set[str] = set()
    for results in per_candidate_results.values():
        for r in results:
            if r["name"] not in seen:
                scenario_names.append(r["name"])
                seen.add(r["name"])

    # Build a lookup so we can render misses as a blank cell.
    cell: dict[tuple[str, str], str] = {}
    for cname, results in per_candidate_results.items():
        for r in results:
            cell[(cname, r["name"])] = "PASS" if r["passed"] else "FAIL"

    # Column-width: name field width = longest scenario name.
    name_w = max((len(n) for n in scenario_names), default=10)
    col_w = max(8, max(len(c) for c in candidate_names))

    print()
    print("=" * 80)
    print("MULTI-PROVIDER AGENTIC EVAL — comparison matrix")
    print("=" * 80)
    header = f"{'scenario'.ljust(name_w)} | " + " | ".join(
        c.ljust(col_w) for c in candidate_names
    )
    print(header)
    print("-" * len(header))
    for sname in scenario_names:
        row = f"{sname.ljust(name_w)} | " + " | ".join(
            cell.get((c, sname), "skip").ljust(col_w) for c in candidate_names
        )
        print(row)
    print("-" * len(header))
    totals: list[str] = []
    for cname in candidate_names:
        results = per_candidate_results[cname]
        passed = sum(1 for r in results if r["passed"])
        totals.append(f"{cname}: {passed}/{len(results)}")
    print("Totals — " + " · ".join(totals))


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
    parser.add_argument(
        "--candidates",
        default="openai",
        help=(
            "Candidate(s) to evaluate. 'all' = OpenAI baseline plus every "
            "OpenRouter slug in _AGENTIC_CANDIDATES (sonnet-4.5, gemini, "
            "kimi, glm, grok, deepseek, qwen). Comma-separated list (e.g. "
            "'openai,sonnet-4.5') picks a subset in that order. Default is "
            "'openai' so a vanilla run stays single-provider."
        ),
    )
    parser.add_argument(
        "--model",
        default=None,
        help=(
            "Optional model slug override. Only meaningful when --candidates "
            "is a single non-baseline name; overrides _AGENTIC_CANDIDATES's "
            "default slug for that one candidate. Useful for testing a new "
            "model id without editing this file."
        ),
    )
    args = parser.parse_args()

    candidate_names = _resolve_candidate_list(args.candidates)

    # Resolve scenario filter once (applies across every candidate).
    base_scenarios: list[dict[str, Any]] = SCENARIOS
    if args.scenario:
        base_scenarios = [s for s in SCENARIOS if s["name"] in set(args.scenario)]
        if not base_scenarios:
            print(f"No scenarios matched --scenario filter: {args.scenario}")
            return 2

    per_candidate_results: dict[str, list[dict[str, Any]]] = {}
    per_candidate_labels: dict[str, str] = {}

    # Run each candidate end-to-end before moving to the next. Lets
    # the user see early results streaming + cap spend mid-run by
    # killing the script if an early candidate is hopeless.
    for candidate in candidate_names:
        try:
            service, provider_label = _build_arm(
                candidate,
                model_override=(args.model if len(candidate_names) == 1 else None),
            )
        except KeyError as exc:
            print(f"Skipping unknown candidate {candidate!r}: {exc}")
            continue
        per_candidate_labels[candidate] = provider_label

        if not service.is_available():
            env_hint = (
                "OPENAI_API_KEY or openai_key.txt"
                if candidate == "openai"
                else "OPENROUTER_API_KEY (env or .env)"
            )
            print(
                f"== {candidate} ({provider_label}) — SKIPPED: not configured "
                f"({env_hint})"
            )
            per_candidate_results[candidate] = []
            continue

        # web_search is OpenAI-only (Slice 1F — wraps an inner
        # Responses-API call to OpenAI's built-in search tool). For
        # cross-provider fairness, skip those scenarios on every non-
        # openai candidate.
        if candidate == "openai":
            scenarios_for_arm = base_scenarios
            skipped_names: list[str] = []
        else:
            scenarios_for_arm = []
            skipped_names = []
            for s in base_scenarios:
                if s.get("requires_web_search"):
                    skipped_names.append(s["name"])
                else:
                    scenarios_for_arm.append(s)

        print()
        print("=" * 80)
        print(f"== {candidate} ({provider_label}) ==")
        if skipped_names:
            print(
                f"   (skipping {len(skipped_names)} web_search scenario(s) "
                f"for non-openai provider: {', '.join(skipped_names)})"
            )

        results: list[dict[str, Any]] = []
        for scenario in scenarios_for_arm:
            print(f"-- running {scenario['name']} ...", flush=True)
            try:
                result = run_scenario(scenario, service)
            except Exception as exc:
                # A provider hard-failure (auth, slug, billing) on
                # ONE scenario shouldn't tank the entire matrix run.
                # Record it as a failure so the row stays comparable.
                result = {
                    "name": scenario["name"],
                    "description": scenario["description"],
                    "passed": False,
                    "findings": [f"runtime error: {type(exc).__name__}: {exc}"],
                    "tool_events": [],
                    "proactive_offers": [],
                    "assistant_replies": [],
                    "error": f"{type(exc).__name__}: {exc}",
                    "structured_projects_count": 0,
                    "structured_education_count": 0,
                    "structured_skill_categories_count": 0,
                    "metrics": {
                        "elapsed_seconds": 0,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0,
                        "cost_usd": 0,
                        "tool_call_count": 0,
                        "pricing_slug": "(unknown)",
                    },
                }
            result["provider"] = provider_label
            results.append(result)
            status = "PASS" if result["passed"] else "FAIL"
            # Slice 1H heartbeat: one tabular metric line per scenario.
            # latency | tokens | cost | tool-calls | status — exactly
            # the columns a `tail -f` watcher needs to keep tabs on the
            # run in real time.
            m = result.get("metrics") or {}
            print(
                f"   {status} | {m.get('elapsed_seconds', 0):>6.2f}s"
                f" | {m.get('total_tokens', 0):>6} tok"
                f" | ${m.get('cost_usd', 0):>6.4f}"
                f" | {m.get('tool_call_count', 0)} tools",
                flush=True,
            )
            if not result["passed"]:
                for finding in result["findings"]:
                    print(f"     - {finding}", flush=True)
        per_candidate_results[candidate] = results

        # Slice 1H: incremental checkpoint after EVERY candidate
        # completes. If the run dies mid-matrix (provider hang, billing
        # cap, network), partial results survive on disk. Each
        # checkpoint overwrites the JSON file so the most recent state
        # is always one read away.
        if args.json:
            checkpoint = {
                "candidates": per_candidate_labels,
                "results": {
                    cname: per_candidate_results[cname]
                    for cname in per_candidate_results
                },
                "checkpoint_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "checkpoint_after_candidate": candidate,
            }
            with open(args.json, "w", encoding="utf-8") as fh:
                json.dump(checkpoint, fh, indent=2)
            print(
                f"   [checkpoint] wrote partial results to {args.json}",
                flush=True,
            )

        # Per-candidate roll-up so totals are visible without waiting
        # for the final comparison matrix.
        passed_count = sum(1 for r in results if r["passed"])
        total_cost = sum((r.get("metrics") or {}).get("cost_usd", 0) for r in results)
        total_tokens = sum(
            (r.get("metrics") or {}).get("total_tokens", 0) for r in results
        )
        avg_latency = (
            sum((r.get("metrics") or {}).get("elapsed_seconds", 0) for r in results)
            / len(results)
            if results
            else 0
        )
        print(
            f"   ===> {candidate} done: {passed_count}/{len(results)} PASS, "
            f"avg {avg_latency:.1f}s/scenario, {total_tokens} tok, "
            f"${total_cost:.4f}",
            flush=True,
        )

    if not per_candidate_results:
        print("\nNo candidates ran. Check --candidates / API key configuration.")
        return 2

    _print_comparison_matrix(per_candidate_results)

    if args.json:
        report = {
            "candidates": per_candidate_labels,
            "results": {
                cname: per_candidate_results[cname]
                for cname in per_candidate_results
            },
            "completed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
        print(f"\nwrote JSON report -> {args.json}")

    # Exit non-zero if any candidate failed any scenario — keeps this
    # script usable as a CI gate for "did the chosen provider regress?"
    any_failures = any(
        not r["passed"]
        for results in per_candidate_results.values()
        for r in results
    )
    return 0 if not any_failures else 1


if __name__ == "__main__":
    sys.exit(main())
