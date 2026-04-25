"use client";

// Hook owning the agent workflow run + polling state machine for the
// workspace. Lifted from `WorkspaceShell.tsx` as part of the Item 2
// frontend split (see `docs/NEXT-STEPS-FRONTEND.md`, task #13).
//
// Cancellation invariant: the polling effect's cleanup sets a local
// `cancelled` flag and clears the pending timeout. Late completions
// (the `persistLatestWorkspace` await in `onCompleted`) might still
// resolve after cancellation; the hook gates the post-completion
// notice + loading flip on the cancellation check, but the caller's
// `onCompleted` body runs regardless (matches monolith behavior).

import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";

import {
  getWorkspaceAnalysisJob,
  startWorkspaceAnalysisJob,
} from "@/lib/api";
import type {
  AuthTokens,
  JobPosting,
  WorkspaceAnalysisJobStatusResponse,
  WorkspaceAnalysisResponse,
} from "@/lib/api-types";
import type { WorkflowStage } from "@/components/workspace/AnalysisRunner";

type Notice =
  | { level: "info" | "success" | "warning"; message: string }
  | null;

type WorkflowRunMode = "preview" | "agentic";

const AGENTIC_WORKFLOW_STAGES: WorkflowStage[] = [
  {
    title: "Workflow crew",
    detail: "Opening your application brief and assigning the first agent.",
    value: 3,
  },
  {
    title: "Matchmaker agent",
    detail:
      "Comparing both sides, scoring overlap, and flagging the real gaps.",
    value: 23,
  },
  {
    title: "Forge agent",
    detail: "Rewriting the draft so it speaks directly to this role.",
    value: 41,
  },
  {
    title: "Gatekeeper agent",
    detail: "Reviewing the drafted outputs and applying grounded corrections.",
    value: 63,
  },
  {
    title: "Builder agent",
    detail:
      "Packaging the final tailored resume and lining up the finish.",
    value: 84,
  },
  {
    title: "Cover letter agent",
    detail:
      "Turning the approved story into a role-specific cover letter that is ready to send.",
    value: 97,
  },
];

export type UseAnalysisJobOptions = {
  resumeText: string;
  jobDescriptionText: string;
  resumeFiletype: string | undefined;
  resumeSource: string | undefined;
  importedJobPosting: JobPosting | null;
  authTokens: AuthTokens | null;
  setNotice: (notice: Notice) => void;
  /**
   * Owner of the canonical `analysisState`. Polling completion calls
   * this to publish the result so other hooks (artifact preview,
   * assistant history) that depend on `analysisState` can react.
   * Owning it in the parent rather than the hook avoids a circular
   * dependency between the analysis hook and the artifact hook.
   */
  setAnalysisState: Dispatch<
    SetStateAction<WorkspaceAnalysisResponse | null>
  >;
  /**
   * Called once the workflow completes successfully. Receives the
   * snapshot result and returns the success notice message (which
   * will be applied by the hook, gated on the cancellation check).
   * The body fires regardless of cancellation so synchronous side
   * effects (e.g. switching tabs, resetting artifacts) match the
   * pre-extraction behavior.
   */
  onCompleted: (
    result: WorkspaceAnalysisResponse,
  ) => Promise<string> | string;
};

export type UseAnalysisJobReturn = {
  analysisLoading: boolean;
  analysisJobState: WorkspaceAnalysisJobStatusResponse | null;
  setAnalysisJobState: Dispatch<
    SetStateAction<WorkspaceAnalysisJobStatusResponse | null>
  >;
  currentWorkflowStage: WorkflowStage | null;
  runAnalysis: () => Promise<void>;
  /** Used by `clearWorkspaceRole`. Resets job-state-only (the parent
   *  owns and resets `analysisState`). */
  resetAnalysis: () => void;
};

export function useAnalysisJob({
  resumeText,
  jobDescriptionText,
  resumeFiletype,
  resumeSource,
  importedJobPosting,
  authTokens,
  setNotice,
  setAnalysisState,
  onCompleted,
}: UseAnalysisJobOptions): UseAnalysisJobReturn {
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisRunMode, setAnalysisRunMode] =
    useState<WorkflowRunMode | null>(null);
  const [analysisJobState, setAnalysisJobState] =
    useState<WorkspaceAnalysisJobStatusResponse | null>(null);

  // Stabilize parent-supplied callbacks so the polling effect doesn't
  // tear down on every parent re-render. Without this, the 1200ms
  // setTimeout would be cleared and rescheduled before it ever fires.
  const setNoticeRef = useRef(setNotice);
  const onCompletedRef = useRef(onCompleted);
  const setAnalysisStateRef = useRef(setAnalysisState);
  useEffect(() => {
    setNoticeRef.current = setNotice;
    onCompletedRef.current = onCompleted;
    setAnalysisStateRef.current = setAnalysisState;
  });

  const workflowStages = useMemo(() => {
    if (analysisRunMode === "agentic") {
      return AGENTIC_WORKFLOW_STAGES;
    }
    return [] as WorkflowStage[];
  }, [analysisRunMode]);

  const currentWorkflowStage = useMemo(() => {
    if (!analysisLoading || analysisRunMode !== "agentic") {
      return null;
    }
    if (!analysisJobState?.stage_title) {
      return workflowStages[0] ?? null;
    }
    return (
      workflowStages.find(
        (stage) => stage.title === analysisJobState.stage_title,
      ) ?? {
        title: analysisJobState.stage_title,
        detail:
          analysisJobState.stage_detail ||
          "The workspace crew is moving through the run.",
        value: analysisJobState.progress_percent || 3,
      }
    );
  }, [analysisJobState, analysisLoading, analysisRunMode, workflowStages]);

  // Polling state machine.
  useEffect(() => {
    if (
      !analysisLoading ||
      analysisRunMode !== "agentic" ||
      !analysisJobState?.job_id ||
      analysisJobState.status === "completed" ||
      analysisJobState.status === "failed"
    ) {
      return;
    }

    let cancelled = false;

    const timeout = window.setTimeout(async () => {
      try {
        const nextJobState = await getWorkspaceAnalysisJob(
          analysisJobState.job_id,
          authTokens,
        );
        if (cancelled) {
          return;
        }

        setAnalysisJobState(nextJobState);

        if (nextJobState.status === "completed" && nextJobState.result) {
          setAnalysisStateRef.current(nextJobState.result);
          const message = await onCompletedRef.current(nextJobState.result);
          if (!cancelled) {
            setNoticeRef.current({ level: "success", message });
            setAnalysisLoading(false);
            setAnalysisRunMode(null);
          }
          return;
        }

        if (nextJobState.status === "failed") {
          setNoticeRef.current({
            level: "warning",
            message:
              nextJobState.error_message ||
              "The agentic workflow failed unexpectedly.",
          });
          setAnalysisLoading(false);
          setAnalysisRunMode(null);
          return;
        }
      } catch (error) {
        if (!cancelled) {
          setNoticeRef.current({
            level: "warning",
            message:
              error instanceof Error
                ? error.message
                : "Workflow status polling failed unexpectedly.",
          });
          setAnalysisLoading(false);
          setAnalysisRunMode(null);
        }
      }
    }, 1200);

    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
    };
  }, [analysisJobState, analysisLoading, analysisRunMode, authTokens]);

  async function runAnalysis() {
    if (!resumeText.trim()) {
      setNotice({
        level: "warning",
        message: "Upload and parse a resume before running the workspace flow.",
      });
      return;
    }

    if (!jobDescriptionText.trim()) {
      setNotice({
        level: "warning",
        message:
          "Load or paste a job description before running the workspace flow.",
      });
      return;
    }

    if (!authTokens) {
      setNotice({
        level: "warning",
        message: "Sign in with Google before running the AI-assisted workflow.",
      });
      return;
    }

    setAnalysisRunMode("agentic");
    setAnalysisJobState({
      job_id: "",
      status: "queued",
      stage_title: "Workflow crew",
      stage_detail:
        "Opening your application brief and preparing the first agent.",
      progress_percent: 3,
      result: null,
      error_message: null,
    });
    setAnalysisLoading(true);
    setNotice({
      level: "info",
      message:
        "Running the agentic workflow now. The workspace crew will keep you posted as each stage moves.",
    });

    try {
      const response = await startWorkspaceAnalysisJob(
        {
          resume_text: resumeText,
          resume_filetype: resumeFiletype ?? "TXT",
          resume_source: resumeSource ?? "workspace",
          job_description_text: jobDescriptionText.trim(),
          imported_job_posting: importedJobPosting,
          run_assisted: true,
        },
        authTokens,
      );
      setAnalysisJobState({
        ...response,
        result: null,
        error_message: null,
      });
    } catch (error) {
      const errorMessage =
        error instanceof Error
          ? error.message
          : "Workspace analysis failed unexpectedly.";
      setNotice({
        level: "warning",
        message: errorMessage,
      });
      setAnalysisLoading(false);
      setAnalysisRunMode(null);
      setAnalysisJobState(null);
    }
  }

  function resetAnalysis() {
    setAnalysisJobState(null);
  }

  return {
    analysisLoading,
    analysisJobState,
    setAnalysisJobState,
    currentWorkflowStage,
    runAnalysis,
    resetAnalysis,
  };
}
