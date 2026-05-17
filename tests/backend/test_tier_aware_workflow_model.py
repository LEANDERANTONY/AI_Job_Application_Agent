"""Tier-aware model selection for the assisted workflow.

Step 7a of the tier-enforcement series. The workflow agents
(tailoring / review / resume_generation / cover_letter) normally read
their model from `OPENAI_MODEL_ROUTING` keyed by task name. When the
caller passes ``premium=True`` AND the user's tier supports it
(``"pro"`` / ``"business"``), the three high-trust agents — review,
resume_generation, cover_letter — should route to the premium model
(``gpt-5.5`` by default) instead of ``gpt-5.4``. Tailoring stays on
mini under premium because the COGS analysis pinned tailoring at the
mini tier regardless.

These tests pin five invariants:

  1. Free + premium=False uses the standard tailoring model. (Today
     free + premium=True is rejected upstream, so we cover the legal
     combination only.)
  2. Pro + premium=False uses the default high-trust model for review
     / resume_generation / cover_letter, NOT the premium model.
  3. Pro + premium=True uses the premium model for review /
     resume_generation / cover_letter, AND still uses the mini for
     tailoring.
  4. Business + premium=True matches Pro + premium=True.
  5. Recovery path: calling the helper twice still returns the same
     answer — no stateful side effect on either call.

A sixth defensive case covers the unreachable-but-defensive branch
where premium=True somehow reaches the helper on a free tier (the gate
would normally reject this first). The helper falls back gracefully
(no upgrade) so a future gate regression can't silently burn premium
credits AND deliver the upgraded model.
"""
from __future__ import annotations

from backend.model_routing import (
    build_workflow_model_overrides,
    build_workflow_reasoning_overrides,
    select_workflow_model,
    select_workflow_reasoning,
)


# ─── select_workflow_model: per-task lookup ─────────────────────────────


def test_free_workflow_uses_default_tailoring_model():
    """Free + premium=False on tailoring returns None (= use the
    default `OPENAI_MODEL_ROUTING["tailoring"]`, which is mini). The
    point of the override map is that None means "no override" so the
    standard task-name lookup wins downstream."""
    assert select_workflow_model(task="tailoring", tier="free", premium=False) is None


def test_pro_basic_workflow_uses_default_high_trust_model():
    """Pro + premium=False on the three high-trust tasks returns None
    so the orchestrator falls through to `OPENAI_MODEL_ROUTING`
    which routes them to gpt-5.4 (the high-trust model). Premium has
    to be EXPLICITLY opted into per-run; a paying Pro user gets the
    upgrade only when they pay the premium credit."""
    for task in ("review", "resume_generation", "cover_letter"):
        assert (
            select_workflow_model(task=task, tier="pro", premium=False) is None
        ), task


def test_pro_premium_workflow_routes_high_trust_to_gpt_5_5():
    """Pro + premium=True on review / resume_generation / cover_letter
    returns the premium model name. Tailoring stays on the default
    routing (mini) because the COGS analysis pinned it at mini under
    every plan."""
    for task in ("review", "resume_generation", "cover_letter"):
        override = select_workflow_model(task=task, tier="pro", premium=True)
        assert override == "gpt-5.5", task
    # Tailoring is NOT in the premium upgrade set.
    assert select_workflow_model(task="tailoring", tier="pro", premium=True) is None


def test_business_premium_matches_pro_premium():
    """Business has the same per-agent upgrade set as Pro — only the
    quota caps differ. The model selection logic is tier-uniform once
    the eligibility check (tier in {pro, business}) passes."""
    for task in ("review", "resume_generation", "cover_letter"):
        pro_override = select_workflow_model(
            task=task, tier="pro", premium=True
        )
        business_override = select_workflow_model(
            task=task, tier="business", premium=True
        )
        assert pro_override == business_override == "gpt-5.5", task


def test_recovery_path_returns_same_answer_on_repeat_call():
    """Calling the helper twice for the same (task, tier, premium)
    triple must return the same answer — no hidden state, no cache
    that could desync. This is the "cache-key sensitivity" stand-in
    for the workflow path (which has no cache layer of its own). The
    helper is a pure function; this test pins that invariant.
    """
    first = select_workflow_model(task="review", tier="pro", premium=True)
    second = select_workflow_model(task="review", tier="pro", premium=True)
    assert first == second == "gpt-5.5"

    # Cover the inverse too — the None branch should also be stable
    # across repeat calls.
    first_none = select_workflow_model(task="tailoring", tier="pro", premium=True)
    second_none = select_workflow_model(task="tailoring", tier="pro", premium=True)
    assert first_none is second_none is None


# ─── defensive guard: free + premium=True ───────────────────────────────


def test_free_with_premium_true_falls_back_to_no_upgrade():
    """Defensive branch — the gate at /workspace/analyze already
    rejects Free + premium=True with a 429, so this combination
    shouldn't reach the helper on the happy path. If it ever does
    (gate regression, eval scripts, etc.), the helper must NOT serve
    the upgraded model — that would let a future bug bill the user
    for a premium credit (= 0 caps on Free, instantly hit) AND quietly
    serve them gpt-5.5 anyway. Falling back to None means the
    orchestrator uses the standard gpt-5.4 routing, which is the safe
    failure mode."""
    for task in ("review", "resume_generation", "cover_letter"):
        assert (
            select_workflow_model(task=task, tier="free", premium=True) is None
        ), task


# ─── build_workflow_model_overrides: aggregate map ──────────────────────


def test_build_overrides_free_basic_yields_all_none():
    overrides = build_workflow_model_overrides(tier="free", premium=False)
    assert overrides == {
        "tailoring": None,
        "review": None,
        "resume_generation": None,
        "cover_letter": None,
    }


def test_build_overrides_pro_premium_targets_only_high_trust():
    """Pro premium: tailoring stays None (no upgrade) but the three
    high-trust agents flip to gpt-5.5. This is the canonical map the
    orchestrator hands its agents on a premium run."""
    overrides = build_workflow_model_overrides(tier="pro", premium=True)
    assert overrides["tailoring"] is None
    assert overrides["review"] == "gpt-5.5"
    assert overrides["resume_generation"] == "gpt-5.5"
    assert overrides["cover_letter"] == "gpt-5.5"


def test_build_overrides_business_premium_matches_pro_premium():
    pro = build_workflow_model_overrides(tier="pro", premium=True)
    business = build_workflow_model_overrides(tier="business", premium=True)
    assert pro == business


# ─── orchestrator integration: end-to-end model wiring ──────────────────


class _ModelRecordingOpenAIService:
    """Test double that records the resolved model for every
    `run_json_prompt` call. Lets us assert that the orchestrator
    actually threaded the override map into the agents' calls.

    Doesn't actually run any real LLM — returns canned per-task
    payloads keyed by task_name. Each agent's expected output shape
    is hardcoded below so the orchestrator can run end-to-end.
    """

    def __init__(self):
        self.model = "default-recorder"
        self.default_model = "default-recorder"
        self.calls: list[dict] = []

    def is_available(self):
        return True

    def describe_model_policy(self):
        return "recorder"

    def run_json_prompt(
        self,
        system_prompt,
        user_prompt,
        expected_keys=None,
        max_completion_tokens=1200,
        task_name=None,
        model=None,
        metadata=None,
        reasoning_effort=None,
        **_,
    ):
        self.calls.append(
            {
                "task_name": task_name,
                "model": model,
                "reasoning_effort": reasoning_effort,
            }
        )
        return _canned_response_for(task_name)


def _canned_response_for(task_name: str) -> dict:
    """Per-task canned payloads matching each agent's expected_keys."""
    if task_name == "tailoring":
        return {
            "professional_summary": "Grounded tailored summary.",
            "rewritten_bullets": ["Built Python services."],
            "highlighted_skills": ["Python", "SQL"],
            "cover_letter_themes": ["Strong delivery fit."],
        }
    if task_name == "review":
        return {
            "approved": True,
            "grounding_issues": [],
            "unresolved_issues": [],
            "revision_requests": [],
            "final_notes": ["Grounded output."],
            "corrected_tailoring": {
                "professional_summary": "Grounded tailored summary.",
                "rewritten_bullets": ["Built Python services."],
                "highlighted_skills": ["Python", "SQL"],
                "cover_letter_themes": ["Strong delivery fit."],
            },
        }
    if task_name == "resume_generation":
        return {
            "professional_summary": "Grounded summary for the role.",
            "highlighted_skills": ["Python", "SQL"],
            "experience_bullets": ["Built Python services."],
            "section_order": [
                "Professional Summary",
                "Core Skills",
                "Professional Experience",
                "Education",
            ],
            "template_hint": "classic_ats",
        }
    if task_name == "cover_letter":
        return {
            "greeting": "Dear Hiring Team",
            "opening_paragraph": "Opening.",
            "body_paragraphs": ["Body."],
            "closing_paragraph": "Closing.",
            "signoff": "Sincerely",
            "signature_name": "Candidate",
        }
    raise AssertionError(f"unexpected task_name: {task_name!r}")


def _build_inputs():
    """Minimal candidate + JD pair the orchestrator can run end-to-end."""
    from src.schemas import ResumeDocument
    from src.services.job_service import build_job_description_from_text
    from src.services.profile_service import build_candidate_profile_from_resume

    candidate = build_candidate_profile_from_resume(
        ResumeDocument(
            text=(
                "Leander Antony\n"
                "Python SQL Docker\n"
                "Built Python services in production."
            ),
            filetype="TXT",
            source="uploaded",
        )
    )
    job_description = build_job_description_from_text(
        "Software Engineer\n"
        "Required: Python, SQL.\n"
        "3+ years experience.\n"
    )
    return candidate, job_description


def test_orchestrator_threads_premium_override_to_high_trust_agents():
    """Pro + premium=True: the orchestrator passes gpt-5.5 as the
    `model=` kwarg for the three high-trust agents, and None for
    tailoring. This is the on-the-wire assertion that the helper +
    threading actually deliver the premium routing."""
    from src.agents.orchestrator import ApplicationOrchestrator

    recorder = _ModelRecordingOpenAIService()
    overrides = build_workflow_model_overrides(tier="pro", premium=True)
    candidate, job = _build_inputs()

    ApplicationOrchestrator(
        openai_service=recorder,
        model_overrides=overrides,
    ).run(candidate, job)

    # Group the calls by task_name; the orchestrator may invoke each
    # task once or twice (e.g. retry path) — we just need to confirm
    # the model argument matches the override for every invocation.
    by_task: dict[str, list[object]] = {}
    for call in recorder.calls:
        by_task.setdefault(call["task_name"], []).append(call["model"])

    # Tailoring stays on default routing (model=None → task lookup).
    assert by_task.get("tailoring"), "tailoring should have been called"
    for resolved in by_task["tailoring"]:
        assert resolved is None

    # The three high-trust agents got gpt-5.5 for every call.
    for task in ("review", "resume_generation", "cover_letter"):
        assert by_task.get(task), f"{task} should have been called"
        for resolved in by_task[task]:
            assert resolved == "gpt-5.5", f"{task} got {resolved!r}"


def test_orchestrator_does_not_upgrade_pro_basic():
    """Pro + premium=False: every call passes model=None so the
    standard `OPENAI_MODEL_ROUTING` resolution wins. This is the
    test that locks "Pro user without premium DOESN'T silently get
    the upgrade for free"."""
    from src.agents.orchestrator import ApplicationOrchestrator

    recorder = _ModelRecordingOpenAIService()
    overrides = build_workflow_model_overrides(tier="pro", premium=False)
    candidate, job = _build_inputs()

    ApplicationOrchestrator(
        openai_service=recorder,
        model_overrides=overrides,
    ).run(candidate, job)

    for call in recorder.calls:
        assert call["model"] is None, call


# ─── ADR-028 D2: premium reasoning-effort override ──────────────────────


def test_select_workflow_reasoning_only_lifts_review_on_premium():
    # Non-premium: never an override, any tier.
    for tier in ("free", "pro", "business"):
        for task in ("tailoring", "review", "resume_generation", "cover_letter"):
            assert select_workflow_reasoning(
                task=task, tier=tier, premium=False
            ) is None
    # Free + premium=True is defensively None (the gate rejects it).
    assert select_workflow_reasoning(task="review", tier="free", premium=True) is None
    # Pro/Business + premium: ONLY review lifts to "high".
    for tier in ("pro", "business"):
        assert (
            select_workflow_reasoning(task="review", tier=tier, premium=True)
            == "high"
        )
        for task in ("tailoring", "resume_generation", "cover_letter"):
            assert select_workflow_reasoning(
                task=task, tier=tier, premium=True
            ) is None


def test_build_workflow_reasoning_overrides_shape():
    basic = build_workflow_reasoning_overrides(tier="pro", premium=False)
    assert set(basic) == {"tailoring", "review", "resume_generation", "cover_letter"}
    assert all(v is None for v in basic.values())

    premium = build_workflow_reasoning_overrides(tier="pro", premium=True)
    assert premium["review"] == "high"
    assert premium["tailoring"] is None
    assert premium["resume_generation"] is None
    assert premium["cover_letter"] is None


def test_orchestrator_threads_premium_reasoning_to_review_only():
    """Pro + premium=True: the orchestrator passes reasoning_effort
    "high" for review and None (routed default) for the others —
    the on-the-wire proof that ADR-028 D2 actually delivers."""
    from src.agents.orchestrator import ApplicationOrchestrator

    recorder = _ModelRecordingOpenAIService()
    candidate, job = _build_inputs()

    ApplicationOrchestrator(
        openai_service=recorder,
        model_overrides=build_workflow_model_overrides(tier="pro", premium=True),
        reasoning_overrides=build_workflow_reasoning_overrides(
            tier="pro", premium=True
        ),
    ).run(candidate, job)

    by_task: dict[str, list[object]] = {}
    for call in recorder.calls:
        by_task.setdefault(call["task_name"], []).append(call["reasoning_effort"])

    assert by_task.get("review"), "review should have been called"
    for effort in by_task["review"]:
        assert effort == "high", f"review reasoning got {effort!r}"
    for task in ("tailoring", "resume_generation", "cover_letter"):
        for effort in by_task.get(task, []):
            assert effort is None, f"{task} reasoning got {effort!r}"


def test_orchestrator_does_not_upgrade_reasoning_pro_basic():
    """Pro + premium=False: every call passes reasoning_effort=None
    so standard routing wins — no silent reasoning upgrade for free."""
    from src.agents.orchestrator import ApplicationOrchestrator

    recorder = _ModelRecordingOpenAIService()
    candidate, job = _build_inputs()

    ApplicationOrchestrator(
        openai_service=recorder,
        model_overrides=build_workflow_model_overrides(tier="pro", premium=False),
        reasoning_overrides=build_workflow_reasoning_overrides(
            tier="pro", premium=False
        ),
    ).run(candidate, job)

    for call in recorder.calls:
        assert call["reasoning_effort"] is None, call
