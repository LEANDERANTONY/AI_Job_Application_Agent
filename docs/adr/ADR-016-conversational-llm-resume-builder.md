# ADR-016: Conversational LLM Resume Builder

- Status: Accepted
- Date: 2026-05-07

## Context

The earlier resume-onboarding flow had two paths:

1. Upload an existing resume (PDF / DOCX / TXT) — the deterministic + LLM-hybrid parser extracted a candidate profile.
2. Manually fill a structured form for users without a resume yet — large textareas keyed to candidate-profile fields.

Path (2) had real friction:

- Users with no resume usually don't know what to put in fields like "experience bullets" or "education entries". They can describe a project conversationally but freeze when the form asks for structured data.
- The form expected complete answers per field; partial answers (e.g., a job title without dates) didn't survive the form's validation, so users would lose progress.
- Adding new optional sections (Projects, Publications) meant adding more fields to the form, which made the UI longer and more intimidating, not shorter.
- Students and early-career profiles needed a different shape than seniors (Education before Experience), which the static form couldn't express.

We wanted a path that worked the way users naturally describe their background — through a conversation — while still landing the same `CandidateProfile` schema the rest of the workflow consumes.

## Decision

Replace the structured form with an LLM-led chat.

The shape:

- A `resume_builder_sessions` Supabase row tracks one in-progress draft per user, persisted across reloads.
- The user enters a chat surface inside the workspace's "Build with assistant" tab. The LLM asks questions one at a time, accepts free-form answers (multiple fields per turn supported), backtracks when the user corrects a previous answer, and renders a live "field completeness" rail so the user sees what's still missing.
- After every turn, a schema-validated extraction step pulls structured data out of the conversation and updates the session payload. Schema validation failures are silent — the LLM just asks a clearer follow-up.
- A separate **structuring pass** runs at "Generate base resume" time:
  - buckets the flat `skills` list into named categories (`Languages & Tools`, `ML/DL Frameworks`, `Cloud & Infrastructure`, etc.) so the rendered resume groups skills by family
  - expands thin one-liner summaries into full paragraphs (the LLM intake produces concise answers; the structuring pass spends a slightly bigger token budget to give the rendered resume a credible professional summary)
  - recovers a full name when the LLM intake drops a surname mid-conversation
  - emits `compute_section_order(candidate_profile)` so students lead with Education / Projects, academics with Publications, and seniors with Experience after Skills
- The structuring output is cached on the session row so a re-export doesn't re-run the LLM.
- The whole surface is gated to authenticated users (matching the resume-builder LLM auth gate the rest of the product uses).
- Session rows have a 7-day TTL with active-user refresh — every save extends `expires_at`. A `pg_cron` job (`cleanup-expired-resume-builder-sessions`) hard-deletes expired sessions every 5 min; RLS also filters expired rows so a user past their TTL doesn't see stale state.

The download exit lives directly under the chat surface: theme picker (`classic_ats` / `professional_neutral`) + Download PDF / Download DOCX buttons that call `POST /workspace/resume-builder/export` ([ADR-015](ADR-015-docx-first-artifact-export-with-theme-palette.md)).

## Alternatives Considered

### 1. Keep the structured form, add Projects + Publications as optional fields
Rejected. Doesn't solve the underlying "users freeze on structured data entry" problem; just makes the form longer.

### 2. Single-shot LLM ("paste anything, we'll structure it")
Rejected. Users without a resume usually don't have a prepared blob of self-description. The conversational shape forces a small, well-scoped question per turn, which matches how the user actually thinks about their background.

### 3. Form-first with an LLM "fill missing fields" assist button
Considered. Combines the worst of both — users still face the form first, and the assist button turns into a fallback rather than the primary path. The conversational flow is a clearer product story.

### 4. Build the structuring logic into the chat turn itself
Rejected. Each chat turn is on the user's perceived latency budget — every extra LLM call inside a turn slows the conversation. The structuring pass runs at "Generate base resume" time when the user is already waiting for an artifact, so the latency is acceptable there.

## Consequences

### Positive

- Users without a resume can complete a builder session in 5–10 minutes of natural conversation instead of 30+ minutes of form anxiety.
- Backtracking works — saying "actually, my second job was at a different company" updates the session without losing the rest.
- Per-profile section ordering means the rendered resume looks correct for students, academics, and seniors without UI configuration.
- The structuring pass is the only place skills get bucketed and summaries get expanded, so a single quality-runner (`resume_builder_quality_runner.py`) can evaluate the whole content-quality story.
- Drafts survive 7 days of inactivity; an active user who saves any change extends the TTL.
- The exit ramp (download PDF/DOCX from the builder directly) means a user who's just here to make a base resume gets the artifact without needing to upload a JD.

### Negative

- Each chat turn costs an LLM call. We mitigate by:
  - using a smaller / cheaper model for the chat itself
  - reusing OpenAI's response-id continuation so the conversation context is server-side
  - only running the heavier structuring pass at export time, not per-turn
- Schema-validated extraction can drop user content silently if the LLM produces malformed structured output. Mitigated by:
  - a `Tier-3` quality runner that pins extraction success rates across fixtures
  - the LLM intake prompt explicitly asking for "raw text now, structured later" so the structuring pass can recover
  - regex fallback inside the structuring pass for the common "drop the surname" failure mode
- The conversational UX puts more weight on prompt quality. The `resume_builder_quality_runner.py` (Tier-3) pins this so prompt edits land with measurable evidence rather than vibes.

## Follow-Up

- Track LLM cost per completed session; cap heavy structuring calls per user per day.
- If users report the chat going off-topic, add a "stay on resume" guard prompt before each turn.
- See [ADR-015](ADR-015-docx-first-artifact-export-with-theme-palette.md) for the export pipeline this builder feeds into.
