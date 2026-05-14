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
  WorkspaceQuotaResponse,
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
  /** Quota snapshot from GET /workspace/quota. Null when anonymous,
   *  auth restoring, or the fetch failed — the toggle renders in the
   *  disabled state in that case (the safe default). */
  quota: WorkspaceQuotaResponse | null;
  /** Premium toggle state. True = user wants to run this workflow on
   *  gpt-5.5 (Pro+/Business only). Free tier never reaches this with
   *  premium=true because the toggle is disabled when
   *  `quota.premium_available` is false. */
  premium: boolean;
  /** Setter for the toggle. The parent (WorkspaceShell) owns the
   *  state because both this component and the run-hook need to read
   *  it. */
  onPremiumChange: (next: boolean) => void;
};

// Pipeline stages shown in the redesigned layout.
//
// Each stage carries:
//   - `key`: backend `stage_title` (must match useAnalysisJob's
//     AGENTIC_WORKFLOW_STAGES so we can locate the live stage).
//   - `displayTitle`: user-facing action label, e.g. "Drafting
//     tailored resume". This is the primary text the user sees.
//   - `agentLabel`: which background agent owns this step. Surfaced
//     as a small mono badge so users understand WHO is doing it,
//     without needing to know what a "Forge agent" is up front.
//
// Progress values still come from `currentWorkflowStage` +
// `analysisJobState`; this list only controls order + labels.
type PipelineStageDef = {
  key: string;
  displayTitle: string;
  agentLabel: string;
};
const PIPELINE_STAGES: PipelineStageDef[] = [
  {
    key: "Workflow crew",
    displayTitle: "Reading inputs",
    agentLabel: "Workflow crew",
  },
  {
    key: "Matchmaker agent",
    displayTitle: "Scoring role fit",
    agentLabel: "Matchmaker agent",
  },
  {
    key: "Forge agent",
    displayTitle: "Drafting tailored resume",
    agentLabel: "Forge agent",
  },
  {
    key: "Gatekeeper agent",
    displayTitle: "Reviewing outputs",
    agentLabel: "Gatekeeper agent",
  },
  {
    key: "Builder agent",
    displayTitle: "Final assembly",
    agentLabel: "Builder agent",
  },
  {
    key: "Cover letter agent",
    displayTitle: "Drafting cover letter",
    agentLabel: "Cover letter agent",
  },
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
  quota,
  premium,
  onPremiumChange,
}: AnalysisRunnerProps) {
  // Premium toggle gating logic.
  //   * Disabled when quota is null (anonymous / restoring / fetch
  //     failed) — the safe default.
  //   * Disabled when `quota.premium_available` is false (Free tier).
  //   * Disabled while a workflow is running — no point letting the
  //     user flip mid-run.
  //
  // The tooltip copy adapts: when premium isn't available we point
  // at the upgrade page; when it IS available we surface the
  // remaining credits.
  const premiumAvailable = Boolean(quota?.premium_available);
  const premiumCounter = quota?.counters.premium_applications ?? null;
  const premiumRemaining = premiumCounter?.remaining ?? 0;
  const premiumLimit = premiumCounter?.limit ?? 0;
  const premiumOutOfCredits =
    premiumAvailable && premiumLimit > 0 && premiumRemaining <= 0;
  const premiumDisabled =
    !premiumAvailable || analysisLoading || premiumOutOfCredits;
  const premiumTooltip = !premiumAvailable
    ? "Upgrade to Pro for premium AI (GPT-5.5)"
    : premiumOutOfCredits
      ? "You've used all your premium credits this month"
      : `${premiumRemaining} of ${premiumLimit} premium credits left this month`;
  const liveStageTitle = currentWorkflowStage?.title ?? null;
  const livePercent =
    analysisJobState?.progress_percent ?? currentWorkflowStage?.value ?? null;

  // Build the pipeline view: each stage has a state (done/active/next)
  // and a value. We mark stages BEFORE the live one as done, the live
  // one as active w/ the live percent, and stages AFTER as next.
  // After analysis completes, every stage ticks to done.
  const liveIndex = liveStageTitle
    ? PIPELINE_STAGES.findIndex((stage) => stage.key === liveStageTitle)
    : -1;

  const stages = PIPELINE_STAGES.map((stage, index) => {
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
    return { ...stage, state, value, detail };
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
          <label
            className="b-premium-toggle"
            data-disabled={premiumDisabled ? "true" : "false"}
            data-active={premium && !premiumDisabled ? "true" : "false"}
            title={premiumTooltip}
          >
            <input
              aria-label="Run with premium AI (GPT-5.5)"
              checked={premium && !premiumDisabled}
              disabled={premiumDisabled}
              onChange={(event) => onPremiumChange(event.target.checked)}
              type="checkbox"
            />
            <span className="b-premium-toggle-label">
              Premium
              {premiumAvailable && premiumLimit > 0 ? (
                <span className="b-premium-toggle-count">
                  {premiumRemaining}/{premiumLimit}
                </span>
              ) : null}
            </span>
          </label>
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
            key={stage.key}
          >
            <div className="b-pipeline-stage-head">
              <span className="b-pipeline-stage-name">
                {stage.displayTitle}
              </span>
              <span className="b-pipeline-stage-percent">
                {Math.round(stage.value)}%
              </span>
            </div>
            <div className="b-pipeline-stage-agent-row">
              <span className="b-pipeline-stage-agent">
                {stage.agentLabel}
              </span>
              <span className="b-pipeline-stage-state">
                {stage.state === "done"
                  ? "complete"
                  : stage.state === "active"
                    ? "running"
                    : "standby"}
              </span>
            </div>
            <div className="b-pipeline-stage-detail">
              {stage.state === "active" && stage.detail
                ? stage.detail
                : stage.state === "done"
                  ? "All done — output committed."
                  : "Waiting its turn."}
            </div>
            <div aria-hidden="true" className="b-pipeline-stage-bar">
              <span style={{ width: `${stage.value}%` }} />
            </div>
          </div>
        ))}
      </div>

      {/* Mobile-only: when every agent has finished, the 6 "All done"
          cards add nothing — collapse them to a single confirmation
          line. Hidden on desktop via CSS. The pipeline cards
          themselves are also hidden on mobile in the idle / all-done
          states (see globals.css mobile pass). */}
      {analysisState ? (
        <div className="b-pipeline-summary" role="status">
          <span aria-hidden="true" className="b-pipeline-summary-pip">
            ✓
          </span>
          <span>
            All {PIPELINE_STAGES.length} agents finished — your tailored
            documents are ready below.
          </span>
        </div>
      ) : null}

      {!analysisState && !analysisLoading ? (
        <div className="b-empty-hint">
          <div className="b-empty-hint-eyebrow">Once the workflow runs</div>
          <div className="b-empty-hint-body">
            {ready
              ? "Press Run analysis above to unlock your tailored resume + cover letter. Each agent posts its progress here as it works."
              : "Add a parsed resume and a job description before running the analysis. The Documents section below will fill in once the workflow completes."}
          </div>
        </div>
      ) : null}
    </div>
  );
}
