"use client";

// Workflow run + progress card — extracted from
// `job-application-workspace.tsx` as part of the Item 2 frontend split
// (see `docs/NEXT-STEPS-FRONTEND.md`).
//
// Owns the markup for `mainTab === "analysis"`'s first section. The
// ArtifactViewer that lives next to it on the same tab is its own
// component and stays a sibling in the parent.

import type {
  WorkspaceAnalysisJobStatusResponse,
  WorkspaceAnalysisResponse,
} from "@/lib/api-types";

export type WorkflowStage = {
  title: string;
  detail: string;
  value: number;
};

function workflowProgressTone(title: string) {
  if (title === "Workflow crew") return "crew";
  if (title === "Backup workflow") return "backup";
  if (title === "Matchmaker agent") return "matchmaker";
  if (title === "Forge agent") return "forge";
  if (title === "Gatekeeper agent") return "gatekeeper";
  if (title === "Builder agent") return "builder";
  if (title === "Cover letter agent") return "coverletter";
  return "crew";
}

export type AnalysisRunnerProps = {
  analysisState: WorkspaceAnalysisResponse | null;
  analysisLoading: boolean;
  analysisJobState: WorkspaceAnalysisJobStatusResponse | null;
  analysisIsStale: boolean;
  currentWorkflowStage: WorkflowStage | null;
  onRunAnalysis: () => void;
  onClearRole: () => void;
};

export function AnalysisRunner({
  analysisState,
  analysisLoading,
  analysisJobState,
  analysisIsStale,
  currentWorkflowStage,
  onRunAnalysis,
  onClearRole,
}: AnalysisRunnerProps) {
  return (
    <section className="surface-card surface-card-neutral">
      <div className="section-head">
        <div>
          <p className="eyebrow">Run</p>
          <h2 className="section-title">Build the workspace package</h2>
        </div>
        <span className="status-chip">
          {analysisState ? analysisState.workflow.mode : "Not run yet"}
        </span>
      </div>
      <p className="section-copy">
        Run the agentic workflow once your resume and job description are
        ready.
      </p>

      <div className="workspace-run-actions">
        <button
          className="primary-button workspace-button"
          disabled={analysisLoading}
          onClick={onRunAnalysis}
          type="button"
        >
          {analysisLoading ? "Running..." : "Run workflow"}
        </button>
        <button
          className="danger-button workspace-button workspace-action-end"
          onClick={onClearRole}
          type="button"
        >
          Clear role
        </button>
      </div>

      {analysisLoading && currentWorkflowStage ? (
        <div
          className={`workspace-progress-card workspace-progress-tone-${workflowProgressTone(
            currentWorkflowStage.title,
          )}`}
        >
          <div className="workspace-progress-head">
            <span className="workspace-progress-tag">
              {currentWorkflowStage.title}
            </span>
            <span className="workspace-progress-percent">
              {analysisJobState?.progress_percent ??
                currentWorkflowStage.value}
              %
            </span>
          </div>
          <p className="workspace-progress-detail">
            {analysisJobState?.stage_detail ?? currentWorkflowStage.detail}
          </p>
          <div aria-hidden="true" className="workspace-progress-bar">
            <span
              style={{
                width: `${
                  analysisJobState?.progress_percent ??
                  currentWorkflowStage.value
                }%`,
              }}
            />
          </div>
          <div className="workspace-progress-stage-list">
            <div className="workspace-progress-stage workspace-progress-stage-live">
              <span className="workspace-progress-stage-title">
                {currentWorkflowStage.title}
              </span>
              <small>
                {analysisJobState?.stage_detail ?? currentWorkflowStage.detail}
              </small>
            </div>
          </div>
          <p className="workspace-muted-copy workspace-progress-note">
            This card now follows the real backend stage instead of stepping
            forward on a timer.
          </p>
        </div>
      ) : null}

      {analysisIsStale ? (
        <div className="notice-panel notice-warning">
          The inputs changed after the last run. Re-run the workflow to refresh
          your documents.
        </div>
      ) : null}

      {analysisState ? (
        <></>
      ) : (
        <div className="workspace-empty-state">
          Run the workflow once to unlock your tailored documents.
        </div>
      )}
    </section>
  );
}
