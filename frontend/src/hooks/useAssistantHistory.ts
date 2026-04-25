"use client";

// Hook owning assistant chat thread state and its localStorage
// persistence. Lifted from `WorkspaceShell.tsx` as part of the Item 2
// frontend split (see `docs/NEXT-STEPS-FRONTEND.md`, task #13).
//
// Storage key invariant: ASSISTANT_HISTORY_STORAGE_KEY must NOT change.
// The key is per-(user, workspace-snapshot signature), so a different
// resume / JD / run produces a fresh thread automatically. The user
// scope ("anonymous" or app_user.id) prevents leaking history between
// accounts on a shared device.

import {
  useEffect,
  useMemo,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";

import type {
  AuthSessionResponse,
  WorkspaceAnalysisResponse,
} from "@/lib/api-types";
import type { AssistantTurn } from "@/components/workspace/AssistantPanel";

const ASSISTANT_HISTORY_STORAGE_KEY = "workspace-assistant-history-v1";
const MAX_PERSISTED_ASSISTANT_TURNS = 8;

function hashString(value: string) {
  let hash = 5381;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 33) ^ value.charCodeAt(index);
  }
  return (hash >>> 0).toString(36);
}

function buildAssistantWorkspaceSignature(
  workspaceSnapshot: WorkspaceAnalysisResponse | null,
) {
  if (!workspaceSnapshot) {
    return null;
  }

  const signaturePayload = {
    resume_text: workspaceSnapshot.resume_document.text,
    job_text: workspaceSnapshot.job_description.raw_text,
    workflow_mode: workspaceSnapshot.workflow.mode,
    fit_score: workspaceSnapshot.fit_analysis.overall_score,
    readiness_label: workspaceSnapshot.fit_analysis.readiness_label,
    resume_summary: workspaceSnapshot.artifacts.tailored_resume.summary,
    cover_letter_summary: workspaceSnapshot.artifacts.cover_letter.summary,
    imported_job_id: workspaceSnapshot.imported_job_posting?.id ?? "",
  };

  return hashString(JSON.stringify(signaturePayload));
}

function readStoredAssistantTurns(storageKey: string): AssistantTurn[] {
  if (typeof window === "undefined") {
    return [];
  }

  try {
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) {
      return [];
    }
    const payload = JSON.parse(raw);
    if (!Array.isArray(payload)) {
      return [];
    }
    return payload
      .flatMap((item) => {
        const question =
          typeof item?.question === "string" ? item.question.trim() : "";
        const answer =
          typeof item?.response?.answer === "string"
            ? item.response.answer.trim()
            : "";
        const sources = Array.isArray(item?.response?.sources)
          ? item.response.sources
              .map((source: unknown) =>
                typeof source === "string" ? source.trim() : "",
              )
              .filter(Boolean)
          : [];
        const suggestedFollowUps = Array.isArray(
          item?.response?.suggested_follow_ups,
        )
          ? item.response.suggested_follow_ups
              .map((followUp: unknown) =>
                typeof followUp === "string" ? followUp.trim() : "",
              )
              .filter(Boolean)
          : [];
        if (!question || !answer) {
          return [];
        }
        return [
          {
            question,
            response: {
              answer,
              sources,
              suggested_follow_ups: suggestedFollowUps,
            },
          } satisfies AssistantTurn,
        ];
      })
      .slice(-MAX_PERSISTED_ASSISTANT_TURNS);
  } catch {
    return [];
  }
}

function persistAssistantTurns(storageKey: string, turns: AssistantTurn[]) {
  if (typeof window === "undefined") {
    return;
  }

  if (!turns.length) {
    window.localStorage.removeItem(storageKey);
    return;
  }

  const serializableTurns = turns
    .slice(-MAX_PERSISTED_ASSISTANT_TURNS)
    .map((turn) => ({
      question: turn.question,
      response: {
        answer: turn.response.answer,
        sources: turn.response.sources,
        suggested_follow_ups: turn.response.suggested_follow_ups,
      },
    }));
  window.localStorage.setItem(storageKey, JSON.stringify(serializableTurns));
}

/**
 * Convert assistant turns into the shape the backend `/assistant/answer`
 * endpoint expects (just question + answer per turn).
 */
export function buildAssistantHistoryPayload(turns: AssistantTurn[]) {
  return turns.map((turn) => ({
    question: turn.question,
    answer: turn.response.answer,
  }));
}

export type UseAssistantHistoryOptions = {
  analysisState: WorkspaceAnalysisResponse | null;
  authSession: AuthSessionResponse | null;
};

export type UseAssistantHistoryReturn = {
  assistantTurns: AssistantTurn[];
  setAssistantTurns: Dispatch<SetStateAction<AssistantTurn[]>>;
};

export function useAssistantHistory({
  analysisState,
  authSession,
}: UseAssistantHistoryOptions): UseAssistantHistoryReturn {
  const [assistantTurns, setAssistantTurns] = useState<AssistantTurn[]>([]);

  const assistantWorkspaceSignature = useMemo(
    () => buildAssistantWorkspaceSignature(analysisState),
    [analysisState],
  );

  const userId = authSession?.app_user.id;

  const assistantStorageKey = useMemo(() => {
    if (!assistantWorkspaceSignature) {
      return null;
    }
    const userScope = userId || "anonymous";
    return `${ASSISTANT_HISTORY_STORAGE_KEY}:${userScope}:${assistantWorkspaceSignature}`;
  }, [assistantWorkspaceSignature, userId]);

  // Hydrate from localStorage when the key changes (or clear when no
  // workspace signature is available).
  useEffect(() => {
    if (!assistantStorageKey) {
      setAssistantTurns([]);
      return;
    }
    setAssistantTurns(readStoredAssistantTurns(assistantStorageKey));
  }, [assistantStorageKey]);

  // Persist to localStorage whenever the thread changes.
  useEffect(() => {
    if (!assistantStorageKey) {
      return;
    }
    persistAssistantTurns(assistantStorageKey, assistantTurns);
  }, [assistantStorageKey, assistantTurns]);

  return { assistantTurns, setAssistantTurns };
}
