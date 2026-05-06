"use client";

// Hook owning artifact tab + preview + export state for the workspace.
// Lifted from `WorkspaceShell.tsx` as part of the Item 2 frontend split
// (see `docs/NEXT-STEPS-FRONTEND.md`, task #13).
//
// Internally uses `useState` rather than a Zustand slice. Artifact
// state has exactly one writer (this hook) and one reader (the
// ArtifactViewer component); a slice would add ceremony without
// payoff. Larger shared state (auth, snapshot) gets slices when its
// hook lands.

import { useEffect, useMemo, useState } from "react";

import {
  exportWorkspaceArtifact,
  previewWorkspaceArtifact,
} from "@/lib/api";
import type {
  ArtifactTheme,
  WorkspaceAnalysisResponse,
  WorkspaceArtifactKind,
} from "@/lib/api-types";
import type {
  ArtifactTab,
  ArtifactViewerArtifact,
} from "@/components/workspace/ArtifactViewer";

type Notice =
  | {
      level: "info" | "success" | "warning";
      message: string;
    }
  | null;

function downloadBase64File(
  filename: string,
  contentBase64: string,
  mimeType: string,
) {
  const binary = atob(contentBase64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  const blob = new Blob([bytes], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function artifactKindFromTab(
  tab: ArtifactTab,
): WorkspaceArtifactKind {
  return tab === "resume" ? "tailored_resume" : "cover_letter";
}

export type UseArtifactExportOptions = {
  /** The current workspace analysis response, or null if no run yet. */
  analysisState: WorkspaceAnalysisResponse | null;
  /** Surface success/error to the workspace top-level notice slot. */
  setNotice: (notice: Notice) => void;
};

export type UseArtifactExportReturn = {
  artifactTab: ArtifactTab;
  setArtifactTab: (tab: ArtifactTab) => void;
  artifactExporting: string | null;
  artifactPreviewHtml: string | null;
  artifactPreviewTitle: string | null;
  artifactPreviewLoading: boolean;
  /** Memoized artifact metadata (title + summary) for the active tab. */
  currentArtifact: ArtifactViewerArtifact | null;
  /** Derived backend kind ("tailored_resume" | "cover_letter") for the active tab. */
  currentArtifactKind: WorkspaceArtifactKind;
  /**
   * Theme selection per artifact. Each tab carries its own theme so the
   * resume can ship classic_ats while the cover letter ships
   * professional_neutral (or vice versa) — the user picks per document.
   */
  resumeTheme: ArtifactTheme;
  coverLetterTheme: ArtifactTheme;
  setResumeTheme: (theme: ArtifactTheme) => void;
  setCoverLetterTheme: (theme: ArtifactTheme) => void;
  /**
   * Trigger an export for the resume or cover letter artifact.
   */
  exportArtifact: (
    kind: WorkspaceArtifactKind,
    format: "markdown" | "pdf",
  ) => Promise<void>;
  /** Reset transient artifact state (used by `clearWorkspaceRole`). */
  resetArtifacts: () => void;
};

export function useArtifactExport({
  analysisState,
  setNotice,
}: UseArtifactExportOptions): UseArtifactExportReturn {
  const [artifactTab, setArtifactTab] = useState<ArtifactTab>("resume");
  const [artifactExporting, setArtifactExporting] = useState<string | null>(
    null,
  );
  const [artifactPreviewHtml, setArtifactPreviewHtml] = useState<string | null>(
    null,
  );
  const [artifactPreviewTitle, setArtifactPreviewTitle] = useState<
    string | null
  >(null);
  const [artifactPreviewLoading, setArtifactPreviewLoading] = useState(false);
  const [resumeTheme, setResumeTheme] = useState<ArtifactTheme>("classic_ats");
  const [coverLetterTheme, setCoverLetterTheme] =
    useState<ArtifactTheme>("classic_ats");

  const currentArtifact = useMemo<ArtifactViewerArtifact | null>(() => {
    if (!analysisState) {
      return null;
    }
    if (artifactTab === "resume") {
      return {
        ...analysisState.artifacts.tailored_resume,
        theme: resumeTheme,
        summary: `Tailored resume draft for ${
          analysisState.job_description.title || "the target role"
        }, ready to review and export.`,
      };
    }
    return {
      ...analysisState.artifacts.cover_letter,
      theme: coverLetterTheme,
    };
  }, [analysisState, artifactTab, resumeTheme, coverLetterTheme]);

  const currentArtifactKind = artifactKindFromTab(artifactTab);

  // Fetch preview HTML whenever the snapshot or artifact kind changes.
  useEffect(() => {
    const workspaceSnapshot = analysisState;
    if (!workspaceSnapshot) {
      setArtifactPreviewHtml(null);
      setArtifactPreviewTitle(null);
      setArtifactPreviewLoading(false);
      return;
    }
    const resolvedWorkspaceSnapshot: WorkspaceAnalysisResponse =
      workspaceSnapshot;

    let cancelled = false;

    async function loadArtifactPreview() {
      setArtifactPreviewLoading(true);
      try {
        const response = await previewWorkspaceArtifact({
          workspace_snapshot: resolvedWorkspaceSnapshot,
          artifact_kind: currentArtifactKind,
          resume_theme: resumeTheme,
          cover_letter_theme: coverLetterTheme,
        });
        if (!cancelled) {
          setArtifactPreviewHtml(response.html);
          setArtifactPreviewTitle(response.artifact_title);
        }
      } catch (error) {
        if (!cancelled) {
          setArtifactPreviewHtml(null);
          setArtifactPreviewTitle(null);
          setNotice({
            level: "warning",
            message:
              error instanceof Error
                ? error.message
                : "Artifact preview could not be generated.",
          });
        }
      } finally {
        if (!cancelled) {
          setArtifactPreviewLoading(false);
        }
      }
    }

    void loadArtifactPreview();

    return () => {
      cancelled = true;
    };
  }, [
    analysisState,
    currentArtifactKind,
    resumeTheme,
    coverLetterTheme,
    setNotice,
  ]);

  async function exportArtifact(
    artifactKind: WorkspaceArtifactKind,
    exportFormat: "markdown" | "pdf",
  ) {
    if (!analysisState) {
      setNotice({
        level: "warning",
        message: "Run the workspace flow before exporting artifacts.",
      });
      return;
    }

    const exportKey = `${artifactKind}:${exportFormat}`;
    setArtifactExporting(exportKey);
    try {
      const response = await exportWorkspaceArtifact({
        workspace_snapshot: analysisState,
        artifact_kind: artifactKind,
        export_format: exportFormat,
        resume_theme: resumeTheme,
        cover_letter_theme: coverLetterTheme,
      });
      downloadBase64File(
        response.file_name,
        response.content_base64,
        response.mime_type,
      );
      setNotice({
        level: "success",
        message: `Prepared ${response.artifact_title} as ${response.file_name}.`,
      });
    } catch (error) {
      setNotice({
        level: "warning",
        message:
          error instanceof Error
            ? error.message
            : "Artifact export failed unexpectedly.",
      });
    } finally {
      setArtifactExporting(null);
    }
  }

  function resetArtifacts() {
    setArtifactExporting(null);
    setArtifactPreviewHtml(null);
    setArtifactPreviewTitle(null);
    setArtifactPreviewLoading(false);
  }

  return {
    artifactTab,
    setArtifactTab,
    artifactExporting,
    artifactPreviewHtml,
    artifactPreviewTitle,
    artifactPreviewLoading,
    currentArtifact,
    currentArtifactKind,
    resumeTheme,
    coverLetterTheme,
    setResumeTheme,
    setCoverLetterTheme,
    exportArtifact,
    resetArtifacts,
  };
}
