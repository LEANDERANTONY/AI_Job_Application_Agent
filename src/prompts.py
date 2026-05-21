import json
from dataclasses import asdict, is_dataclass
from typing import Any, Dict, Iterable

from src.schemas import (
    CandidateProfile,
    FitAnalysis,
    JobDescription,
    ReviewAgentOutput,
    TailoredResumeDraft,
    TailoringAgentOutput,
)


def _to_serializable(value: Any):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {key: _to_serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_serializable(item) for item in value]
    return value


# Shared system-prompt block that teaches the assistant how to read and
# use the live workspace-state projection sent on every turn (see
# `WorkspaceStateContext` on the frontend / `WorkspaceStateContextModel`
# on the backend).
#
# The canonical copy of this content now lives in ``prompts/assistant/v1.json``
# (JSON-contract path) AND ``prompts/assistant_text/v1.json`` (SSE-streaming
# prose path) — see prompts/README.md. This Python constant is retained as
# the byte-identity reference for ``tests/test_prompts.py``, so any future
# wording edit only has to land in three places (two JSON files and this
# constant) and the test harness catches drift.
_WORKSPACE_STATE_GUIDANCE = (
    "WORKSPACE STATE: A `workspace_state` object inside `product_context` reflects the user's live progress. Read it before answering ANY question that touches what the user has done so far. "
    "Fields: `current_step` (one of resume / jobs / jd / analysis — the tab the user is on right now), `has_resume` and `resume_summary` (parsed CandidateProfile — name, location, skills_count, experience_entries_count, has_certifications), `has_jd` and `jd_summary` (parsed JobDescription — title, location, hard_skills_count, soft_skills_count, must_haves_count), `has_analysis` (true once the analysis pipeline has produced a fit score), `saved_jobs_count` (size of the user's shortlist), `last_search_query` (last keyword they searched). "
    "Step numbering when the user asks 'what's step N?': step 01 = Resume, step 02 = Job Search, step 03 = Job Detail (JD review), step 04 = Analysis. The `current_step` value matches each step's id. "
    "Auth: the workspace requires sign-in. If a user is signed out, they get redirected to the landing page and can't use ANY workspace feature — Resume, Job Search, Job Detail, Analysis, or this assistant. So if the user asks 'can I do X without signing in?', the answer is NO for any in-workspace action. The fact that this assistant is responding at all means the user is on the workspace page, which means they're signed in (or in a preview/test). Don't tell users they can run analysis or upload resumes signed-out — they'd be on the landing page. "
    "Field semantics — read carefully: "
    "`experience_entries_count` is the number of WORK ENTRIES on the resume (e.g. 4 jobs held), NOT years of total experience. If the user asks 'how many years of experience do I have?', the resume_summary does NOT carry that — say it isn't computed in the current context and offer to look at the parsed experience timeline once the snapshot is available. "
    "`skills_count` is a count, not a list — never enumerate specific skills from the count alone. "
    "Rules: "
    "(1) ALWAYS check workspace_state before answering 'what's next?', 'is my resume parsed?', 'why is X locked?'. "
    "(2) If `has_resume === false` and the user asks about resume content, do NOT invent skills, jobs, or experience — say the resume hasn't been uploaded yet and offer the upload step. "
    "(3) If `has_jd === false` and the user asks about a role's requirements, the same rule applies — there is no JD yet. "
    "(4) If `has_analysis === false`, you don't have a fit score, matched/missing skills, or a tailored resume — be explicit about that and explain that running the analysis is the next step. "
    "(5) When the user asks 'what should I do next?' or similar, use `current_step` plus the boolean flags to suggest the very next concrete action (e.g. on `current_step='resume'` with `has_resume=false` → 'upload your PDF here'; on `current_step='jobs'` with `saved_jobs_count=0` → 'try a search or import a posting URL'; on `current_step='jd'` with `has_jd=false` → 'paste the job description into the textarea'; on `current_step='analysis'` with `has_resume=true` and `has_jd=true` and `has_analysis=false` → 'press Run analysis'). "
    "(6) When `has_analysis === true`, prefer grounding from `workflow_context` / `workspace_snapshot` for specifics; fall back to `workspace_state` summaries when those are absent. "
    "(7) Never echo raw counts as the answer ('skills_count: 27'). Translate into human language ('we found 27 skills on your resume'). "
    "(8) Be concise — 1-3 sentences for product help, longer only when the user asked for explanation or coaching. "
)


# Slice 1J': stop sounding ignorant about product details. The
# WORKSPACE STATE block teaches the assistant how to read live runtime
# state but says nothing about pricing, themes, the agentic pipeline,
# or the assistant's own limits — so when a user asked "what tiers do
# you have?" / "what themes can I use?" / "can you book me an
# interview?", the answers ranged from "I don't have that info" to
# outright fabrications. This block backstops all of those questions
# with authoritative numbers sourced from backend/tiers.py + the
# RESUME_THEMES registry. If a value here drifts from the source-of-
# truth tables, the
# ``test_assistant_prompt_matches_pre_migration_system_byte_for_byte``
# byte-mirror test catches it on the next CI run.
#
# Source of truth: backend/tiers.py (TIER_CAPS), src/resume_builder.py
# (RESUME_THEMES), backend/tiers.py (FREE_EXPORT_FORMAT/THEME), and
# src/agents/* (the orchestrator chain).
_PRODUCT_KNOWLEDGE_BLOCK = (
    "PRODUCT KNOWLEDGE (authoritative — use these answers when asked): "
    "Pricing tiers: Free / Pro / Business. The monthly caps are: "
    "tailored applications 3 / 20 / 80; premium applications 0 / 5 / 25; "
    "assistant turns (this chat) 20 / 150 / 500; resume parses 3 / 25 / 100; "
    "job searches 50 / unlimited / unlimited. Persistent counters: saved jobs 5 / 1000 / unlimited; saved workspaces 1 / 5 / unlimited. "
    "Resume builder sessions are LIFETIME on Free (1 total, never resets) and monthly on Pro (3) / Business (15). "
    "Saved-workspace retention: Free 7 days, Pro 30 days, Business unbounded. "
    "Resume themes — FIVE are available to users for export, all single-column and ATS-safe: professional_neutral (the product-wide default), classic_ats, modern_blue, creative_warm, architect_mono. "
    "There is no two-column, multi-column, or sidebar resume theme available today — if a user asks for one, say it isn't offered yet (a two-column 'presentation' layout exists in the renderer but is held from users pending a designer-grade rework; do NOT present it as selectable). "
    "Export entitlement: Free exports PDF in professional_neutral only; Pro and Business export PDF or DOCX in any theme. There is no plain-text or HTML export. "
    "Resume intake paths: users can either UPLOAD a PDF (parsed into a CandidateProfile) or use the conversational RESUME BUILDER (multi-turn chat that fills the same profile field-by-field). Both feed the same downstream pipeline. "
    "Agentic analysis chain when the user presses 'Run analysis' on a resume + JD pair: tailoring → review → resume generation → cover letter. The review pass detects fabrications and asks the user before rewriting (conservative correction posture). "
    "What this assistant CANNOT do (be honest if asked): schedule interviews, send emails or messages to recruiters, log in to LinkedIn / Indeed / any external account on the user's behalf, scrape arbitrary URLs (it can only summarize artifacts present in the workspace context), edit the user's resume file directly (resume edits happen through the upload or builder flow), make payments or change the user's subscription tier, or remember anything across browser sessions when signed out. "
    "Quotas reset at the start of each calendar month (UTC) for monthly counters; lifetime counters never reset. If a user hits a cap, they see the upgrade nudge — this assistant does not bypass the gate. "
)


def _json_block(label: str, value: Any) -> str:
    payload = json.dumps(_to_serializable(value), indent=2, default=str)
    return "{label}:\n{payload}".format(label=label, payload=payload)


# Slice 1B: how many characters of conversation history the resume-
# builder prompt is willing to feed back to the model on each turn.
# 30k chars ≈ ~7.5k tokens — well under the conversational budget for
# even the cheaper models, leaves headroom for the structured draft +
# system prompt + completion. The cap is HOLISTIC: when the serialized
# history would exceed it, the OLDEST entries are dropped one at a
# time until it fits.
RESUME_BUILDER_HISTORY_CHAR_BUDGET = 30000

# Slice 1J: the workspace-assistant prompts (JSON + SSE-text variants)
# carry a much larger static payload than the resume builder — the
# `assistant_context` block alone embeds workspace_snapshot, workflow_
# context, and the verbose _WORKSPACE_STATE_GUIDANCE rules. To keep the
# total turn under the same effective token ceiling we cap history at
# 18k chars (~4.5k tokens), leaving ~13k for context + system + reply.
# Same drop-oldest-first semantics as the resume builder. Before Slice
# 1J this was a hard `history[-4:]` slice that lost mid-session memory
# in any session longer than 4 turns — a worse version of the bug Slice
# 1B fixed for the resume builder.
ASSISTANT_HISTORY_CHAR_BUDGET = 18000


def _slice_history_for_budget(
    history: list,
    *,
    max_chars: int = RESUME_BUILDER_HISTORY_CHAR_BUDGET,
) -> list:
    """Return the most recent suffix of `history` whose JSON
    serialization fits under `max_chars`.

    Drops the OLDEST entries first — earlier turns are summarized by
    the structured ``draft`` state we also pass to the model, so
    losing the verbatim back-and-forth from turn 1 is graceful. The
    most-recent turn pair is ALWAYS retained: if even the last entry
    doesn't fit, we still return it (the model will see at least one
    turn of context). The caller's responsibility to enforce a
    sensible cap on the conversation_history list overall — this
    function is a per-prompt budget guard, not the memory cap.
    """
    if not history:
        return []
    # Walk from the newest entry backward, accumulating until we'd
    # blow the budget. The check is on the serialized form because
    # that's what actually rides in the prompt — a single entry whose
    # raw `content` is short can still take >2× its raw length in
    # JSON (escapes + indentation + quotes).
    selected: list = []
    accumulated_chars = 0
    for entry in reversed(history):
        serialized_entry = json.dumps(_to_serializable(entry), default=str)
        # Estimate the cost of this entry as if added to the array.
        # We count the entry's serialized length + 2 (for the comma +
        # newline-indent the json.dumps(indent=2) emits between items)
        # to avoid the off-by-one of guessing the final framing chars.
        entry_cost = len(serialized_entry) + 2
        if selected and accumulated_chars + entry_cost > max_chars:
            break
        selected.append(entry)
        accumulated_chars += entry_cost
    # We accumulated newest-first; flip back so the model sees them in
    # chronological order.
    selected.reverse()
    return selected


def _truncate_text(value: Any, max_chars: int) -> str:
    text = str(value or "")
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    if max_chars <= 16:
        return text[:max_chars]
    return text[: max_chars - 16].rstrip() + "...[truncated]"


def _compact_prompt_value(value: Any, *, max_string_chars: int, max_list_items: int):
    serializable = _to_serializable(value)
    if isinstance(serializable, dict):
        return {
            key: _compact_prompt_value(
                item,
                max_string_chars=max_string_chars,
                max_list_items=max_list_items,
            )
            for key, item in serializable.items()
        }
    if isinstance(serializable, list):
        return [
            _compact_prompt_value(
                item,
                max_string_chars=max_string_chars,
                max_list_items=max_list_items,
            )
            for item in serializable[:max_list_items]
        ]
    if isinstance(serializable, tuple):
        return [
            _compact_prompt_value(
                item,
                max_string_chars=max_string_chars,
                max_list_items=max_list_items,
            )
            for item in serializable[:max_list_items]
        ]
    if isinstance(serializable, str):
        return _truncate_text(serializable, max_string_chars)
    return serializable


def _json_block_with_budget(label: str, value: Any, *, max_chars: int) -> tuple[str, Dict[str, Any]]:
    serialized_value = _to_serializable(value)
    original_payload = json.dumps(serialized_value, indent=2, default=str)
    payload = original_payload
    compacted = False

    if len(payload) > max_chars:
        compacted = True
        for max_string_chars, max_list_items in (
            (600, 12),
            (420, 8),
            (280, 6),
            (180, 4),
            (120, 3),
        ):
            compacted_value = _compact_prompt_value(
                serialized_value,
                max_string_chars=max_string_chars,
                max_list_items=max_list_items,
            )
            payload = json.dumps(compacted_value, indent=2, default=str)
            if len(payload) <= max_chars:
                break

        if len(payload) > max_chars:
            payload = json.dumps(
                {
                    "summary": "Section compacted to stay within the prompt budget.",
                    "preview": _truncate_text(payload, min(max_chars, 600)),
                },
                indent=2,
                default=str,
            )

    return (
        "{label}:\n{payload}".format(label=label, payload=payload),
        {
            "label": label,
            "original_chars": len(original_payload),
            "final_chars": len(payload),
            "compacted": compacted,
        },
    )


def _build_budgeted_user_prompt(sections: Iterable[tuple[str, Any, int]]) -> tuple[str, Dict[str, str]]:
    blocks = []
    stats = []
    for label, value, max_chars in sections:
        block, stat = _json_block_with_budget(label, value, max_chars=max_chars)
        blocks.append(block)
        stats.append(stat)

    user_prompt = "\n\n".join(blocks)
    compacted_labels = [stat["label"] for stat in stats if stat["compacted"]]
    metadata = {
        "estimated_input_chars": str(len(user_prompt)),
        "compacted_sections": str(len(compacted_labels)),
        "prompt_budget_mode": "compacted" if compacted_labels else "full",
    }
    if compacted_labels:
        metadata["compacted_labels"] = ", ".join(compacted_labels)
    return user_prompt, metadata


def _build_contract(contract: Dict[str, str]) -> str:
    lines = ["Return JSON only with exactly these keys:"]
    for key, description in contract.items():
        lines.append('- "{key}": {description}'.format(key=key, description=description))
    return "\n".join(lines)


def _strict_expected_keys(template, *, fallback: list[str] | None = None) -> list[str]:
    """Pull ``metadata.expected_keys`` off a registry-loaded template
    with strict type checking. Used by every prompt builder that
    delegates to the registry — keeps the validation logic in one
    place so a registry mistake fails fast and identically across all
    builders.

    Three invariants:
      1. None / missing → fall back to the caller-supplied default
         (only the tailoring builder uses this — it shipped a hardcoded
         default before the migration). All other builders pass None
         which means "no default; missing is an error".
      2. Non-list → ``TypeError`` (CodeRabbit on PR #3 round 1).
      3. List with non-string entry → ``TypeError`` (CodeRabbit on
         PR #3 round 4). The previous ``[str(k) for k in ...]``
         coerced ``["answer", 1]`` to ``["answer", "1"]``, silently
         changing the output contract; this raises instead.
    """
    raw = template.metadata.get("expected_keys")
    if raw is None:
        if fallback is not None:
            return list(fallback)
        raise TypeError(
            f"{template.name} prompt metadata.expected_keys is missing; "
            "the registry entry must include a list of string keys."
        )
    if not isinstance(raw, list):
        raise TypeError(
            f"{template.name} prompt metadata.expected_keys must be a list of "
            f"strings, got {type(raw).__name__!s}."
        )
    for index, item in enumerate(raw):
        if not isinstance(item, str):
            raise TypeError(
                f"{template.name} prompt metadata.expected_keys[{index}] must "
                f"be a string, got {type(item).__name__!s} ({item!r})."
            )
    return list(raw)


def build_tailoring_agent_prompt(
    candidate_profile: CandidateProfile,
    job_description: JobDescription,
    fit_analysis: FitAnalysis,
    tailored_draft: TailoredResumeDraft,
) -> Dict[str, Any]:
    """Build the TailoringAgent prompt.

    Migrated to the prompt registry: ``system`` is loaded from
    ``prompts/tailoring/v1.json`` via ``backend.prompt_registry``.
    The user prompt + budgeting glue stays in Python — that logic
    is too procedural to express cleanly in JSON.

    Note: a previous version of this prompt also included the
    FitAgent's narrated 'top matches / key gaps' as an extra context
    block. That agent has been removed — TailoringAgent now reads the
    structured FitAnalysis directly. One fewer LLM call per workspace
    analysis with no quality regression.
    """
    # Local import: keeps src/prompts.py importable without the
    # backend package on the path (e.g. some unit tests that exercise
    # the deterministic builders directly).
    from backend.prompt_registry import get_prompt

    template = get_prompt("tailoring")
    sections = [
        ("Candidate Profile", candidate_profile, 2200),
        ("Job Description", job_description, 1800),
        ("Deterministic Fit Analysis", fit_analysis, 1600),
        ("Deterministic Tailored Draft", tailored_draft, 1800),
    ]
    user_prompt, metadata = _build_budgeted_user_prompt(sections)
    # Validate ``expected_keys`` is a list, not a string. A
    # misconfigured registry entry that put the keys in as a string
    # (``"professional_summary,rewritten_bullets,..."``) would silently
    # ``list(...)`` into a character array (``["p","r","o",...]``) and
    # break downstream response parsing without a clear error. The
    # explicit type check raises a TypeError instead. CodeRabbit
    # finding on PR #3.
    expected_keys = _strict_expected_keys(
        template,
        fallback=[
            "professional_summary",
            "rewritten_bullets",
            "highlighted_skills",
            "cover_letter_themes",
        ],
    )
    return {
        "system": template.system,
        "user": user_prompt,
        "expected_keys": expected_keys,
        "metadata": metadata,
    }


def build_review_agent_prompt(
    candidate_profile: CandidateProfile,
    job_description: JobDescription,
    fit_analysis: FitAnalysis,
    tailored_draft: TailoredResumeDraft,
    tailoring_output: TailoringAgentOutput,
) -> Dict[str, Any]:
    """Migrated to the prompt registry: system + expected_keys are
    loaded from ``prompts/review/v1.json``; only the budgeted user
    prompt + per-section truncation metadata stay in Python."""
    from backend.prompt_registry import get_prompt

    template = get_prompt("review")
    sections = [
        ("Candidate Profile", candidate_profile, 2000),
        ("Job Description", job_description, 1600),
        ("Deterministic Fit Analysis", fit_analysis, 1600),
        ("Deterministic Tailored Draft", tailored_draft, 1800),
        ("Tailoring Agent Output", tailoring_output, 1400),
    ]
    user_prompt, metadata = _build_budgeted_user_prompt(sections)
    expected_keys = _strict_expected_keys(template)
    return {
        "system": template.system,
        "user": user_prompt,
        "expected_keys": expected_keys,
        "metadata": metadata,
    }


def build_resume_generation_agent_prompt(
    candidate_profile: CandidateProfile,
    job_description: JobDescription,
    fit_analysis: FitAnalysis,
    tailored_draft: TailoredResumeDraft,
    tailoring_output: TailoringAgentOutput,
    review_output: ReviewAgentOutput = None,
) -> Dict[str, Any]:
    """Migrated to the prompt registry: system + expected_keys are
    loaded from ``prompts/resume_generation/v1.json``."""
    from backend.prompt_registry import get_prompt

    template = get_prompt("resume_generation")
    sections = [
        ("Candidate Profile", candidate_profile, 1800),
        ("Job Description", job_description, 1500),
        ("Deterministic Fit Analysis", fit_analysis, 1500),
        ("Deterministic Tailored Draft", tailored_draft, 1800),
        ("Tailoring Agent Output", tailoring_output, 1400),
    ]
    user_prompt, metadata = _build_budgeted_user_prompt(sections)
    expected_keys = _strict_expected_keys(template)
    return {
        "system": template.system,
        "user": user_prompt,
        "expected_keys": expected_keys,
        "metadata": metadata,
    }


def build_cover_letter_agent_prompt(
    candidate_profile: CandidateProfile,
    job_description: JobDescription,
    fit_analysis: FitAnalysis,
    tailored_draft: TailoredResumeDraft,
    tailoring_output: TailoringAgentOutput,
    review_output: ReviewAgentOutput = None,
    resume_generation_output=None,
) -> Dict[str, Any]:
    """Migrated to the prompt registry: system + expected_keys are
    loaded from ``prompts/cover_letter/v1.json``."""
    from backend.prompt_registry import get_prompt

    template = get_prompt("cover_letter")
    sections = [
        ("Candidate Profile", candidate_profile, 1800),
        ("Job Description", job_description, 1500),
        ("Deterministic Fit Analysis", fit_analysis, 1400),
        ("Deterministic Tailored Draft", tailored_draft, 1600),
        ("Approved Tailoring Output", tailoring_output, 1400),
    ]
    if review_output:
        sections.append(("Review Output", review_output, 1200))
    if resume_generation_output:
        sections.append(("Resume Generation Output", resume_generation_output, 1200))
    user_prompt, metadata = _build_budgeted_user_prompt(sections)
    expected_keys = _strict_expected_keys(template)
    return {
        "system": template.system,
        "user": user_prompt,
        "expected_keys": expected_keys,
        "metadata": metadata,
    }


def build_assistant_prompt(
    assistant_context: Dict[str, Any],
    question: str,
    history: Any = None,
) -> Dict[str, Any]:
    """Unified in-app assistant prompt (JSON contract variant).

    Migrated to the prompt registry: ``system`` and ``expected_keys`` are
    loaded from ``prompts/assistant/v1.json``. The user prompt — the
    serialized assistant context + question + optional recent history —
    is composed in Python because it is dynamic per turn.

    The system message embeds the same ``_WORKSPACE_STATE_GUIDANCE``
    block used by ``build_assistant_text_prompt``; the two registry
    entries must stay in lockstep so the streaming variant doesn't drift
    from the JSON variant.
    """
    from backend.prompt_registry import get_prompt

    template = get_prompt("assistant")
    # Slice 1J: history used to be hard-sliced at history[-4:], which
    # cratered mid-session memory the moment a conversation passed 4
    # turns. Now we budget by chars (drop-oldest-first, same shape as
    # _slice_history_for_budget for the resume builder) so the model
    # gets as much continuity as the prompt budget allows.
    history_payload = _slice_history_for_budget(
        list(history or []),
        max_chars=ASSISTANT_HISTORY_CHAR_BUDGET,
    )
    user_prompt = "\n\n".join(
        [
            _json_block("Assistant Context", assistant_context),
            _json_block("User Question", {"question": question}),
        ]
        + ([_json_block("Recent History", history_payload)] if history_payload else [])
    )
    expected_keys = _strict_expected_keys(template)
    return {
        "system": template.system,
        "user": user_prompt,
        "expected_keys": expected_keys,
    }


def build_assistant_text_prompt(
    assistant_context: Dict[str, Any],
    question: str,
    history: Any = None,
) -> Dict[str, Any]:
    """Plain-prose variant of ``build_assistant_prompt`` for the SSE
    streaming endpoint.

    Same context, same grounding rules, but instructs the model to
    return prose only (no JSON contract) so the response can be
    streamed token-by-token. Sources and follow-up suggestions are
    computed deterministically from the workspace snapshot in the
    streaming caller (see ``stream_workspace_question``).

    Migrated to the prompt registry: ``system`` is loaded from
    ``prompts/assistant_text/v1.json``. The user prompt is composed in
    Python because it is dynamic per turn. There is no ``expected_keys``
    on the return value — the streaming caller handles prose chunks
    directly without a JSON contract.
    """
    from backend.prompt_registry import get_prompt

    template = get_prompt("assistant_text")
    # Slice 1J: mirror the JSON-variant fix — drop the hard
    # history[-4:] slice in favour of the char-budget slider so
    # streaming chat keeps multi-turn memory.
    history_payload = _slice_history_for_budget(
        list(history or []),
        max_chars=ASSISTANT_HISTORY_CHAR_BUDGET,
    )
    user_prompt = "\n\n".join(
        [
            _json_block("Assistant Context", assistant_context),
            _json_block("User Question", {"question": question}),
        ]
        + ([_json_block("Recent History", history_payload)] if history_payload else [])
    )
    return {
        "system": template.system,
        "user": user_prompt,
    }


def build_assistant_followup_prompt(
    question: str,
    *,
    assistant_scope: str = "assistant",
    state_updates: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    """Follow-up turn prompt for the in-app assistant.

    Migrated to the prompt registry: ``system`` is loaded from
    ``prompts/assistant_followup/v1.json`` with a single ``{scope}``
    placeholder that is filled here via ``str.format(scope=...)``.
    Pattern B (placeholder substitution) — the rest of the system text
    is fully static. ``expected_keys`` comes from the registry metadata.
    """
    from backend.prompt_registry import get_prompt

    template = get_prompt("assistant_followup")
    # The template ships exactly one ``{scope}`` placeholder; format()
    # would raise KeyError if the registry author added another curly
    # token without supplying it here. We rely on the registry round-
    # trip tests to catch a stray ``{`` rather than escape defensively.
    rendered_system = template.system.format(scope=assistant_scope)
    user_sections = [
        _json_block("User Question", {"question": question}),
    ]
    if state_updates:
        user_sections.append(_json_block("State Updates", state_updates))
    expected_keys = _strict_expected_keys(template)
    return {
        "system": rendered_system,
        "user": "\n\n".join(user_sections),
        "expected_keys": expected_keys,
    }


# Resume-builder field schema. The list of fields here drives
# ``resume_builder_missing_fields`` (which the user prompt embeds as a
# JSON block per turn), and the description text is also pre-rendered
# into ``prompts/resume_builder/v1.json`` as the field-list block in the
# system message. Both consumers must stay in sync: a tests/test_prompts
# guard asserts the registry-loaded system matches the value computed
# from this constant byte-for-byte, so a drifted edit lights up before
# rollout.
_RESUME_BUILDER_FIELD_DESCRIPTIONS = {
    "full_name": (
        "candidate's full name as they typed it — capture EVERY name "
        "token (first, middle, last, suffix). Don't drop a surname just "
        "because the user packed location or contact info onto the same "
        "line ('Priya Sharma, Bangalore. priya@gmail.com' → "
        "full_name='Priya Sharma', NOT 'Priya')."
    ),
    "location": "city / region / 'Remote'",
    "contact_lines": "list of contact entries: emails, phones, links",
    "target_role": "the SHORT role title the candidate is targeting",
    "professional_summary": (
        "1-3 sentence headline of the candidate's professional identity. "
        "Self-descriptions like 'Senior backend engineer with 5 years on "
        "distributed Python systems' belong here — NOT in experience_notes. "
        "Capture even when the user phrases it in first person; downstream "
        "rendering rephrases to third-person ATS voice."
    ),
    "experience_notes": (
        "Specific past roles only — company names, titles, date ranges, "
        "impact bullets. Do NOT put broad self-descriptions or summary-style "
        "language here; that goes in professional_summary."
    ),
    "education_notes": "degrees, institutions, dates",
    "skills": "list of tools / technologies / strengths",
    "certifications": "optional list of credentials / specializations",
    "projects_notes": (
        "OPTIONAL — side projects, open-source work, or portfolio pieces "
        "the candidate wants on the resume. Capture verbatim user prose "
        "(name, link, what it does, tech used, outcomes). Skip this field "
        "for candidates without a tech-heavy background or no projects to "
        "share — never push for one if they don't mention any."
    ),
    "publications": (
        "OPTIONAL — academic publications, papers, or conference talks. "
        "List of citation strings. Skip this field unless the candidate "
        "explicitly mentions a paper / publication / talk."
    ),
}


# Fields that DON'T block "ready" status when empty. The LLM intake
# prompt knows to skip these unless the user volunteers them — pushing
# every candidate to invent projects or publications would be annoying.
_RESUME_BUILDER_OPTIONAL_FIELDS = {
    "certifications",
    "projects_notes",
    "publications",
}


def resume_builder_missing_fields(draft: Dict[str, Any]) -> list[str]:
    """Return the list of REQUIRED resume-builder fields that are still empty.

    Used by the LLM intake prompt so the model can pick the next gap to
    ask about without having to re-derive it. Public helper so the
    service layer and tests can compute it consistently. Optional
    fields (certifications, projects, publications) are excluded —
    they're only asked when the user volunteers them.
    """
    missing: list[str] = []
    for key in _RESUME_BUILDER_FIELD_DESCRIPTIONS:
        if key in _RESUME_BUILDER_OPTIONAL_FIELDS:
            continue
        value = draft.get(key) if isinstance(draft, dict) else None
        if value is None:
            missing.append(key)
            continue
        if isinstance(value, str) and not value.strip():
            missing.append(key)
            continue
        if isinstance(value, list) and not value:
            missing.append(key)
            continue
    return missing


def build_resume_builder_prompt(
    *,
    draft: Dict[str, Any],
    history: Any = None,
    user_message: str,
    pending_followups: Any = None,
) -> Dict[str, Any]:
    """LLM intake prompt for the conversational resume builder.

    The model receives the current draft (truth source), a list of
    fields that are still empty (so it doesn't have to re-derive),
    recent conversation turns (for narrative continuity / backtracking),
    and the latest user message. It returns a partial draft update + a
    natural conversational reply + a status flag.

    Rendering the resume itself is not the model's job — the dataclass
    is templated to markdown by `_build_resume_markdown` after the
    draft is captured.

    Migrated to the prompt registry: ``system`` and ``expected_keys``
    are loaded from ``prompts/resume_builder/v1.json``. Pattern A: the
    field-descriptions block previously rendered from the module-level
    ``_RESUME_BUILDER_FIELD_DESCRIPTIONS`` constant is now pre-baked
    into the JSON. The constant still drives ``resume_builder_missing_fields``,
    so any field-name or description edit MUST be mirrored in both
    places to keep the user-prompt fields and the system-prompt
    instructions in sync.
    """
    from backend.prompt_registry import get_prompt

    template = get_prompt("resume_builder")
    missing = resume_builder_missing_fields(draft)
    # Slice 1B: drop the hard `[-12:]` truncation in favor of a
    # character-budget guard. The full conversation_history (capped
    # in-memory at ~200 entries by the service) is included as long as
    # it fits under RESUME_BUILDER_HISTORY_CHAR_BUDGET; when it
    # doesn't, the OLDEST entries are dropped (sliding window) until
    # it does. Earlier turns are summarized by the structured `draft`
    # state, so dropping them is graceful — the agent still sees the
    # accumulated facts, just not the verbatim back-and-forth.
    history_payload = _slice_history_for_budget(
        list(history or []),
        max_chars=RESUME_BUILDER_HISTORY_CHAR_BUDGET,
    )
    # Slice 1E: thread the agent's outstanding follow-up commitments
    # back into its prompt context every turn. The model uses this
    # block to decide whether to surface a pending item now — either
    # by addressing it in assistant_message or by firing a
    # proactive_offer that nudges the user to resolve it.
    pending_followups_payload = [
        str(item).strip()
        for item in (pending_followups or [])
        if str(item or "").strip()
    ]

    user_prompt = "\n\n".join(
        [
            _json_block("Current Draft", draft),
            _json_block("Missing Fields", missing),
            _json_block("Outstanding Follow-ups", pending_followups_payload),
            _json_block("Recent Conversation", history_payload),
            _json_block("Latest User Message", {"message": user_message}),
        ]
    )

    expected_keys = _strict_expected_keys(template)
    return {
        "system": template.system,
        "user": user_prompt,
        "expected_keys": expected_keys,
    }


def build_resume_builder_structuring_prompt(
    *,
    draft: Dict[str, Any],
) -> Dict[str, Any]:
    """LLM structuring pass for the resume builder draft.

    The conversational intake captures `experience_notes` and
    `education_notes` as free-form prose (verbatim user words). At
    generate / export time we ask the model to convert those strings
    into a list of structured role / degree objects so the resume
    renderer can produce one card per role and one row per degree.

    The model also gets license to LIGHTLY rewrite bullets into ATS
    voice and infer obvious missing pieces (e.g., the second role's
    title when the user wrote "prior at FinStart"). It must NOT
    fabricate companies, schools, dates, or skills the user did not
    mention. Voice rewrite only — facts stay the user's.

    Returns are merged into a CandidateProfile downstream. On any
    failure (LLM unavailable, JSON malformed, schema mismatch) the
    caller falls back to the deterministic regex parsers, so this
    prompt is best-effort enrichment, not a hard dependency.

    Migrated to the prompt registry: ``system`` and ``expected_keys``
    are loaded from ``prompts/resume_builder_structuring/v1.json``.
    Pattern A (pure static): the intro, rules block, and rendered
    contract are pre-baked into the JSON file.
    """
    from backend.prompt_registry import get_prompt

    template = get_prompt("resume_builder_structuring")
    user_prompt = "\n\n".join(
        [
            _json_block(
                "Draft Snapshot",
                {
                    "full_name": draft.get("full_name") or "",
                    "target_role": draft.get("target_role") or "",
                    "professional_summary": draft.get("professional_summary") or "",
                    "skills": draft.get("skills") or [],
                },
            ),
            _json_block(
                "Experience Notes (user prose, verbatim)",
                {"text": draft.get("experience_notes") or ""},
            ),
            _json_block(
                "Education Notes (user prose, verbatim)",
                {"text": draft.get("education_notes") or ""},
            ),
            _json_block(
                "Projects Notes (user prose, verbatim)",
                {"text": draft.get("projects_notes") or ""},
            ),
        ]
    )

    expected_keys = _strict_expected_keys(template)
    return {
        "system": template.system,
        "user": user_prompt,
        "expected_keys": expected_keys,
    }


def build_product_help_assistant_prompt(
    app_context: Dict[str, Any],
    question: str,
    history: Any = None,
) -> Dict[str, Any]:
    """Product-help variant of the in-app assistant.

    Transitively migrated: this wrapper delegates to ``build_assistant_prompt``
    so it inherits the registry-loaded ``prompts/assistant/v1.json`` system
    message automatically. There is no separate prompt file because the
    only difference from the unified assistant is the shape of the user-
    facing assistant_context dict (``assistant_scope='product_help'`` and
    nesting the caller-supplied ``app_context`` under ``product_context``).
    """
    return build_assistant_prompt(
        {
            "assistant_scope": "product_help",
            "product_context": app_context,
        },
        question,
        history=history,
    )


def build_application_qa_assistant_prompt(
    workflow_context: Dict[str, Any],
    question: str,
    history: Any = None,
) -> Dict[str, Any]:
    """Application-Q&A variant of the in-app assistant.

    Transitively migrated: this wrapper delegates to ``build_assistant_prompt``
    so it inherits the registry-loaded ``prompts/assistant/v1.json`` system
    message automatically. The only call-site difference is the shape of the
    user-facing assistant_context dict (``assistant_scope='application_qa'``
    and surfacing the caller-supplied ``workflow_context``).
    """
    return build_assistant_prompt(
        {
            "assistant_scope": "application_qa",
            "workflow_context": workflow_context,
        },
        question,
        history=history,
    )
