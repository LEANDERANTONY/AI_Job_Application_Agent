# Prompt registry

Versioned LLM prompts loaded by `backend/prompt_registry.py`. Each `<name>/v<N>.json` carries:

- `version` — string id matching the filename (`"v1"`).
- `owner` — agent or service that owns the prompt.
- `schema_ref` — Pydantic output model the response is validated against (in `src/schemas_llm_outputs.py`). For prompts without a strict Pydantic schema (the assistant variants), this is a descriptive placeholder name so the registry-author-cross-check log message stays useful.
- `system` — full system message, including pre-rendered `Return JSON only with exactly these keys: ...` contract.
- `metadata.expected_keys` — array of top-level JSON keys the LLM must return. Omitted for prose-only streaming prompts.

`registry.json` maps each `<name>` to its active version so callers can use `get_prompt(name)` without pinning a version.

## Migrated agents (loaded from registry)

| Agent | File | Pattern | Notes |
|---|---|---|---|
| Tailoring | `tailoring/v1.json` | A (static) | Initial migration |
| Review | `review/v1.json` | A (static) | Migration round 2 |
| Resume Generation | `resume_generation/v1.json` | A (static) | Migration round 2 |
| Cover Letter | `cover_letter/v1.json` | A (static) | Migration round 2 |
| Assistant (JSON) | `assistant/v1.json` | A (static) | Batch 2 — intro + `_WORKSPACE_STATE_GUIDANCE` + contract pre-baked. Shared `_WORKSPACE_STATE_GUIDANCE` content also lives in `assistant_text/v1.json`; edit both in lockstep. |
| Assistant (prose / SSE) | `assistant_text/v1.json` | A (static) | Batch 2 — same intro and workspace guidance as `assistant`; no JSON contract, no `expected_keys`. |
| Assistant follow-up | `assistant_followup/v1.json` | B (`{scope}` placeholder) | Batch 2 — `template.system.format(scope=assistant_scope)` substitutes the only placeholder; rest of the system text is fully static. |
| Resume Builder (intake) | `resume_builder/v1.json` | A (static) | Batch 2 — field-list block derived from `_RESUME_BUILDER_FIELD_DESCRIPTIONS` is pre-baked. The Python constant still drives `resume_builder_missing_fields`; keep them aligned. Literal `{name}` tokens in the resume-shape example are plain text, never call `.format()` on this string. |
| Resume Builder (structuring) | `resume_builder_structuring/v1.json` | A (static) | Batch 2 — intro, rules block, and rendered contract pre-baked. Best-effort enrichment; callers fall back to regex parsers on failure. |

### Transitively migrated wrappers

`build_product_help_assistant_prompt` and `build_application_qa_assistant_prompt` are thin wrappers around `build_assistant_prompt`: they shape the `assistant_context` dict differently but share the system message. They inherit `prompts/assistant/v1.json` via the delegation — there is intentionally no separate prompt file for them.

## Migration patterns

- **Pattern A — pure static.** The dynamic content is a module-level constant or rendered helper result that does not vary at runtime. Inline it into the v1.json `system` string. The Python builder loads `template.system` directly. All but one of the migrated agents use this pattern.
- **Pattern B — `{name}` placeholder.** The dynamic content is a per-call value (currently only `assistant_followup`'s `{scope}`). Put `{name}` in the JSON `system`; the builder runs `template.system.format(name=value)`. Keep the placeholder count to ONE per template so the format call is unambiguous, and ensure no other `{` characters appear in the system body (literal curly braces in instructional text must be escaped as `{{`).

`PromptTemplate` does not ship a render helper — the `.format()` approach is intentionally lightweight and keeps the registry contract a plain string. If we add a second placeholder template, factor a small helper before duplicating the call.

## Migration recipe

1. Decide pattern A vs B per the criteria above.
2. Write `prompts/<name>/v1.json` carrying the full pre-rendered system + `metadata.expected_keys`. Schema files are byte-sensitive: a single missing space changes the contract sent to the LLM.
3. Add `<name>: v1` to `registry.json`.
4. Replace the inlined system + contract in `src/prompts.py` with a `get_prompt(<name>)` load, keeping the user-prompt-building logic intact.
5. Add a byte-identity guard test in `tests/test_prompts.py` that recomputes the original Python concat from the still-available helpers (`_WORKSPACE_STATE_GUIDANCE`, `_RESUME_BUILDER_FIELD_DESCRIPTIONS`, `_build_contract`) and asserts equality against the registry-loaded system. This catches a stray space or `\n` mismatch immediately.
6. Re-run `pytest tests/` to confirm no regressions.
