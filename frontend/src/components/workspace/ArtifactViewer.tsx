"use client";

// Artifact viewer (Resume / Cover Letter tabs + preview iframe + export
// buttons) — Direction B redesign.
//
// Behavior preservation:
//   - Tabs: Tailored Resume | Cover Letter (parent owns artifactTab)
//   - PDF / DOCX download buttons → onExport(kind, format)
//   - Server-rendered preview iframe via previewHtml
//   - Loading + missing-preview fallbacks retained
//
// Layout (per handoff specs/04-analysis.md):
//   - b-artifact-tabs — pill row above the doc
//   - b-artifact-body — 2-col grid: doc body (iframe) + right-rail
//   - b-artifact-aside — title, summary, download buttons, meta line

import { FeedbackButtons } from "@/components/workspace/FeedbackButtons";
import type { ArtifactTheme, WorkspaceArtifactKind } from "@/lib/api-types";

export type ArtifactTab = "resume" | "cover-letter";

// DOCX replaces markdown export; markdown is no longer a download
// option (the artifact's `markdown` content field is still used for
// the in-app preview, but it is not surfaced as a download).
export type ArtifactExportFormat = "pdf" | "docx";

export type ArtifactViewerArtifact = {
  title: string;
  summary: string;
};

// professional_neutral is the product-wide default + the Free-tier
// theme — listed first. classic_ats is the Pro/Business alternate.
const THEME_OPTIONS: { value: ArtifactTheme; label: string }[] = [
  { value: "professional_neutral", label: "Professional" },
  { value: "classic_ats", label: "Classic ATS" },
];

const THEME_HINT: Record<ArtifactTheme, string> = {
  classic_ats:
    "Warm cream paper, brown accents — distinctive, design-forward. Good for startups, design-eng, modern tech.",
  professional_neutral:
    "Pure black on white, no color. Conservative; safer for Big Tech recruiting at scale, banks, defense, or B&W printing.",
};

const TAB_LABELS: Record<ArtifactTab, string> = {
  resume: "Tailored Resume",
  "cover-letter": "Cover Letter",
};

const TAB_ORDER: ArtifactTab[] = ["resume", "cover-letter"];

function kindForTab(
  tab: ArtifactTab,
): WorkspaceArtifactKind {
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
   * `null` when no export is in progress.
   */
  exporting: string | null;
  previewHtml: string | null;
  previewTitle: string | null;
  previewLoading: boolean;
  /**
   * Theme of the currently-active artifact (resume theme when on the
   * resume tab, cover-letter theme when on the cover letter tab). The
   * picker writes back via onThemeChange.
   */
  activeTheme: ArtifactTheme;
  onThemeChange: (theme: ArtifactTheme) => void;
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
  activeTheme,
  onThemeChange,
  onExport,
}: ArtifactViewerProps) {
  const artifactKind = kindForTab(tab);

  if (!hasAnalysis) {
    return (
      <div className="b-region">
        <div className="b-region-head">
          <div>
            <div className="b-region-title">Documents</div>
            <div className="b-region-sub">
              The tailored resume and cover letter appear here after the run.
            </div>
          </div>
        </div>
        <div className="b-twoup-empty">
          Run the workflow first — artifact previews and downloads unlock once
          the analysis completes.
        </div>
      </div>
    );
  }

  return (
    <div className="b-region">
      <div className="b-region-head">
        <div>
          <div className="b-region-title">Documents</div>
          <div className="b-region-sub">
            Review and download your tailored package.
          </div>
        </div>
      </div>

      <div className="b-artifact-tabs" role="tablist">
        {TAB_ORDER.map((value) => (
          <button
            aria-selected={tab === value}
            className="b-artifact-tab"
            key={value}
            onClick={() => onTabChange(value)}
            role="tab"
            type="button"
          >
            {TAB_LABELS[value]}
          </button>
        ))}
      </div>

      <div className="b-artifact-body">
        <div className="b-artifact-doc">
          {previewLoading ? (
            <div className="b-twoup-empty" style={{ padding: 24 }}>
              Preparing the artifact preview…
            </div>
          ) : previewHtml ? (
            <iframe
              className="b-artifact-doc-frame"
              srcDoc={previewHtml}
              title={`${TAB_LABELS[tab]} preview`}
            />
          ) : (
            <div className="b-twoup-empty" style={{ padding: 24 }}>
              The artifact preview is temporarily unavailable, but the download
              actions still work.
            </div>
          )}
        </div>

        <div className="b-artifact-aside">
          <h4 className="b-artifact-aside-title">
            {artifact?.title ?? TAB_LABELS[tab]}
          </h4>
          {artifact?.summary ? (
            <p className="b-artifact-aside-text">{artifact.summary}</p>
          ) : null}
          <hr className="rd-hairline" />
          {/* Per-artifact theme picker. The user picks a treatment for
              each document independently — e.g. classic_ats resume +
              professional_neutral cover letter. The preview iframe and
              the PDF download both pick up the change. */}
          <div className="b-artifact-style-eyebrow">Style</div>
          <div className="b-artifact-style-toggle" role="radiogroup">
            {THEME_OPTIONS.map((option) => (
              <button
                aria-checked={activeTheme === option.value}
                className="b-artifact-style-option"
                data-active={activeTheme === option.value}
                key={option.value}
                onClick={() => onThemeChange(option.value)}
                role="radio"
                type="button"
              >
                {option.label}
              </button>
            ))}
          </div>
          <p className="b-artifact-style-hint">{THEME_HINT[activeTheme]}</p>
          <hr className="rd-hairline" />
          <div className="b-artifact-actions">
            <button
              className="rd-btn rd-btn-primary rd-btn-sm"
              disabled={exporting !== null}
              onClick={() => onExport(artifactKind, "pdf")}
              type="button"
            >
              {exporting === `${artifactKind}:pdf`
                ? "Preparing…"
                : "Download PDF"}
            </button>
            <button
              className="rd-btn rd-btn-ghost rd-btn-sm"
              disabled={exporting !== null}
              onClick={() => onExport(artifactKind, "docx")}
              type="button"
            >
              {exporting === `${artifactKind}:docx`
                ? "Preparing…"
                : "Download DOCX"}
            </button>
          </div>
          {previewTitle ? (
            <div className="b-artifact-meta">Preview · {previewTitle}</div>
          ) : null}
          {/* Online feedback — gathers a per-artifact 👍 / 👎 + optional
              comment so we can correlate quality with the underlying
              model + cost in the aggregate. The surface flips with the
              active tab; trace_id is omitted at this layer because the
              parent doesn't carry the per-call trace id today. */}
          <hr className="rd-hairline" />
          <FeedbackButtons
            surface={
              artifactKind === "tailored_resume"
                ? "tailored_resume"
                : "cover_letter"
            }
            // Re-mount the FeedbackButtons when the tab changes so the
            // user starts fresh on the new artifact — submitted state
            // shouldn't bleed across tabs.
            key={artifactKind}
          />
        </div>
      </div>
    </div>
  );
}
