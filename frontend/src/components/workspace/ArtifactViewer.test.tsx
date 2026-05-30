import { describe, it, expect, vi } from "vitest";
import { render } from "@testing-library/react";

import { ArtifactViewer } from "@/components/workspace/ArtifactViewer";

describe("ArtifactViewer preview iframe (M5)", () => {
  it("renders the srcDoc preview iframe fully sandboxed (no allow-scripts)", () => {
    const { container } = render(
      <ArtifactViewer
        hasAnalysis
        artifact={{ title: "Resume", summary: "" }}
        tab="resume"
        onTabChange={vi.fn()}
        exporting={null}
        previewHtml="<p>preview</p>"
        previewTitle="Resume preview"
        previewLoading={false}
        activeTheme="professional_neutral"
        onThemeChange={vi.fn()}
        onExport={vi.fn()}
      />,
    );

    const iframe = container.querySelector("iframe.b-artifact-doc-frame");
    expect(iframe).not.toBeNull();
    // Empty sandbox = maximally locked: no scripts, no same-origin.
    expect(iframe?.getAttribute("sandbox")).toBe("");
  });
});
