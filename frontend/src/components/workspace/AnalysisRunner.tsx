"use client";

// Workflow run + progress card — Direction B redesign.
//
// Behavior preservation:
//   - "Run analysis" disabled until parent reports `ready` (resume + JD)
//   - useAnalysisJob polling drives `currentWorkflowStage`; pipeline
//     reflects that. The `analysisJobState.progress_percent` overrides
//     the stage's static value when present.
//   - Stale notice + Clear-role action retained.
//
// Layout (per handoff specs/04-analysis.md):
//   1. Region head (title + STEP 04 tag)
//   2. b-run-bar — status pip, Re-run / Clear actions
//   3. b-pipeline — multi-column stage cards with active glow
//
// The ArtifactViewer that renders below this component on the same tab
// is its own sibling component — no change here.

import type {
  WorkspaceAnalysisJobStatusResponse,
  WorkspaceAnalysisResponse,
} from "@/lib/api-types";
import { PlayIcon } from "@/components/workspace/icons";

export type WorkflowStage = {
  title: string;
  detail: string;
  value: number;
};

export type AnalysisRunnerProps = {
  analysisState: WorkspaceAnalysisResponse | null;
  analysisLoading: boolean;
  analysisJobState: WorkspaceAnalysisJobStatusResponse | null;
  analysisIsStale: boolean;
  currentWorkflowStage: WorkflowStage | null;
  onRunAnalysis: () => void;
  onClearRole: () => void;
  /** True when both a resume + JD are present. */
  ready: boolean;
};

// Pipeline stages shown in the redesigned layout. The actual progress
// values come from `currentWorkflowStage` + `analysisJobState`; this
// list defines the order and labels.
const PIPELINE_STAGE_ORDER = [
  "Workflow crew",
  "Matchmaker agent",
  "Forge agent",
  "Gatekeeper agent",
  "Builder agent",
  "Cover letter agent",
];

export function AnalysisRunner({
  analysisState,
  analysisLoading,
  analysisJobState,
  analysisIsStale,
  currentWorkflowStage,
  onRunAnalysis,
  onClearRole,
  ready,
}: AnalysisRunnerProps) {
  const liveStageTitle = currentWorkflowStage?.title ?? null;
  const livePercent =
    analysisJobState?.progress_percent ?? currentWorkflowStage?.value ?? null;

  // Build the pipeline view: each stage has a state (done/active/next)
  // and a value. We mark stages BEFORE the live one as done, the live
  // one as active w/ the live percent, and stages AFTER as next.
  // After analysis completes, every stage ticks to done.
  const liveIndex = liveStageTitle
    ? PIPELINE_STAGE_ORDER.indexOf(liveStageTitle)
    : -1;

  const stages = PIPELINE_STAGE_ORDER.map((title, index) => {
    let state: "done" | "active" | "next" = "next";
    let value = 0;
    let detail = "";

    if (analysisState) {
      state = "done";
      value = 100;
    } else if (analysisLoading) {
      if (liveIndex >= 0) {
        if (index < liveIndex) {
          state = "done";
          value = 100;
        } else if (index === liveIndex) {
          state = "active";
          value = livePercent ?? 50;
          detail = currentWorkflowStage?.detail ?? "";
        }
      } else if (index === 0) {
        state = "active";
        value = livePercent ?? 25;
        detail = "Coordinating agents";
      }
    }
    return { title, state, value, detail };
  });

  return (
    <div className="b-region">
      <div className="b-region-head">
        <div>
          <div className="b-region-title">Workflow run</div>
          <div className="b-region-sub">
            {analysisState
              ? `${analysisState.workflow.mode} · ${
                  analysisState.workflow.review_approved
                    ? "review approved"
                    : "review pending"
                }`
              : analysisLoading
                ? "Generating tailored documents…"
                : ready
                  ? "Ready to run — both inputs are loaded."
                  : "Need a parsed resume + JD to run."}
          </div>
        </div>
        <span className="b-region-tag">STEP 04</span>
      </div>

      <div className="b-run-bar">
        <div className="b-run-bar-info">
          <span
            className={
              analysisState
                ? "rd-pip rd-pip-live"
                : analysisLoading
                  ? "rd-pip rd-pip-ready"
                  : "rd-pip"
            }
          >
            {analysisState
              ? "Outputs ready"
              : analysisLoading
                ? "Running…"
                : ready
                  ? "Idle"
                  : "Inputs needed"}
          </span>
          {currentWorkflowStage && analysisLoading ? (
            <span style={{ fontSize: 13, color: "var(--fg-3)" }}>
              {currentWorkflowStage.title} · {analysisJobState?.stage_detail ??
                currentWorkflowStage.detail}
            </span>
          ) : null}
        </div>
        <div className="b-run-bar-actions">
          <button
            className="rd-btn rd-btn-primary rd-btn-sm"
            disabled={!ready || analysisLoading}
            onClick={onRunAnalysis}
            type="button"
          >
            <PlayIcon /> {analysisLoading ? "Running…" : analysisState ? "Re-run" : "Run analysis"}
          </button>
          <button
            className="rd-btn rd-btn-danger rd-btn-sm"
            disabled={analysisLoading}
            onClick={onClearRole}
            type="button"
          >
            Clear role
          </button>
        </div>
      </div>

      {analysisIsStale ? (
        <div className="b-notice b-notice-warning">
          The inputs changed after the last run. Re-run the workflow to refresh
          your documents.
        </div>
      ) : null}

      <div className="b-pipeline">
        {stages.map((stage) => (
          <div
            className="b-pipeline-stage"
            data-state={stage.state}
            key={stage.title}
          >
            <div className="b-pipeline-stage-head">
              <span className="b-pipeline-stage-name">{stage.title}</span>
              <span className="b-pipeline-stage-percent">
                {Math.round(stage.value)}%
              </span>
            </div>
            <div className="b-pipeline-stage-detail">
              {stage.state === "active" && stage.detail
                ? stage.detail
                : stage.state === "done"
                  ? "Complete"
                  : "Standby"}
            </div>
            <div aria-hidden="true" className="b-pipeline-stage-bar">
              <span style={{ width: `${stage.value}%` }} />
            </div>
          </div>
        ))}
      </div>

      {!analysisState && !analysisLoading ? (
        <div className="b-twoup-empty">
          {ready
            ? "Run the workflow once to unlock your tailored documents."
            : "Add a parsed resume and JD before running the analysis."}
        </div>
      ) : null}
    </div>
  );
}
