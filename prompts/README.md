# Prompt registry

Versioned LLM prompts loaded by `backend/prompt_registry.py`. Each `<name>/v<N>.json` carries:

- `version` — string id matching the filename (`"v1"`).
- `owner` — agent or service that owns the prompt.
- `schema_ref` — Pydantic output model the response is validated against (in `src/schemas_llm_outputs.py`).
- `system` — full system message, including pre-rendered `Return JSON only with exactly these keys: ...` contract.
- `metadata.expected_keys` — array of top-level JSON keys the LLM must return.

`registry.json` maps each `<name>` to its active version so callers can use `get_prompt(name)` without pinning a version.

## Migrated agents (loaded from registry)

| Agent | File | Notes |
|---|---|---|
| Tailoring | `tailoring/v1.json` | Initial migration |
| Review | `review/v1.json` | Migration round 2 |
| Resume Generation | `resume_generation/v1.json` | Migration round 2 |
| Cover Letter | `cover_letter/v1.json` | Migration round 2 |

## Deferred (still inlined in `src/prompts.py`)

The six remaining builders have **dynamic system content** that needs template-level placeholder support before migration:

| Builder | Dynamic bit |
|---|---|
| `build_assistant_prompt` | `_WORKSPACE_STATE_GUIDANCE` module constant interpolated into system |
| `build_assistant_text_prompt` | Same as above; SSE-streaming variant returning prose instead of JSON |
| `build_assistant_followup_prompt` | `Current assistant scope: {scope}.` interpolated into system |
| `build_resume_builder_prompt` | Field descriptions + missing-fields list rendered into system |
| `build_resume_builder_structuring_prompt` | Similar — structured resume-builder intake |
| `build_product_help_assistant_prompt` | Product knowledge hits interpolated |
| `build_application_qa_assistant_prompt` | Workspace snapshot interpolated |

**Migration path** when these come back to top of mind:

1. Decide the placeholder shape: Jinja `{{name}}` for caller-supplied values, or pre-bake into multiple static `vN` files per scope. The former wins when 2+ callers share the prompt with different parameter values; the latter wins when there's exactly one canonical value.
2. The registry's existing `PromptTemplate.render(**kwargs)` substitutes both system AND user. The assistant builders compose their user prompt in Python (not Jinja), so we'd want a `render_system_only(**kwargs)` helper or pre-render the system to a string-format Python template.
3. Each migration follows the same 4-step pattern documented in commit history:
   - Write `prompts/<name>/v1.json` with the static system + metadata.expected_keys.
   - Add `<name>: v1` to `registry.json`.
   - Replace the inlined system + contract in `src/prompts.py` with a `get_prompt(<name>)` load.
   - Re-run `pytest tests/` to confirm no regressions.

The four currently-migrated agents cover the full production resume-application workflow: tailoring → review → resume generation → cover letter. The deferred six are assistant/help/intake surfaces — important but lower-traffic.
