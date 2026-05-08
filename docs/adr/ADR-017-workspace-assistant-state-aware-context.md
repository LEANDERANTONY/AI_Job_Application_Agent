# ADR-017: Workspace Assistant — Ungated and State-Aware Context

- Status: Accepted
- Date: 2026-05-08

## Context

The workspace assistant chat (the floating FAB at the bottom-right of the workspace) used to be **locked until the first analysis run had completed**. The reasoning at the time was reasonable: the assistant grounds answers in the workspace package, so without a workspace there's "nothing to ground in" and the answers would be generic.

In practice this had two failure modes:

1. **Most user questions are product-help, not application Q&A.** Users opened the chat to ask "how do I use this?", "where do I upload my resume?", "what's step 03 for?" — questions the assistant could answer well even without a workspace, because the backend's `AssistantService.answer_product_help` path is designed for exactly that case. The lock pushed those questions out of the app entirely.
2. **The assistant was blind to pre-analysis state even when a user did have data.** The only context payload was `workspace_snapshot` — which the frontend set to `analysisState` — and that stayed `null` until an analysis ran. Even when the user had a parsed resume, a parsed JD, or a search history, the assistant didn't see any of it. So when a user asked "what should I do next?" with a parsed resume but no JD, the answer was generic boilerplate instead of "paste a JD and run analysis."

We wanted the assistant available from the very first visit AND aware of the live workspace state, with the latter being the bigger win.

## Decision

Ungate the assistant chat and thread a compact projection of the live workspace state through every query.

### Ungating

Three lockup surfaces removed in one pass:

- The `requiresWorkspaceRun` boolean that swapped the panel's footer form for a "Assistant unlocks after your first workspace run" block.
- An early-return guard inside `WorkspaceShell.submitAssistantQuestion` that surfaced a "Run the AI analysis first…" warning notice instead of submitting.
- An `assistantUnlocked` prop on the command palette that hid recent-question history.

The remaining `requiresWorkspaceRun` prop became cosmetic-only and was renamed to `hasWorkspaceContext` to reflect what it actually drives now: contextual copy in the panel header sub-line, the empty state, and the textarea placeholder.

### State context payload

Every assistant query now includes a `workspace_state` object alongside the existing `workspace_snapshot`:

```ts
type WorkspaceStateContext = {
  current_step: "resume" | "jobs" | "jd" | "analysis";
  has_resume: boolean;
  resume_summary: { name; location; skills_count; experience_entries_count; has_certifications } | null;
  has_jd: boolean;
  jd_summary: { title; location; hard_skills_count; soft_skills_count; must_haves_count } | null;
  has_analysis: boolean;
  saved_jobs_count: number;
  last_search_query: string | null;
};
```

Counts and identity only, no raw resume text or JD body. Built directly from existing React state in `submitAssistantQuestion` — no new server-side store, no extra round-trip. Backend's `WorkspaceStateContextModel` (extra="forbid") validates the shape; the workspace service folds it into the `app_context` dict that reaches `AssistantService`, where the existing `**(app_context or {})` spread surfaces it inside the prompt's JSON-blocked `product_context`.

The `workspace_snapshot` field stays as-is for full-fidelity application Q&A once an analysis has run; `workspace_state` covers the pre-analysis gap.

### System-prompt guidance

A shared `_WORKSPACE_STATE_GUIDANCE` block was added to both `build_assistant_prompt` (JSON-contract path) and `build_assistant_text_prompt` (streaming prose path) so behavior is identical regardless of which call site uses which. The block teaches the model:

1. **The `workspace_state` shape**, field by field, with explicit semantics. `experience_entries_count` is the number of work entries on the resume, NOT years of experience — the original name `experience_count` led the LLM to answer "how many years?" with the entry count. Renamed everywhere with a sentence in the prompt explicitly disambiguating.
2. **Step-number mapping** (01=Resume, 02=Job Search, 03=Job Detail, 04=Analysis) so questions like "what's step 03 about?" get the right answer instead of a guess.
3. **Auth contract** — the workspace requires sign-in; signed-out users get redirected to the landing page; "can I do X without signing in?" is always NO for any in-workspace action.
4. **Eight rules** for using the state: always check before answering "what's next?"; never invent skills/jobs/scores when the corresponding flag is false; map `current_step` + flags to the very next concrete action; translate raw counts into prose ("we found 27 skills" not "skills_count: 27"); be concise (1–3 sentences for product help).

### Product-knowledge refresh

While ungating, refreshed `src/product_knowledge.py` to ground truth — 12 documents covering the four-step flow, both resume intake modes (Upload + Build with assistant), all four ATS sources (Greenhouse, Lever, Ashby, Workday), the six supervised-pipeline agents, PDF + DOCX exports with theme palette, the saved-workspace 24-h TTL, the command palette, the floating assistant itself, the cover letter artifact, and the quota model. Several earlier documents referenced retired surfaces (e.g. "Manual JD Input" instead of "Job Detail," Markdown export which was removed in 2026-05); those were rewritten or replaced.

## Alternatives Considered

### 1. Save chat history to a Supabase `assistant_messages` table and ground answers on it
Rejected for now. Useful for cross-device persistence and recall ("what did I ask last week?"), but it does not improve answer quality on the current turn and adds round-trips. Independent of this ADR; can be revisited later.

### 2. Build a Supabase `workspace_state` table that the backend reads on every assistant query
Rejected. The state already lives in React memory on the client. A server-side store creates a sync problem (which is the source of truth?), adds a round-trip per query, and doesn't give us anything we don't already get by sending the projection inline. Latency-wise, a 500–800 byte JSON addition to the existing request payload is invisible compared to LLM streaming time.

### 3. Inject `workspace_state` directly into the prompt's text instead of via the JSON `product_context` block
Rejected. The existing `assistant_context` JSON block already carries context cleanly; adding a parallel text channel would split the source of truth. Putting the state inside `product_context` reuses the same path the existing flags (`has_resume`, `has_tailored_resume`, etc.) already travel.

### 4. Keep the gate but make the empty-state copy more useful
Rejected. The user's actual mental model is "I can chat with the assistant" — gating it on an action they may not have done yet is friction, not safety. The backend's `answer_product_help` path makes the gate redundant.

## Consequences

### Positive

- Users can ask questions from the very first visit, including before they upload anything.
- "What should I do next?" returns three different, correct answers across the cold-start / mid-flow / ready-to-run personas instead of one generic answer for all three.
- The assistant proactively suggests next actions ("you've saved 2 roles — open one of those postings to move to the JD step") instead of describing the workspace abstractly.
- The cosmetic `hasWorkspaceContext` boolean drives panel copy that's contextual without adding a new gate.
- Field semantics are now explicit in the prompt so the model can't quietly conflate counts with durations.
- Battle-test verified: 47/51 (92%) across three persona × ~17 questions, with 0 outstanding correctness failures after the entry-count and step-number bugs were fixed.

### Negative

- Slightly more tokens per query (~150 prompt tokens for the guidance block + ~500–800 bytes of payload). Cost impact is minimal on the assistant model; latency-wise the ~30–80 ms TTFT increase is invisible inside the streaming generation time.
- The assistant now answers a wider range of questions, which means the system prompt has to handle more edge cases (off-topic questions, account-deletion requests, unverified pricing claims). Mitigated by the existing scope-narrowing language at the top of the prompt and verified by battle-test refusals.
- Product-knowledge maintenance is now a real ongoing job — the ground-truth refresh in this ADR is current as of 2026-05-08, but the index will go stale as features ship. Owner: whoever ships a new workspace surface should update `src/product_knowledge.py` in the same PR.

## Follow-Up

- Add an `assistant_quality_runner` fixture for the `cold_start` / `mid_flow` / `ready_to_run` personas so future system-prompt edits land with measurable evidence rather than vibes.
- Consider persisting chat history to Supabase for cross-device recall (independent of this ADR; not blocking).
- Track LLM cost per assistant turn against the workspace cost ceiling; the assistant is now reachable from a wider user surface than before, so usage patterns may shift.
