"use client";

// Artifact viewer (Resume / Cover Letter tabs + preview iframe + export
// buttons) — extracted from `job-application-workspace.tsx` as part of
// the Item 2 frontend split (see `docs/NEXT-STEPS-FRONTEND.md`).
//
// Today this is a "use client" island that consumes preview HTML and
// export handlers from the parent. The handoff suggests rendering
// markdown → HTML server-side as a future optimisation; that's a
// separate follow-up and not part of Item 2.

import type { WorkspaceArtifactKind } from "@/lib/api-types";

export type ArtifactTab = "resume" | "cover-letter";

export type ArtifactExportFormat = "markdown" | "pdf";

export type ArtifactViewerArtifact = {
  title: string;
  summary: string;
};

const TAB_LABELS: Record<ArtifactTab, string> = {
  resume: "Tailored Resume",
  "cover-letter": "Cover Letter",
};

const TAB_ORDER: ArtifactTab[] = ["resume", "cover-letter"];

function kindForTab(
  tab: ArtifactTab,
): Exclude<WorkspaceArtifactKind, "bundle" | "report"> {
  return tab === "resume" ? "tailored_resume" : "cover_letter";
}

export type ArtifactViewerProps = {
  /** Whether a workspace analysis run has produced artifacts. */
  hasAnalysis: boolean;
  /** Currently-selected artifact (title + summary). `null` while loading. */
  artifact: ArtifactViewerArtifact | null;
  tab: ArtifactTab;
  onTabChange: (tab: ArtifactTab) => void;
  /**
   * Key of the export currently in flight, formatted as
   * `${artifactKind}:${exportFormat}` (e.g. `"tailored_resume:pdf"`).
   * `null` when no export is in progress. Matches the parent's
   * `artifactExporting` state.
   */
  exporting: string | null;
  previewHtml: string | null;
  previewTitle: string | null;
  previewLoading: boolean;
  onExport: (kind: WorkspaceArtifactKind, format: ArtifactExportFormat) => void;
};

export function ArtifactViewer({
  hasAnalysis,
  artifact,
  tab,
  onTabChange,
  exporting,
  previewHtml,
  previewTitle,
  previewLoading,
  onExport,
}: ArtifactViewerProps) {
  const artifactKind = kindForTab(tab);

  return (
    <section className="surface-card surface-card-neutral">
      <div className="section-head">
        <div>
          <p className="eyebrow">Outputs</p>
          <h2 className="section-title">Documents</h2>
        </div>
        <span className="status-chip">
          {hasAnalysis ? "Ready to review" : "Waiting for run"}
        </span>
      </div>
      <p className="section-copy">Review and download your documents.</p>

      {hasAnalysis ? (
        <>
          <div className="workspace-tab-row">
            {TAB_ORDER.map((value) => (
              <button
                className={
                  tab === value
                    ? "inspector-tab inspector-tab-active"
                    : "inspector-tab"
                }
                key={value}
                onClick={() => onTabChange(value)}
                type="button"
              >
                {TAB_LABELS[value]}
              </button>
            ))}
          </div>

          {artifact ? (
            <div className="workspace-artifact-panel">
              <div className="workspace-artifact-head">
                <div>
                  <p className="workspace-label">Current document</p>
                  <h3 className="workspace-role-title">{artifact.title}</h3>
                  <p className="workspace-role-copy">{artifact.summary}</p>
                </div>
                <div className="workspace-artifact-actions">
                  <button
                    className="secondary-button workspace-button workspace-button-small"
                    disabled={exporting !== null}
                    onClick={() => onExport(artifactKind, "markdown")}
                    type="button"
                  >
                    {exporting === `${artifactKind}:markdown`
                      ? "Preparing..."
                      : "Download Markdown"}
                  </button>
                  <button
                    className="secondary-button workspace-button workspace-button-small"
                    disabled={exporting !== null}
                    onClick={() => onExport(artifactKind, "pdf")}
                    type="button"
                  >
                    {exporting === `${artifactKind}:pdf`
                      ? "Preparing..."
                      : "Download PDF"}
                  </button>
                </div>
              </div>

              <div className="workspace-section-card">
                <h3>Preview</h3>
                <p className="workspace-muted-copy">
                  {previewTitle
                    ? `Preview of ${previewTitle}.`
                    : "A preview of the current document will appear here once it is ready."}
                </p>
                {previewLoading ? (
                  <div className="workspace-empty-state">
                    Preparing the artifact preview...
                  </div>
                ) : previewHtml ? (
                  <iframe
                    className="workspace-artifact-preview-frame"
                    srcDoc={previewHtml}
                    title={`${TAB_LABELS[tab]} preview`}
                  />
                ) : (
                  <div className="workspace-empty-state">
                    The artifact preview is temporarily unavailable, but the
                    download actions still work.
                  </div>
                )}
              </div>
            </div>
          ) : null}
        </>
      ) : (
        <div className="workspace-empty-state">
          The tailored resume and cover letter will appear here after the
          workflow runs.
        </div>
      )}
    </section>
  );
}
