# Conversational Quality Re-Assessment of the Slice 1G Multi-Provider Eval

**Date:** 2026-05-21
**Source data:** `2026-05-21-agentic-eval-v2-post-fence-fix.json`
**Why this document exists:** the headline scores from Slice 1G (openai
10/10, others 5-6/8) compress something the operator pointed out by
reading the actual replies: **several "failures" are conversationally
SUPERIOR to the OpenAI baseline.** Pass/fail can't see that. This is the
re-classification through a user-experience lens.

## Headline finding — re-read

The v2 pass/fail matrix said openai was the clear winner. The actual
assistant replies tell a more nuanced story:

| Tier | Providers | Why |
|---|---|---|
| **Conversationally STRONG (smart clarifications, catches user errors)** | Sonnet 4.5, Gemini, DeepSeek | All three caught a subtle user error and asked the right question |
| **Conversationally GOOD baseline (commits without questioning, otherwise solid)** | OpenAI, GLM, Grok | Pass every scenario but miss the smart-clarification opportunity |
| **Conversationally MIXED** | Kimi, Qwen | Adapter hiccups (Kimi) / promise-but-don't-fire pattern (Qwen) |

**For pure user-facing chat experience, Sonnet 4.5 / Gemini / DeepSeek
arguably out-perform OpenAI gpt-5.4.** That's the opposite of what the
score matrix suggests.

## The smoking gun — `github_url_fires_tool` scenario

The scenario has the user paste `https://github.com/openai/openai-python`
saying "here's a project of mine." Note: that's the FAMOUS OpenAI Python
SDK, almost certainly NOT actually the user's project. The interesting
question is: does the model NOTICE that and ask?

What each provider actually replied on turn 2:

| Provider | Score | Turn 2 reply (truncated) | Behavior |
|---|---|---|---|
| openai | PASS | "Got it — I read the README and captured the project as the OpenAI Python API library. Anything you'd like to add about your specific contribution or impact?" | Committed without questioning |
| **sonnet-4.5** | **FAIL** | "I see that's the **official OpenAI Python SDK repository maintained by OpenAI**. Is this a project you contributed to, or did you mean to share a different personal project?" | **Caught the trap** |
| **gemini** | PASS | "Got it — I read the README and saw it's the official OpenAI Python API library... Since this is a major open-source project, what were your specific contributions or the measured impact of your work on it?" | **Caught the trap** |
| **deepseek** | **FAIL** | "I pulled up the README for that repo — but it's the **official openai/openai-python SDK maintained by OpenAI, not a personal project**. Did you mean to share a different repo, or did you contribute to this one?" | **Caught the trap** |
| grok | PASS | "Captured your OpenAI Python library project — it's the official SDK..." | Missed; over-eager |
| kimi / glm | FAIL | (Step-machine fallback) | Adapter hiccup |
| qwen | FAIL | "I'll pull up the README for that repo... One moment!" | **Promise-but-don't-fire** — the OLD hallucination pattern |

**Sonnet 4.5, Gemini, and DeepSeek noticed the user was confused** and
asked the smart clarifying question. The eval's `assistant_says_any`
matcher only accepted "read"/"captured"/"saw" vocabulary — it treated
the smarter response as a fail.

## The promise-tracking scenario tells a similar story

When the user said "I have a publication on graph neural networks I'll
share later", every single provider ACK'd the deferral conversationally:

  - openai:    "Got it — I'll leave the publication details for later."
  - sonnet:    "Noted — we'll add that publication once you're ready."
  - gemini:    "Sounds good, I'll remind you to add the GNN publication details later."
  - kimi:      "Noted — we'll come back to your graph neural networks publication later."
  - glm:       "Noted — I'll circle back for your graph neural networks publication when you're ready."
  - grok:      "Noted — I'll capture your graph neural networks publication when you're ready..."
  - deepseek:  "Noted — happy to include your GNN publication. I'll circle back for the details..."
  - qwen:      "Noted — we'll circle back to your graph neural networks publication when you're ready."

And on turn 4 (when the user asked "what else do you need from me?"),
**every single provider resurfaced the publication**:

  - openai:    "Earlier you mentioned a publication on graph neural networks — want to share the details now?"
  - sonnet:    "Earlier you mentioned a publication on graph neural networks you wanted to add — want to share the details now?"
  - gemini:    "Earlier you mentioned a publication on graph neural networks that you wanted to include..."
  - kimi:      "Earlier you mentioned a graph neural networks publication you wanted to include..."
  - glm:       "Earlier you mentioned a publication on graph neural networks — want to share the details now?"
  - grok:      "Earlier you mentioned a publication on graph neural networks you'd share later — want to give the details now?"
  - deepseek:  "Earlier you mentioned a publication on graph neural networks you wanted to add..."
  - qwen:      "Earlier you mentioned a publication on graph neural networks — want to share the details now?"

The 4 FAILs (gemini, kimi, grok, qwen) failed only the structured-data
check (`pending_followups[]` JSON field not populated when they ACK'd
the deferral). **The chat that the user sees is identical to the
passing providers.** This is a structural bookkeeping issue, not a
conversational quality issue.

## What's actually failing — the structural errors

Disentangling the eval results into two failure classes:

### Class A: Structural / schema errors (USER NEVER SEES THESE)

  1. **`structured_payload_runs_after_generate`** — fails on most
     providers (Sonnet, Gemini, Kimi, GLM, DeepSeek, Qwen). This is
     a SEPARATE backend call (the structuring LLM that converts free
     prose into ProjectEntry / EducationEntry lists). Uses an
     ~11K-char prompt with worked BEFORE/AFTER examples that
     stretches non-OpenAI providers. **The user's chat experience
     is unaffected** — the conversation is fine; the "click
     Generate" step at the end fails to produce structured projects.

  2. **`pending_followups[]` field not populated** — 4 providers
     conversationally tracked the deferral but didn't write the
     JSON `add_followups` field on turn 3. Again, **the user's chat
     experience is unaffected** — the publication still got
     resurfaced on turn 4. Just a missing structured-state write.

### Class B: Actual conversational errors

  1. **Qwen: promise-but-don't-fire** on the github URL scenario.
     Says "I'll pull up the README... one moment!" but the tool
     never fires. This is the SAME hallucination pattern that
     prompted this entire session (the user's original complaint
     about the agent claiming a capability and then not delivering).
     Qwen is the only provider that still does this consistently.

  2. **Grok: over-eager tool use**. On `non_github_url_no_fetch`,
     Grok called `fetch_github_readme` on a non-github URL anyway
     (the function would have rejected it server-side, but the agent
     SHOULD know not to call it). On the github URL scenario, it
     fired THREE web_search calls plus a fetch — burning latency.
     Tool-use discipline is weaker than the others.

  3. **Kimi: adapter hiccups on tool-call turns**. Some turns get
     parsed as bare JSON, some don't (markdown-fence intermittent).
     Real conversation quality is fine when the adapter clears.

## Per-provider take

Looking at this through "how would a real user feel after a session":

  - **Sonnet 4.5**: best conversational quality of the OpenRouter
    candidates. Catches user errors (the github-URL trap), asks
    smart clarifying questions, handles deferrals well, resurfaces
    promises naturally. Loses points on the agent eval ONLY because
    of structured-data field-population (which is below the
    user-visible surface). **For a chat-first feel, this is the
    strongest non-OpenAI option.**

  - **Gemini**: matches Sonnet on conversational smartness; same
    trap-catching, same "what were your specific contributions"
    follow-up. Slightly more verbose. Same structured-data
    underpopulation.

  - **DeepSeek**: same trap-catching as Sonnet/Gemini. Asks for
    citation, authors, venue, date — more thorough on detail
    collection. Same structured-data gap.

  - **OpenAI gpt-5.4**: doesn't catch the github-URL trap (treats
    a famous OSS repo as the user's own project without checking)
    but otherwise handles every scenario reliably. **Structurally
    the most reliable** — the only provider that passes
    `structured_payload_runs_after_generate` consistently.

  - **GLM**: solid baseline, no smart-clarification but no
    structural failures either. Mid-tier across the board.

  - **Grok**: solid baseline + occasional over-eager tool use.
    Burns more latency than needed (multiple web_search per scenario).
    `structured_payload` passes, which is notable.

  - **Kimi**: adapter intermittency drops some turns. When it works,
    conversational quality is comparable to baseline.

  - **Qwen**: the weakest conversationally — still shows the
    promise-but-don't-fire pattern that was the original bug
    that started this whole session. Avoid.

## The right recommendation, given this re-read

**For the resume-builder conversational surface specifically:**

  1. **OpenAI gpt-5.4 stays default for the full pipeline.** It's
     the only provider that handles both the conversational
     intake AND the heavy structuring pass reliably.

  2. **If the operator wants to A/B a "chat-first" experience**,
     swap in Sonnet 4.5 or Gemini for the intake LLM only, keep
     OpenAI for the structuring pass. The structured-data
     under-population (`pending_followups[]` not getting written)
     would still need a prompt fix per-provider, but the user-
     facing conversation would feel SMARTER on Sonnet/Gemini —
     they'd catch user-error patterns OpenAI's baseline misses.

  3. **Failover targets for non-PII workloads (per ADR-028 D1):**
     Sonnet 4.5, Gemini, DeepSeek — all viable, all conversationally
     strong. GLM and Grok also pass the bar but with no smart-
     clarification edge. Avoid Kimi (adapter issues) and Qwen
     (promise-don't-fire pattern) until those clear up.

## What the eval misses (Phase 3 candidate)

This re-read suggests the eval matchers are too narrow. A richer
rubric would distinguish:

  - **"Committed without question"** (current PASS bar) vs
  - **"Asked smart clarifying question first"** (currently treated as FAIL but is BETTER)
  - **"Hallucinated capability"** (the original bug — qwen still does this)

The current matchers can't tell those three apart. A v2 rubric with
LLM-as-judge scoring for "conversational quality" (1-5 scale) per
scenario would give a more honest cross-provider picture. Parked.
