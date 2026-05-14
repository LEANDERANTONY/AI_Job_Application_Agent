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
  TierLimitExceededError,
} from "@/lib/api";
import type {
  JobPosting,
  WorkspaceAnalysisJobStatusResponse,
  WorkspaceAnalysisResponse,
} from "@/lib/api-types";
import { humanizeApiError } from "@/lib/humanizeApiError";
import type { WorkflowStage } from "@/components/workspace/AnalysisRunner";

type Notice =
  | {
      level: "info" | "success" | "warning";
      message: string;
      /** Optional CTA (Step 7b). When set, the workspace renders an
       *  "Upgrade" link next to the message. Used for tier-limit
       *  429 toasts; left undefined for plain notices. */
      action?: { label: string; href: string };
    }
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
  authStatus: "loading" | "restoring" | "signed_out" | "signed_in";
  /** Whether the user has opted into per-run premium routing via
   *  the Premium toggle (Step 7b). The toggle is gated by
   *  `premium_available` from /workspace/quota; the parent passes
   *  the current toggle state here so each run picks up the latest
   *  value without the hook owning the toggle state itself. */
  premium?: boolean;
  /** Called after each run finishes (success OR failure), so the
   *  parent can refetch /workspace/quota and keep the toggle's
   *  indicator in sync with the actual backend state. */
  onRunFinished?: () => void;
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
  authStatus,
  premium,
  onRunFinished,
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
  const onRunFinishedRef = useRef(onRunFinished);
  useEffect(() => {
    setNoticeRef.current = setNotice;
    onCompletedRef.current = onCompleted;
    setAnalysisStateRef.current = setAnalysisState;
    onRunFinishedRef.current = onRunFinished;
  });

  // True until the hook unmounts. Distinct from the polling effect's
  // local `cancelled` flag, which flips every time the effect re-runs
  // (including in response to our own state setters). The post-await
  // success-notice path gates on this so it survives the self-induced
  // cleanup that fires when we publish the completed job state.
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

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
        );
        if (cancelled) {
          return;
        }

        setAnalysisJobState(nextJobState);

        if (nextJobState.status === "completed" && nextJobState.result) {
          // Flip the running flags + publish the snapshot synchronously
          // BEFORE the persistLatestWorkspace await below. Otherwise our
          // own setAnalysisJobState(nextJobState) above triggers the
          // polling effect's cleanup → cancelled becomes true →
          // every post-await reset gets dropped, leaving the UI stuck
          // on "Running…" even though `analysisState` is already set.
          setAnalysisStateRef.current(nextJobState.result);
          setAnalysisLoading(false);
          setAnalysisRunMode(null);
          const message = await onCompletedRef.current(nextJobState.result);
          // Notice is gated on real unmount, not on the polling
          // effect's self-induced cancellation.
          if (mountedRef.current) {
            setNoticeRef.current({ level: "success", message });
          }
          // Tell the parent to refetch /workspace/quota — the run
          // consumed a tailored_applications (or premium_applications)
          // credit, so the toggle's "X of Y remaining" indicator
          // needs to update.
          onRunFinishedRef.current?.();
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
          // Refetch quota on failure too — the backend's refund-on-
          // failure path SHOULD have rolled the credit back, but
          // we re-sync to be sure the indicator reflects truth.
          onRunFinishedRef.current?.();
          return;
        }
      } catch (error) {
        if (!cancelled) {
          setNoticeRef.current({
            level: "warning",
            message: humanizeApiError(
              error,
              "Workflow status polling failed unexpectedly.",
            ),
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
  }, [analysisJobState, analysisLoading, analysisRunMode]);

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

    if (authStatus !== "signed_in") {
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
      const response = await startWorkspaceAnalysisJob({
        resume_text: resumeText,
        resume_filetype: resumeFiletype ?? "TXT",
        resume_source: resumeSource ?? "workspace",
        job_description_text: jobDescriptionText.trim(),
        imported_job_posting: importedJobPosting,
        run_assisted: true,
        // Premium opts the workflow into gpt-5.5 for the three
        // high-trust agents AND burns a `premium_applications`
        // credit. The Premium toggle is disabled for Free tier
        // (premium_available=false on /workspace/quota), so this
        // value should already be safe by the time we get here.
        // Defensive: the backend rejects free+premium=true with a
        // 429, which surfaces as TierLimitExceededError below.
        premium: Boolean(premium),
      });
      setAnalysisJobState({
        ...response,
        result: null,
        error_message: null,
      });
    } catch (error) {
      // Tier-limit 429s get a specialized notice with an Upgrade CTA
      // — separate code path from the generic warning so the toast
      // can deep-link to the pricing page. The error's `detail`
      // already carries a user-friendly message ("You have reached
      // your X cap, upgrade to continue.").
      if (error instanceof TierLimitExceededError) {
        setNotice({
          level: "warning",
          message: error.message,
          action: {
            label: "Upgrade plan",
            // Hardcoded production landing path — the upgrade page
            // URL also rides on the /workspace/quota response, but
            // we don't have access to it in this catch branch and
            // the path is stable across environments. The link
            // opens in a new tab so the in-flight workspace state
            // isn't lost.
            href: "/pricing",
          },
        });
      } else {
        setNotice({
          level: "warning",
          message: humanizeApiError(error, "Workspace analysis failed unexpectedly."),
        });
      }
      setAnalysisLoading(false);
      setAnalysisRunMode(null);
      setAnalysisJobState(null);
      // Even on failure the parent should refetch quota — a 429
      // doesn't burn credit, but a transient backend error might
      // still have rotated the counter (and a refund-failure path
      // would have shifted it too). Mirrors HelpmateAI's pattern of
      // "refetch after every run, win or lose".
      onRunFinishedRef.current?.();
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
