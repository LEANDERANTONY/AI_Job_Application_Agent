"use client";

// Assistant chat surface — extracted from `job-application-workspace.tsx`
// as part of the Item 2 frontend split (see
// `docs/NEXT-STEPS-FRONTEND.md`).
//
// This is the home for the future SSE streaming logic from Item 3.
// The `AssistantTurn` type is the canonical definition; the monolith
// (and the localStorage helpers) import it from here.
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

export type AssistantPanelProps = {
  turns: AssistantTurn[];
  /**
   * `true` while the workspace has not yet been analyzed — the assistant
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
  requiresWorkspaceRun,
  question,
  onQuestionChange,
  sending,
  canSubmit,
  onSubmit,
  onClearConversation,
}: AssistantPanelProps) {
  return (
    <div className="workspace-sidebar-card workspace-assistant-card">
      <p className="eyebrow">Assistant</p>

      <div className="workspace-assistant-thread">
        {turns.length ? (
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
            disabled={!turns.length}
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
