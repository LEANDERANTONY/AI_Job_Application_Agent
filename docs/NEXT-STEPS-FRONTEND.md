# Next steps: frontend split + assistant streaming

> **Purpose.** This document hands off two pending pieces of work
> (Items 2 and 3 from a multi-session code review) to a fresh chat
> session, so the next session can execute without re-deriving the
> context from a long backlog.
>
> **Status as of 2026-04-25 / commit `f4edad5`:** the backend is
> cleaned up, rate-limited, and tested (196 passing). The frontend
> has live WIP on `globals.css` and `job-application-workspace.tsx`
> that has **not been committed yet**. Both items below depend on
> that WIP being merged or stashed first.

---

## Project context (read this first)

- **Architecture (current):** Next.js 14 App Router on Vercel ↔ FastAPI on a single VPS (Caddy reverse proxy, single Docker container, single uvicorn worker). Supabase (Postgres + Google OAuth) for persistence and auth.
- **Architecture (historical, ignore for this work):** Streamlit + Render. Migration completed in DEVLOG Day 36, recorded in ADR-012. Plenty of stale references may still exist in older code comments — treat the live `backend/` and `frontend/` directories as canonical.
- **Auth model.** Supabase Google sign-in. Frontend stores access/refresh tokens in `localStorage` and sends them on every authenticated request via `X-Auth-Access-Token` / `X-Auth-Refresh-Token` headers. Backend re-validates against Supabase per request via `backend/request_auth.py`. (XSS risk is acknowledged; not in scope here.)
- **Domain core.** All business logic lives in `src/`. The FastAPI layer in `backend/` is a thin HTTP/auth/persistence shell over `src/`. Don't put domain logic in `backend/`.
- **Rate limiting.** All expensive endpoints are now bucketed per-user (Supabase JWT `sub`) or per-IP if anonymous. See `backend/rate_limit.py`. Tests in `tests/test_rate_limit.py`. Limits: HEAVY 10/min (full agent workflow), LLM 30/min (single LLM call), PARSE 60/min (file parsing). The polling endpoint `GET /workspace/analyze-jobs/{job_id}` is deliberately unlimited.
- **Tests.** `uv run pytest -q` from the repo root. Suite is 196 passing on Windows. There's a Windows-only `PermissionError: WinError 5` on the temp-dir cleanup that returns exit code 1 even on full pass — read the summary line, not the exit code.
- **Edits policy.** `Desktop Commander:edit_block` for exact-string find/replace. AST-based Python helpers for structural multi-location edits. **Never regex-on-text for multi-line code blocks** — that caused a real bug earlier in this review and is a hard rule.

### Key files for these two items

- `frontend/src/components/job-application-workspace.tsx` — 3,500+ lines, single `"use client"` component, **the target of Item 2**. Contains all 7 feature areas (auth bootstrap, job search, resume intake, JD review, analysis run/poll, artifact preview, assistant chat) plus inline icon SVGs.
- `frontend/src/app/globals.css` — 2,466 lines, hand-rolled, no Tailwind, no CSS modules.
- `frontend/src/lib/api.ts` (397 lines) and `frontend/src/lib/api-types.ts` — the HTTP layer. Already cleanly separated. Touch this carefully; backend changes need parallel TS type updates.
- `frontend/src/lib/auth-session.ts` — token persistence helpers, isolated from components.
- `frontend/src/lib/job-workspace.ts` (~300 lines) — domain helpers (`buildJobResultBadges`, `buildJobReview`). Good foundation for the `useWorkspace*` hooks introduced in Item 2.
- `backend/routers/workspace.py` — has `POST /assistant/answer` at the assistant endpoint. **Item 3 will add `POST /assistant/answer/stream`** as a sibling.
- `backend/services/workspace_service.py` — calls `answer_workspace_question(...)` which is in `src/assistant_service.py`.
- `src/assistant_service.py` — the assistant entry point. Two surfaces: `assistant_product_help` (cheap, low reasoning) and `assistant_application_qa` (high-trust, medium reasoning). Both currently use `run_json_prompt()` which calls `responses.create()` non-streaming and parses a JSON object with fields `answer`, `sources`, `suggested_follow_ups`.
- `src/openai_service.py` — wraps the OpenAI Responses API. Streaming is supported by the underlying API but not yet exposed here.

### Frontend WIP that **must merge first**

The user has uncommitted changes on:
- `frontend/src/app/globals.css`
- `frontend/src/components/job-application-workspace.tsx`

Both items below directly conflict with `workspace.tsx`. **Do not start coding either item until the user has either committed those changes or explicitly told you to rebase on top of them.** Step 1 of any new session should be `git status` + asking the user how to handle WIP.

---

## Item 2 — Frontend split

### The problem

`job-application-workspace.tsx` is 3,500+ lines in one client component with ~50 `useState` hooks, 10+ `useEffect` blocks, and seven distinct feature areas mixed together. Inline SVG icon components live in the same file. Every interaction re-renders the whole tree because everything shares one render scope. This is the single biggest blocker for both UX iteration speed and code maintainability.

### Goals

1. **No behavior change.** Every existing user-visible interaction continues to work identically.
2. **Bundle size reduction.** As much rendered HTML as possible served by React Server Components; only interactive subtrees become `"use client"`.
3. **Render scope isolation.** A change in the assistant panel should not re-render the artifact viewer.
4. **A clean foundation for Item 3** (assistant streaming becomes trivial once the assistant lives in its own component with its own state).

### Proposed file breakdown

Split `job-application-workspace.tsx` into approximately seven sub-components. Suggested layout under `frontend/src/components/workspace/`:

```
workspace/
├── WorkspaceShell.tsx          # 'use client' top-level layout + tab routing
├── Sidebar.tsx                 # 'use client' nav + collapsed-state
├── ResumeIntake.tsx            # 'use client' upload + builder chooser
├── JobSearch.tsx               # 'use client' search bar + result list
├── JDReview.tsx                # 'use client' JD summary + edit panel
├── AnalysisRunner.tsx          # 'use client' run/poll + progress
├── ArtifactViewer.tsx          # 'use client' resume / cover letter / report tabs
├── AssistantPanel.tsx          # 'use client' chat surface (Item 3 lives here)
└── icons.tsx                   # extracted inline SVG icon components
```

Plus, under `frontend/src/hooks/`:

```
hooks/
├── useWorkspaceSession.ts      # auth restore, saved-snapshot bootstrap
├── useAnalysisJob.ts           # POST /analyze-jobs + polling state machine
├── useAssistantHistory.ts      # localStorage-backed chat history
├── useSavedJobs.ts             # GET/POST/DELETE /workspace/saved-jobs
└── useArtifactExport.ts        # POST /artifacts/export with toast feedback
```

### State strategy

The current "everything in one `useState` per concern" works, but stops scaling around 30 `useState`s. Two reasonable choices:

- **Option A — React Context.** Add a `WorkspaceContext` provider in `WorkspaceShell.tsx` and consume it in children via custom hooks. Zero new dependencies. Best for a project that's avoided third-party state libs so far.
- **Option B — Zustand.** ~3KB, gives you per-slice subscriptions (so the assistant chat doesn't re-render when the JD changes). Single dependency add, real performance win.

**Recommend B** because the workspace has clear independent slices and the per-slice subscription win is real. Get explicit user approval before adding the dependency.

### Server vs client components

`app/workspace/page.tsx` is currently the only server-side entry. Most of the workspace is interactive, but a few parts can stay server-rendered:

- The **JD summary view** (read-only display of parser output) — server component.
- The **artifact preview** (markdown → HTML) — render server-side, hydrate the export buttons as a small `"use client"` island.
- Saved-jobs **list** (when not in the active modify state) — server component.

These are nice-to-haves; the bigger win is the file split itself.

### Tailwind migration question

The 2,466-line `globals.css` is a separate problem. Options:

- **Don't touch it now.** Item 2 is purely a JS/TSX restructure. CSS classes get copied across files as-is. Tailwind migration is a follow-up item.
- **Introduce Tailwind alongside.** Both can coexist. Existing classes keep working, new components use Tailwind. Lower disruption than a full rewrite.

**Recommend the first** — keep this item focused. Surface Tailwind as a separate Item 2.5 if you want it.

### Suggested execution order

1. **`git status`** + user confirmation that frontend WIP is merged.
2. **Snapshot baseline.** Take a screenshot of every workspace state before any changes. Compare against the same states after the split — ideally pixel-identical.
3. **Extract icons first** to `workspace/icons.tsx`. Tiny, safe first step.
4. **Extract the sidebar** to `workspace/Sidebar.tsx` with its own state for collapse/expand. Small, isolated.
5. **Build the state layer.** Create `WorkspaceContext` (or Zustand store) with the full shape, populated initially from values lifted out of the monolith.
6. **Extract one feature area at a time** in this order: AssistantPanel → ArtifactViewer → JDReview → AnalysisRunner → ResumeIntake → JobSearch. Test each extraction by running the app between steps. Commit after each.
7. **Extract `WorkspaceShell.tsx`** as the parent. Replace the original `job-application-workspace.tsx` with a thin re-export of `WorkspaceShell` so any importer paths keep working, then optionally remove the file in a final cleanup commit.
8. **Build & lint:** `cd frontend && npm run build && npm run lint`. Both must pass.
9. **Manual smoke test the full happy path:** sign in → upload resume → upload JD → run analysis → wait for completion → preview each artifact → export → ask the assistant a question → save the workspace → reload page → confirm restore.

### Acceptance criteria

- [ ] No file in `frontend/src/components/workspace/` exceeds 600 lines.
- [ ] `npm run build` produces a smaller First Load JS for `/workspace` than before. (Compare before/after; if it's larger, the split has accidentally regressed.)
- [ ] All seven feature areas work identically to baseline.
- [ ] `useState` count in any single component ≤ 10.
- [ ] No new `any` types in TypeScript.
- [ ] No regressions in `tests/test_backend_*.py` — these are HTTP contract tests and shouldn't be affected by frontend work, but verify.

### Risks and watch-outs

- **The `useEffect` bootstrap chain.** The current monolith has a careful order: auth restore → session restore → saved-jobs load → URL-tab read. Replicate that order in `useWorkspaceSession`. Wrong order = lost state on refresh.
- **`localStorage` keys.** `ASSISTANT_HISTORY_STORAGE_KEY = "workspace-assistant-history-v1"` and the auth-session keys must keep the same string values, or every existing user loses their session on first deploy.
- **URL deep links.** The current code reads `?tab=...&drawer=...` on mount via `getInitialMainTab` / `getInitialSidebarCollapsed`. Preserve this in `WorkspaceShell` or you break shareable links.
- **Re-render avalanches.** If you do go with Context, wrap stable callbacks in `useCallback` and stable arrays/objects in `useMemo` aggressively. The whole point of this split is fewer renders, not more.

---

## Item 3 — Assistant streaming via SSE

### The problem

The assistant currently uses `POST /api/workspace/assistant/answer` which calls OpenAI non-streaming and waits for the full JSON response. Typical user-perceived latency: 3–8 seconds before any text appears. That's the worst snappiness regression in the product.

### Why it was deferred earlier

OpenAI's Responses API does support streaming, but the current backend uses `responses.create(..., text={"format": "json_object"})`. JSON streaming is hard to render incrementally without fragile partial-parse logic. The clean fix is to **change the contract**: stream `answer` as plain text, and return `sources` + `suggested_follow_ups` as a separate final payload (either a final SSE event or a follow-up call).

That's a meaningful API change, which is why it was deferred to land alongside the frontend split — the new `AssistantPanel.tsx` is a much cleaner home for streaming logic than a 3,500-line monolith.

### Backend plan

#### New endpoint: `POST /api/workspace/assistant/answer/stream`

Sibling to the existing `/answer`. Same request body shape, but the response is SSE (`text/event-stream`).

Event types:

| event | data | when |
|---|---|---|
| `meta` | `{"sources": [...]}` | First event, immediately after the OpenAI request is dispatched. Sources are determined from the workspace snapshot before the LLM runs, so they're known up front. |
| `delta` | `{"text": "..."}` | One per OpenAI streaming token chunk. The frontend appends to its growing `answer` buffer. |
| `followups` | `{"suggested_follow_ups": [...]}` | After the stream completes, before `done`. |
| `done` | `{}` | Signals end of stream. Frontend closes the EventSource. |
| `error` | `{"detail": "..."}` | If anything fails. Frontend shows the error and closes. |

#### Implementation sketch

```python
# backend/routers/workspace.py

from fastapi.responses import StreamingResponse

@router.post("/assistant/answer/stream")
@limiter.limit(LIMIT_LLM)
async def stream_assistant_answer(
    request: Request,
    payload: WorkspaceAssistantRequestModel,
    auth_tokens=Depends(get_optional_auth_tokens),
):
    access_token, refresh_token = auth_tokens
    return StreamingResponse(
        stream_workspace_question(  # new in src/assistant_service.py
            question=payload.question,
            current_page=payload.current_page,
            workspace_snapshot=payload.workspace_snapshot,
            history=[item.model_dump() for item in payload.history],
            access_token=access_token or "",
            refresh_token=refresh_token or "",
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable Caddy buffering
        },
    )
```

The new `stream_workspace_question` in `src/assistant_service.py` is an async generator that yields SSE-formatted strings. Use the **same** prompt, the **same** model routing, and the **same** grounding logic — only the OpenAI call shape changes from non-streaming JSON-object to streaming plain text.

Helper for SSE formatting:

```python
def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"
```

#### OpenAI streaming switch

In `src/openai_service.py`, add a sibling method `run_text_stream()` parallel to `run_json_prompt()`. It calls `client.responses.create(..., stream=True)` and yields text deltas. **Keep `run_json_prompt()` untouched** — other agents in the workflow still use it.

#### Caddy buffering

Caddy by default may buffer streaming responses. Two ways to disable:

1. The `X-Accel-Buffering: no` header on the response (already in the sketch above). Caddy respects this when configured.
2. Add `flush_interval -1` to the reverse proxy in `deploy/vps/Caddyfile`:
   ```
   reverse_proxy api:8000 {
       flush_interval -1
   }
   ```

Test the streaming end-to-end **with** Caddy in the loop, not just direct to uvicorn — buffering is exactly the kind of thing that works locally and breaks in prod.

#### Tests

Add `tests/test_backend_assistant_stream.py`:

- 200 status with `media_type=text/event-stream` for a valid request.
- Response contains a `meta` event before any `delta`.
- Response ends with a `done` event.
- 422 for invalid request body (mirror the existing assistant-answer validation tests).
- Rate limited to LIMIT_LLM (verify by setting `RATE_LIMIT_OVERRIDE` and asserting 429 on the third call).
- Use a **mocked** OpenAI client that yields a fixed sequence of deltas, never the real API.

### Frontend plan

Inside `AssistantPanel.tsx` (new in Item 2):

```tsx
function streamAssistantAnswer(payload: AssistantRequest, onEvent: (event: AssistantStreamEvent) => void) {
    const eventSource = new EventSource(/* not actually EventSource — see below */);
    // ...
}
```

**Important caveat:** `EventSource` only supports GET and doesn't allow custom headers. Since the request has a JSON body and needs `X-Auth-Access-Token`, use `fetch` with a `ReadableStream` reader instead:

```tsx
async function streamAssistantAnswer(payload, headers, onEvent) {
    const response = await fetch('/api/workspace/assistant/answer/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ...headers },
        body: JSON.stringify(payload),
    });

    if (!response.ok) {
        throw new Error(`Stream failed: ${response.status}`);
    }

    const reader = response.body!.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        // Parse SSE events from buffer (split by '\n\n')
        const events = buffer.split('\n\n');
        buffer = events.pop()!; // keep the last (potentially incomplete) chunk

        for (const event of events) {
            const parsed = parseSseEvent(event);
            if (parsed) onEvent(parsed);
        }
    }
}
```

State shape in `AssistantPanel`:

```tsx
type StreamingMessage = {
    role: 'assistant';
    answer: string;        // grows with each delta
    sources: Source[];     // populated by 'meta' event
    suggestedFollowUps: string[]; // populated by 'followups' event
    isStreaming: boolean;  // true until 'done' or 'error'
    error: string | null;
};
```

Render a message progressively:

1. Show "Thinking..." spinner before `meta` arrives.
2. After `meta`, show source chips.
3. As `delta` events arrive, append to `answer` buffer; render with a blinking cursor.
4. After `followups`, show the chip row.
5. After `done`, hide the cursor and mark `isStreaming: false`.

### Backward compatibility

Keep the existing `POST /assistant/answer` (non-streaming) endpoint as-is for now. It's still used by:
- the saved-snapshot restore flow (no streaming needed)
- any non-browser API client

After two weeks of the streaming endpoint being stable, the old endpoint can be deprecated and eventually removed.

### Acceptance criteria

- [ ] First visible token in the assistant panel within 1.5s of the user pressing send (compared to 3–8s today).
- [ ] Sources chip row appears before any answer text starts streaming.
- [ ] Suggested follow-up chips appear after the answer finishes.
- [ ] If the user navigates away mid-stream, the fetch request is properly cancelled (use an AbortController).
- [ ] All existing `tests/test_backend_workspace.py` assistant tests still pass.
- [ ] New `tests/test_backend_assistant_stream.py` tests pass.
- [ ] Streaming works through the deployed Caddy → uvicorn path, not just locally.

### Risks and watch-outs

- **Token cost.** Streaming uses the same number of tokens as non-streaming — no cost change. Just user-perceived latency.
- **Connection drops.** A flaky network mid-stream needs graceful handling. Show an error state with a "retry" button. Don't auto-reconnect (Responses API replays would double-charge).
- **The `current_page` field** in the request is currently used for prompt routing (product-help vs application-qa). Preserve this logic in the streaming version.
- **Source determinism.** Sources today come from the structured JSON output. In the streaming text version, sources are computed before the LLM call from the workspace snapshot itself (which is what should have been happening all along). This may slightly change which sources appear — verify against current behavior.

---

## Useful starter commands

```powershell
# Verify clean baseline
cd 'C:\Users\Leander Antony A\Documents\Projects\AI_Job_Application_Agent'
git status --short
uv run pytest -q

# Frontend dev
cd frontend
npm run dev

# Frontend build (verify bundle size after Item 2)
npm run build

# Backend dev (separate terminal)
cd ..
uv run uvicorn backend.app:app --reload

# Smoke test the streaming endpoint with curl after Item 3
curl -N -X POST http://localhost:8000/api/workspace/assistant/answer/stream \
    -H "Content-Type: application/json" \
    -H "X-Auth-Access-Token: <token>" \
    -d '{"question": "What are my biggest gaps?", "current_page": "Workspace", "workspace_snapshot": {...}, "history": []}'
```

---

## Out of scope for this handoff

These were considered and explicitly deferred:

- **Item 6** (move `_JOBS` dict to Supabase): skipped permanently per current single-worker deployment topology. Don't revisit unless the deploy changes to multi-worker.
- **Tailwind migration of `globals.css`**: separate item, larger scope.
- **Frontend split of CSS** alongside the component split: keep CSS as-is during Item 2.
- **Auth tokens → httpOnly cookies**: real XSS-mitigation work, separate item.
- **Multi-node deployment**: not currently a goal.
