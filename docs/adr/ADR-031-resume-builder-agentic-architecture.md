# ADR-031: Résumé-builder agentic architecture (tool-calling loop, promise tracking, silent-fallback discipline)

- Status: Accepted (Slices 1A-1F shipped 2026-05-20 through 2026-05-21; eval expansion to 15-20 fixtures + Phase 3 features parked in `report.md`)
- Date: 2026-05-21

## Context

The résumé-builder intake was a deterministic five-step form-filler dressed
up as a chatbot. The operator's complaint, after QA-ing it with their own
résumé, surfaced three concrete failures:

1. **Hallucinated capabilities.** When the user asked "if I give you the
   GitHub links of my projects, can you extract the skills yourself?", the
   agent said "Yes — if you share the GitHub project links, I can extract
   the skills and tools from them." It then captured the URLs verbatim into
   `projects_notes` with no actual fetch — because there was no tool
   wired. The agent was confidently lying about a capability it didn't
   have.
2. **No multi-turn memory.** The intake LLM was fed the recent 12 history
   entries via a `history[-12:]` slice in `build_resume_builder_prompt`.
   For sessions longer than 6 user/assistant pairs the model "forgot"
   earlier corrections (e.g. the user gave education across 3 turns,
   correcting each previous turn — the structuring pass saw a garbled
   stream-of-consciousness). The user described the effect plainly: "is
   each new question going to a fresh GPT instance?"
3. **No proactive behavior, no promise tracking.** The agent only answered
   questions; it never volunteered ("you've shared enough about your
   projects — want me to draft a professional summary from them?"). It
   also forgot its own commitments: when the user said "we can do the
   summary later based on the projects", the agent acknowledged it and
   then never circled back.

The user's stated goal: *"i want it to be intelligent like talking to
Claude in this chat — multi-turn context, can fetch URLs / browse the
web when useful, holds promises across turns, proactively infers when
it has enough signal."*

There were two architectural questions to answer before building:

- **Native Responses-API tool calling vs LangGraph / LangChain.** The
  codebase is Responses-API-native (62 references, zero
  `chat.completions`, per the ADR-028 audit). LangGraph would add a
  heavy LangChain dependency tree, a new abstraction layer over what the
  Responses API already provides natively, friction with the structured-
  outputs + fidelity-runner + eval discipline we already have, and a
  new mental model for zero clear value-add at this scope. Native
  Responses-API tool calling wins on every axis except multi-provider
  unification — which is parked for ADR-028 D1 anyway.
- **Where does the loop live?** A generic "agentic loop" in
  `OpenAIService` (reusable) or inline in the résumé-builder service
  (scoped)? The instinct was generic; the reality is the loop has
  cross-cutting concerns (budget enforcement, cost tracing, usage
  recording) that already live in `OpenAIService`. A new method on the
  service keeps everything in one place.

## Decision

A native Responses-API **tool-calling agentic loop** on `OpenAIService`
(`run_tool_loop`) drives the résumé-builder intake. Tools are exposed
as **function tools** the model emits via `function_call` items; the
service dispatches via a small registry and feeds results back as
`function_call_output` items on the next iteration. The loop iterates
up to a small cap (12) and then returns the final JSON envelope as
parsed Pydantic / dict. All four properties the operator asked for fall
out of this base + a few prompt-channel additions:

### Supporting decisions

1. **`run_tool_loop` lives on `OpenAIService`.** Mirrors `run_json_prompt`
   on every dimension (instructions / user prompt / expected keys /
   cost-trace contract / iteration budget) but loops on `function_call`
   items. Each iteration:
   - Calls `responses.create(input=input_items, tools=tools,
     tool_choice="auto", text={format: {type: json_object}})`.
   - If response contains `function_call` items: echoes them into
     `input_items` (so the next call sees them), executes via the
     passed-in `tool_executor`, appends `function_call_output` items,
     loops.
   - Otherwise: extracts the final JSON text, parses, returns
     `(payload, tool_trace)` where `tool_trace` is a list of
     `{name, arguments, output}` dicts the caller can persist into
     conversation history.
   - Each iteration calls `_enforce_budget()` + `_track_usage_from_response()`
     so a runaway loop trips the budget guard rather than silently
     burning credits.
   - On iteration-cap exhaustion: raises `AgentExecutionError` so the
     service can fall back gracefully.

   Cap = **12 iterations**. Initially 5 — but the QA replay caught a
   real failure: when the user pasted 6 GitHub URLs in one turn and the
   model serialised the fetches (one per loop iteration instead of in
   parallel), iteration 5 hit the cap, the loop raised, the regex
   step-machine fallback ran, and the projects ended up dumped into
   `experience_notes`. Bumped to 12 (10 sequential fetches + 2 for the
   final answer). Above ~12 is a runaway-loop signal.

2. **Tool registry in `backend/services/resume_builder_tools.py`.**
   Two function tools currently registered:

   - **`fetch_github_readme(url)`** — HTTPS-only, github.com hostname
     allowlist, raw.githubusercontent.com `/HEAD/README.md` (so default
     branch resolves regardless of main/master), 6s timeout, 200 KB cap,
     content-type gate (text/markdown or text/plain), stable error
     codes (`invalid_url` / `timeout` / `network_error` / `http_status`
     / `wrong_content_type` / `oversize` / `empty_body` /
     `decode_error`). Returns errors as JSON envelopes, never raises
     across the tool boundary.

   - **`web_search(query)`** — sidesteps a non-obvious OpenAI
     incompatibility (see decision §3 below). Function-wrapped: the
     dispatcher fires its own inner `responses.create` (gpt-5.4-mini,
     no `json_object` format, with OpenAI's built-in
     `{"type": "web_search"}` server-side tool enabled) and returns
     the synthesized text as the function_call_output. Capped at 8 KB.

   Both tools are documented in the intake prompt with explicit WHEN-
   TO-USE and WHEN-NOT-TO-USE rules. "Use sparingly" is the operating
   discipline — `web_search` is expensive (one extra API call per
   invocation, +1-2s latency) and the prompt explicitly nudges the
   agent to refuse speculative or already-answered queries.

3. **`web_search` is wrapped as a function tool, NOT exposed as
   `{"type": "web_search"}` directly.** This is the most non-obvious
   architectural decision in the entire slice and the rationale is
   important enough to preserve:

   - OpenAI's API rejects the combination of
     `tools=[{"type": "web_search"}]` and
     `text.format={"type": "json_object"}` with:
     `400 - "Web Search cannot be used with JSON mode."`
   - The résumé-builder intake contract REQUIRES `json_object`
     (`draft_updates` / `assistant_message` / `status` / `focus_field`
     / `proactive_offer` / `add_followups` / `resolved_followups`).
     Removing JSON mode would degrade parse rates and force ad-hoc
     parsing.
   - The first naive attempt — adding `{"type": "web_search"}` to the
     tool list — silently 400'd every intake turn. The service caught
     the exception (broad `except` clause) and fell back to the regex
     step-machine. The agentic eval (Slice 1D — see §4) immediately
     surfaced the regression: 3/10 scenarios passing instead of 7/10.
   - **The function-wrap is the fix.** The agent calls
     `web_search(query)` like any other function tool. The dispatcher
     makes a separate internal `responses.create` call — no
     `json_object`, with the built-in web_search tool enabled — and
     returns the synthesized text as the function_call_output. Main
     loop stays JSON-mode-safe; the agent gets a research capability
     on-demand.
   - Cost shape: each `web_search` invocation is ONE extra
     `responses.create` call. Realistic usage per session: 0-2
     invocations. Latency: +1-2s when fired.
   - Search execution itself runs on OpenAI infrastructure (US-hosted).
     The EU-data-residency posture from `docs/competitive-landscape.md`
     applies to user data we store, not outbound research queries — so
     this is acceptable for v1. Revisit when ADR-028 D1 multi-provider
     eval lands and a concrete EU alternative is benchmarked.

4. **Schema-strictness pact-tests are MANDATORY.** Mid-session a
   different silent-fallback bug surfaced:
   `ResumeBuilderStructuringOutput.skill_categories` was typed as
   `dict[str, list[str]]`. Pydantic v2 emits this as
   `{"type": "object", "additionalProperties": <schema>}`. OpenAI's
   strict mode rejects this shape when the field is in `required` with:
   `400 - "Extra required key 'skill_categories' supplied."` The
   structuring call had been failing on every export since the schema
   landed; the regex fallback was producing the visible output
   (empty bullets, `Link: <first tech word>`, single-paragraph
   projects). Weeks of degraded quality, no error in any log.

   Fix: refactored `skill_categories` to
   `list[ResumeBuilderStructuringSkillBucket]` (label/skills pairs).
   List-of-typed-objects is OpenAI-strict-mode-friendly; arbitrary-key
   dicts are not. Boundary conversion in `_sanitize_skill_categories`
   keeps downstream consumers (the artifact renderer) on the original
   `dict[str, list[str]]` shape — no propagating breakage.

   To prevent this class of bug from coming back in a new place:
   `tests/backend/test_llm_schema_strictness.py` walks the JSON Schema
   produced by `_build_response_format_schema` for **every** Pydantic
   model wired to `run_structured_prompt` in production (currently 9
   models) and asserts:
   - No node has `additionalProperties` set to a schema dict (the
     `dict[K, V]` trap).
   - No node has `anyOf` with more than one non-null branch (the
     multi-type-union trap).

   These are STATIC — no API calls — so they run on every CI build
   (~1.5s). If anyone introduces a new `dict[K, V]` field or
   multi-branch union in any production schema, this fails at CI before
   the change can ship and start silently 400-erroring in production.

5. **Two parallel registries that should match must be pact-tested.**
   The same silent-fallback pattern recurred in a different place
   during the same session: `src/exporters._THEME_SPECS` and
   `SUPPORTED_THEMES` listed all 6 themes, but
   `src/resume_builder.RESUME_THEMES` listed only 2 (the original
   `classic_ats` + `professional_neutral`). `_resolve_resume_theme`
   silently substituted `classic_ats` for any other theme. Result:
   `modern_blue.pdf` and `classic_ats.pdf` had identical MD5 hashes
   for ~4 weeks across the workspace export flow, the resume-builder
   export, and the persistence pipeline.

   Fix: `RESUME_THEMES` now lists all 6 themes; two pact-tests
   (`test_resume_themes_registry_matches_supported_themes` +
   `test_resolve_resume_theme_round_trips_every_supported_theme`)
   lock the two registries together so the same drift cannot recur.

   **Generalised lesson:** any two configs that should match
   (registries, schemas, allowlists) need a pact-test. The silent-
   fallback antipattern is the most expensive class of bug we saw in
   this session — both bugs lived for weeks because nothing failed
   loudly. Adding a pact-test is half a day; the bug it prevents costs
   weeks of degraded quality.

6. **History budget is character-based, not turn-based.** Previously
   `build_resume_builder_prompt` hard-sliced
   `history_payload = list(history or [])[-12:]`. That's a fixed
   12-entry cap regardless of how dense or sparse those entries are.
   Replaced with `_slice_history_for_budget(history, max_chars=30000)`:
   walks newest-first, accumulates serialized entries until adding the
   next would exceed budget. Returns the most-recent suffix in
   chronological order. ALWAYS keeps at least the newest entry so an
   over-budget tail doesn't break the chat.

   The in-memory cap (in `_run_llm_turn` after the assistant turn lands)
   was bumped from 48 to 200 entries — the prompt-time char budget is
   what actually defends the per-turn token budget; the entry cap is a
   long-session memory safety valve so pathological sessions don't
   grow unboundedly in process memory.

7. **`proactive_offer` is a new JSON channel — not just a wrapped
   `assistant_message`.** When the model has enough signal to draft
   something useful (summary, skill grouping, bullet expansion), it
   sets `proactive_offer` to a click-to-accept CTA string ("Draft my
   professional summary from what we have so far"). The frontend
   renders this as a pill below the assistant reply; clicking the pill
   submits the offer text as the next user turn (bypassing the
   textarea state via an `overrideText` parameter on
   `handleResumeBuilderAnswer` — avoids the React setState async window
   where a Continue click could fire before the prefilled value
   commits). One offer per turn, max. Null when there's no clear-
   enough signal yet, or when the agent is still collecting a specific
   field.

   Prompt gives concrete GOOD vs BAD examples ("Draft my professional
   summary" vs "Help me with my resume"). 200-char cap at the backend
   boundary against runaway-length offers.

8. **`pending_followups: list[str]` tracks deferred commitments.**
   New session field. The intake prompt is fed the current outstanding
   set via an `Outstanding Follow-ups` block; the model returns two
   new channels each turn:
   - `add_followups: list[str]` — new commitments captured this turn
   - `resolved_followups: list[str]` — items addressed this turn

   Service applies resolutions FIRST (substring + case-insensitive
   match — the LLM sometimes paraphrases the original wording), then
   adds new commitments (dedupe by case-insensitive equality), then
   caps at 12 outstanding items.

   The TRIGGER PRIORITY rule in the prompt is what made the behavior
   reliable: when the user asks an open-ended question
   (`"what else?"` / `"what's next?"` / `"anything missing?"`),
   surface the OLDEST outstanding follow-up before asking for a new
   field. Without this rule, GPT-5.4@medium preferred to ask new
   collection questions; the conversational eval flagged it on the
   first calibrated run.

## Trade-offs (explicit non-decisions)

- **LangGraph is NOT used.** Adds heavy LangChain deps + new
  abstraction layer + friction with existing structured outputs +
  eval discipline. Native Responses-API tool calling does everything
  this scope needs.
- **External web search providers (Tavily / Brave / Exa) are NOT
  integrated.** OpenAI's built-in via the function-wrap costs zero
  new dependencies and is "good enough" for v1. External providers
  would add an env var + API key + cost commitment + EU-residency
  story. Parked until a clear quality or compliance gap forces the
  decision.
- **`pending_followups` has no UI surface in v1.** The agent's
  natural `assistant_message` and `proactive_offer` behaviour are
  enough to demo the feature. `_serialize_session` does emit the list
  in the response payload so the frontend can opt in to a small
  "outstanding items" panel later.
- **Conversational eval is 10 fixtures, not the 15-20 the parked
  plan calls for.** Diminishing returns per added fixture; the 10
  cover the highest-value behaviors (tool fires, honest abstention,
  proactive offers, promise tracking, structured-payload canary).
  Eval expansion parked.

## Verification

- 145+ hermetic tests across affected suites (test_prompts /
  test_resume_builder / test_resume_builder_tools /
  test_llm_schema_strictness / test_structured_outputs /
  test_prompt_registry / test_cost_tracking) all green.
- 10/10 LLM scenarios pass on the live API (gpt-5.4) in the agentic
  runner (`tests/quality/resume_builder_agentic_runner.py`).
- The user's original 10-turn QA transcript replays cleanly through
  the post-1F agent: tool fires on the 6 GitHub URLs, projects are
  captured with real tech stacks + outcomes from the READMEs, the
  proactive_offer chip shows up at the right moment, the rendered
  PDF in all 3 user-tested themes (professional_neutral, classic_ats,
  modern_blue) produces 3 distinct visually-correct outputs.
- The two silent-fallback bugs caught this session both have
  regression tests (`test_llm_schema_strictness` for the schema 400,
  `test_resume_themes_registry_matches_supported_themes` for the
  registry drift). The bug class cannot recur silently in either
  place without failing at CI time.

## Follow-ups (Phase 2 remainder + Phase 3)

- **Eval expansion to 15-20 fixtures** with rubric scoring (parked,
  `report.md` Phase 2). The current 10 cover the high-value behaviors
  but additional coverage on edge cases (international names, very
  long sessions, conflicting multi-turn corrections, multi-language
  prose) would catch more.
- **External web-search provider integration** (parked). Evaluate
  Tavily vs Brave vs Exa once a quality gap surfaces or a compliance
  reason forces the move. Architecture is already set up to drop in:
  swap `_web_search`'s inner call for an HTTPS provider request, keep
  the function-tool spec identical.
- **`pending_followups` UI surface** (parked). A small "open items"
  panel in the resume-builder side panel would make the feature
  visible to users. Data already flows through the API response;
  only frontend work needed.
- **Multi-provider agentic eval** (ADR-028 D1, parked). If/when a
  non-OpenAI provider's adapter lands, the agentic eval should run
  against both to compare tool-use discipline.
