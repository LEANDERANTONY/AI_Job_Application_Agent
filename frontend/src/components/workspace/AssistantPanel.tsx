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
// handleClearAssistantConversation). The `requiresWorkspaceRun` gate
// also stays — the assistant unlocks only after the first analysis
// run, same as before.
//
// The suggested-follow-up panel was intentionally removed in commit
// 9138ead and is not restored here.

import { useEffect, useRef, useState, type FormEvent } from "react";

import {
  CloseIcon,
  SendIcon,
  SparkleIcon,
} from "@/components/workspace/icons";
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

export type AssistantPanelProps = {
  turns: AssistantTurn[];
  /** In-flight streaming turn, or null when no request is open. */
  streamingTurn?: AssistantStreamingTurn | null;
  /**
   * `true` while the workspace has not yet been analyzed; the assistant
   * is gated on a successful analysis run for the application-Q&A
   * surface.
   */
  requiresWorkspaceRun: boolean;
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
  streamingTurn = null,
  requiresWorkspaceRun,
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
  const bodyRef = useRef<HTMLDivElement | null>(null);

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
                {requiresWorkspaceRun
                  ? "Unlocks after the first workspace run."
                  : "Grounded in your active workspace."}
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
                {requiresWorkspaceRun
                  ? "Run the analysis first — the assistant grounds answers in your workspace package."
                  : "Ask about your tailored resume, cover letter, or the current package."}
              </div>
            )}
          </div>

          {requiresWorkspaceRun ? (
            <div className="rd-assistant-locked">
              Assistant unlocks after your first workspace run.
            </div>
          ) : (
            <form className="rd-assistant-form" onSubmit={handleSubmit}>
              <textarea
                className="rd-assistant-input"
                disabled={sending}
                onChange={(event) => onQuestionChange(event.target.value)}
                onKeyDown={handleKeyDown}
                placeholder="Ask about your package, resume, cover letter, or outputs…"
                value={question}
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
          )}
        </div>
      ) : null}
    </>
  );
}
