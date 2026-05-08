"use client";

// Assistant chat surface extracted from `job-application-workspace.tsx`
// as part of the Item 2 frontend split (see
// `docs/NEXT-STEPS-FRONTEND.md`).
//
// Item 3 added the streaming surface: while a question is in flight,
// the parent passes a `streamingTurn` describing the current partial
// answer (sources from the `meta` event, text growing with each
// `delta` event). On `done`, the parent commits the turn into the
// regular `turns` array and clears `streamingTurn` to null.
//
// Note: the suggested-follow-up panel was removed in commit 9138ead
// per the user's intentional product decision. Do not restore it here
// without re-confirming.

import type { FormEvent } from "react";

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
   * is gated on a successful analysis run for the application-Q&A surface.
   */
  requiresWorkspaceRun: boolean;
  question: string;
  onQuestionChange: (value: string) => void;
  sending: boolean;
  canSubmit: boolean;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onClearConversation: () => void;
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
}: AssistantPanelProps) {
  const hasContent = turns.length > 0 || streamingTurn !== null;

  return (
    <div className="workspace-sidebar-card workspace-assistant-card">
      <p className="eyebrow">Assistant</p>

      <div className="workspace-assistant-thread">
        {hasContent ? (
          <div className="workspace-chat-history">
            {turns.map((turn, index) => (
              <div
                className="workspace-chat-turn"
                key={`${index}-${turn.question.slice(0, 18)}`}
              >
                <div className="workspace-chat-bubble workspace-chat-user">
                  {turn.question}
                </div>
                <div className="workspace-chat-bubble workspace-chat-assistant">
                  {turn.response.answer}
                </div>
              </div>
            ))}
            {streamingTurn ? (
              <div
                className="workspace-chat-turn workspace-chat-turn-streaming"
                key="streaming"
              >
                <div className="workspace-chat-bubble workspace-chat-user">
                  {streamingTurn.question}
                </div>
                <div className="workspace-chat-bubble workspace-chat-assistant">
                  {streamingTurn.error ? (
                    <span className="workspace-chat-error">
                      {streamingTurn.error}
                    </span>
                  ) : (
                    <>
                      {streamingTurn.partialAnswer}
                      {streamingTurn.isStreaming ? (
                        <span
                          aria-hidden="true"
                          className="workspace-chat-cursor"
                        >
                          |
                        </span>
                      ) : null}
                      {!streamingTurn.partialAnswer && streamingTurn.isStreaming ? (
                        <span className="workspace-chat-thinking">
                          Thinking...
                        </span>
                      ) : null}
                    </>
                  )}
                </div>
              </div>
            ) : null}
          </div>
        ) : !requiresWorkspaceRun ? (
          <div className="workspace-empty-state workspace-empty-state-compact">
            Ask about your tailored resume, cover letter, or the current
            package.
          </div>
        ) : null}
      </div>

      <form className="workspace-assistant-form" onSubmit={onSubmit}>
        <textarea
          className="workspace-assistant-textarea"
          disabled={requiresWorkspaceRun || sending}
          onChange={(event) => onQuestionChange(event.target.value)}
          placeholder={
            requiresWorkspaceRun
              ? "Assistant unlocks after your first workspace run."
              : "Ask about your package, resume, cover letter, or the current outputs..."
          }
          value={question}
        />
        <div className="workspace-sidebar-actions">
          <button
            className="primary-button workspace-button workspace-button-full"
            disabled={!canSubmit}
            type="submit"
          >
            {sending
              ? "Sending..."
              : requiresWorkspaceRun
                ? "Awaiting workspace run"
                : "Send to assistant"}
          </button>
          <button
            className="secondary-button workspace-button workspace-button-full"
            disabled={!turns.length && !streamingTurn}
            onClick={onClearConversation}
            type="button"
          >
            Clear chat
          </button>
        </div>
      </form>
    </div>
  );
}
