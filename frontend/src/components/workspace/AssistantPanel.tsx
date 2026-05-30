"use client";

// Floating assistant — Direction B redesign.
//
// The component used to render as a sidebar card inside the (now
// removed) Sidebar slot. It now mounts itself as a fixed-position FAB
// at the bottom-right corner of the workspace, expanding into a 380px
// popover anchored to the same corner.
//
// The streaming surface and clear-conversation behavior are preserved
// verbatim (see WorkspaceShell.handleAssistantSubmit /
// handleClearAssistantConversation). The previous `requiresWorkspaceRun`
// gate that locked the assistant until an analysis had run was lifted —
// users can now ask product-help questions ("how do I use this?",
// "what's step 03 for?") before they have any workspace at all. The
// backend's AssistantService.answer_product_help path handles those
// gracefully when no workspace snapshot is attached. The remaining
// `hasWorkspaceContext` prop only controls cosmetic copy (grounded vs
// general).
//
// The suggested-follow-up panel was intentionally removed in commit
// 9138ead and is not restored here.

import { useEffect, useRef, useState, type FormEvent } from "react";
import { create } from "zustand";

// Local notice surface for voice-input errors. The assistant panel
// doesn't have an existing notice slot we can borrow, so we render a
// short-lived inline message under the form. Cleared on the next
// successful transcription, the next submit, or after 6 seconds.

import {
  CloseIcon,
  SendIcon,
  SparkleIcon,
} from "@/components/workspace/icons";
import { FeedbackButtons } from "@/components/workspace/FeedbackButtons";
import { VoiceInputButton } from "@/components/workspace/VoiceInputButton";
import type { WorkspaceAssistantResponse } from "@/lib/api-types";

export type AssistantTurn = {
  question: string;
  response: WorkspaceAssistantResponse;
};

/**
 * In-flight streaming turn the panel renders below committed `turns`
 * while a request is open. Cleared by the parent on stream
 * completion (success or error).
 */
export type AssistantStreamingTurn = {
  question: string;
  /** Grows with each `delta` event. */
  partialAnswer: string;
  /** Populated by the `meta` event up front. */
  sources: string[];
  /** True between the first POST and the terminal `done`/`error` event. */
  isStreaming: boolean;
  /** Set to the SSE `error` event's `detail`, or null on the happy path. */
  error: string | null;
};

type AssistantStreamingStore = {
  streamingTurn: AssistantStreamingTurn | null;
  setStreamingTurn: (turn: AssistantStreamingTurn | null) => void;
  updateStreamingTurn: (
    fn: (current: AssistantStreamingTurn) => AssistantStreamingTurn,
  ) => void;
};

/**
 * The in-flight streaming buffer lives HERE, not in WorkspaceShell, so
 * per-token SSE writes re-render ONLY this panel — not the whole
 * workspace tree (review PERF-1). The shell writes non-reactively via
 * `useAssistantStreamingStore.getState()` so its own renders are not
 * triggered per token; this panel subscribes to the slice. The
 * `updateStreamingTurn` null-guard reproduces the shell's prior
 * `current ? {...} : current` semantics exactly, so a late event after
 * a clear-to-null can never resurrect a turn.
 */
export const useAssistantStreamingStore = create<AssistantStreamingStore>(
  (set) => ({
    streamingTurn: null,
    setStreamingTurn: (streamingTurn) => set({ streamingTurn }),
    updateStreamingTurn: (fn) =>
      set((state) => ({
        streamingTurn: state.streamingTurn
          ? fn(state.streamingTurn)
          : state.streamingTurn,
      })),
  }),
);

export type AssistantPanelProps = {
  turns: AssistantTurn[];
  /**
   * `true` once the user has run an analysis (i.e. there's a workspace
   * snapshot the assistant can ground answers in). Affects only the
   * cosmetic header sub-line and the empty-state copy — the assistant
   * is *not* gated on this. Without a workspace, the assistant routes
   * through the product-help path on the backend.
   */
  hasWorkspaceContext: boolean;
  question: string;
  onQuestionChange: (value: string) => void;
  sending: boolean;
  canSubmit: boolean;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onClearConversation: () => void;
  /**
   * Optional controlled-open hook so the parent (e.g. the command
   * palette "Ask assistant" action) can pop the panel open. The
   * component still owns its own boolean when this prop is omitted.
   */
  forceOpen?: boolean;
  onForceOpenHandled?: () => void;
};

export function AssistantPanel({
  turns,
  hasWorkspaceContext,
  question,
  onQuestionChange,
  sending,
  canSubmit,
  onSubmit,
  onClearConversation,
  forceOpen,
  onForceOpenHandled,
}: AssistantPanelProps) {
  const [open, setOpen] = useState(false);
  const [voiceError, setVoiceError] = useState<string | null>(null);
  // Subscribe to the streaming buffer here (the shell writes it
  // non-reactively) so token deltas re-render only this panel (PERF-1).
  const streamingTurn = useAssistantStreamingStore((s) => s.streamingTurn);
  const bodyRef = useRef<HTMLDivElement | null>(null);

  // Auto-clear the voice error after 6s so a stale message doesn't
  // sit indefinitely under the input. Re-rendering with a fresh
  // setTimeout is safer than relying on the user to dismiss it.
  useEffect(() => {
    if (!voiceError) return undefined;
    const id = window.setTimeout(() => setVoiceError(null), 6000);
    return () => window.clearTimeout(id);
  }, [voiceError]);

  useEffect(() => {
    if (forceOpen) {
      setOpen(true);
      onForceOpenHandled?.();
    }
  }, [forceOpen, onForceOpenHandled]);

  // Auto-scroll to the latest message whenever the thread grows.
  useEffect(() => {
    if (!open) return;
    const el = bodyRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [open, turns.length, streamingTurn?.partialAnswer]);

  const hasContent = turns.length > 0 || streamingTurn !== null;

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    onSubmit(event);
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (canSubmit) {
        const form = event.currentTarget.form;
        if (form) form.requestSubmit();
      }
    }
  }

  return (
    <>
      <button
        aria-label={open ? "Close assistant" : "Open assistant"}
        className="rd-fab"
        onClick={() => setOpen((current) => !current)}
        onMouseLeave={(event) => {
          // Reset the cursor-tracking highlight position when the
          // pointer leaves so the gradient doesn't get stuck off-axis.
          event.currentTarget.style.removeProperty("--rd-fab-x");
          event.currentTarget.style.removeProperty("--rd-fab-y");
        }}
        onMouseMove={(event) => {
          // Update CSS vars with the pointer's relative position so the
          // inner highlight gradient follows the cursor — small but
          // makes the FAB feel alive on hover.
          const rect = event.currentTarget.getBoundingClientRect();
          const x = ((event.clientX - rect.left) / rect.width) * 100;
          const y = ((event.clientY - rect.top) / rect.height) * 100;
          event.currentTarget.style.setProperty("--rd-fab-x", `${x}%`);
          event.currentTarget.style.setProperty("--rd-fab-y", `${y}%`);
        }}
        type="button"
      >
        <SparkleIcon />
        {!open ? <span className="rd-fab-dot" /> : null}
      </button>

      {open ? (
        <div
          aria-label="Workspace assistant"
          className="rd-assistant"
          role="dialog"
        >
          <div className="rd-assistant-head">
            <div>
              <div className="rd-assistant-title">Assistant</div>
              <div className="rd-assistant-sub">
                {hasWorkspaceContext
                  ? "Grounded in your active workspace."
                  : "Ask anything — product help or workspace Q&A."}
              </div>
            </div>
            <div className="rd-assistant-head-actions">
              <button
                aria-label="Clear chat"
                className="rd-assistant-iconbtn"
                disabled={!turns.length && !streamingTurn}
                onClick={onClearConversation}
                title="Clear chat"
                type="button"
              >
                <CloseIcon />
              </button>
              <button
                aria-label="Close"
                className="rd-assistant-iconbtn"
                onClick={() => setOpen(false)}
                type="button"
              >
                <span aria-hidden="true">−</span>
              </button>
            </div>
          </div>

          <div className="rd-assistant-body" ref={bodyRef}>
            {hasContent ? (
              <>
                {turns.map((turn, index) => (
                  <div
                    className="rd-assistant-turn"
                    key={`${index}-${turn.question.slice(0, 18)}`}
                  >
                    <div className="rd-bubble rd-bubble-user">
                      {turn.question}
                    </div>
                    <div className="rd-bubble rd-bubble-assistant">
                      {turn.response.answer}
                    </div>
                    {/* Per-turn feedback so we can correlate satisfaction
                        with the assistant scope (product help vs
                        workspace QA) in aggregate. */}
                    <FeedbackButtons
                      surface="assistant_turn"
                      prompt="Was this answer helpful?"
                    />
                  </div>
                ))}
                {streamingTurn ? (
                  <div className="rd-assistant-turn" key="streaming">
                    <div className="rd-bubble rd-bubble-user">
                      {streamingTurn.question}
                    </div>
                    <div
                      className={
                        streamingTurn.error
                          ? "rd-bubble rd-bubble-error"
                          : "rd-bubble rd-bubble-assistant"
                      }
                    >
                      {streamingTurn.error ? (
                        streamingTurn.error
                      ) : (
                        <>
                          {streamingTurn.partialAnswer}
                          {streamingTurn.isStreaming ? (
                            <span
                              aria-hidden="true"
                              className="rd-bubble-cursor"
                            >
                              ▋
                            </span>
                          ) : null}
                          {!streamingTurn.partialAnswer &&
                          streamingTurn.isStreaming ? (
                            <span className="rd-bubble-thinking">
                              Thinking…
                            </span>
                          ) : null}
                        </>
                      )}
                    </div>
                  </div>
                ) : null}
              </>
            ) : (
              <div className="rd-assistant-empty">
                {hasWorkspaceContext
                  ? "Ask about your tailored resume, cover letter, or the current package."
                  : "Ask how to use the workspace, what each step does, or what to do next. Once you've run an analysis, you can ask about your tailored package too."}
              </div>
            )}
          </div>

          {voiceError ? (
            <div
              role="status"
              style={{
                margin: "0 12px 6px",
                padding: "6px 10px",
                fontSize: 12,
                color: "#fbbf24",
                background: "rgba(251, 191, 36, 0.08)",
                border: "1px solid rgba(251, 191, 36, 0.3)",
                borderRadius: 6,
              }}
            >
              {voiceError}
            </div>
          ) : null}
          <form className="rd-assistant-form" onSubmit={handleSubmit}>
            <textarea
              className="rd-assistant-input"
              disabled={sending}
              onChange={(event) => onQuestionChange(event.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={
                hasWorkspaceContext
                  ? "Ask about your package, resume, cover letter, or outputs…"
                  : "Ask how to use the workspace, what each step does…"
              }
              value={question}
            />
            {/* Voice input — secondary surface (the resume builder is
                the flagship). Speaks a question into the input then
                lets the user review + edit before submitting. */}
            <VoiceInputButton
              disabled={sending}
              onTranscript={(text) => {
                setVoiceError(null);
                const trimmed = (question ?? "").trim();
                onQuestionChange(trimmed ? `${trimmed} ${text}` : text);
              }}
              onError={(message) => setVoiceError(message)}
              className="rd-assistant-iconbtn"
              label=""
            />
            <button
              aria-label="Send"
              className="rd-assistant-send"
              disabled={!canSubmit}
              type="submit"
            >
              <SendIcon />
            </button>
          </form>
        </div>
      ) : null}
    </>
  );
}
