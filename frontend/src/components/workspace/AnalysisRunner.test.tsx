import { describe, it, expect, vi } from "vitest";
import { type ComponentProps } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AnalysisRunner } from "@/components/workspace/AnalysisRunner";
import type {
  WorkspaceQuotaCounter,
  WorkspaceQuotaResponse,
} from "@/lib/api-types";

function makeQuota(premiumAvailable: boolean): WorkspaceQuotaResponse {
  const counter = (limit: number): WorkspaceQuotaCounter => ({
    current: 0,
    limit,
    remaining: limit,
    reset_period: "monthly",
  });
  // Only the fields AnalysisRunner reads need to be real; the rest is cast.
  return {
    premium_available: premiumAvailable,
    counters: { premium_applications: counter(premiumAvailable ? 30 : 0) },
  } as unknown as WorkspaceQuotaResponse;
}

const TOGGLE_LABEL = "Run with premium AI (GPT-5.5)";

function renderRunner(
  overrides: Partial<ComponentProps<typeof AnalysisRunner>>,
) {
  const props: ComponentProps<typeof AnalysisRunner> = {
    analysisState: null,
    analysisLoading: false,
    analysisJobState: null,
    analysisIsStale: false,
    currentWorkflowStage: null,
    onRunAnalysis: vi.fn(),
    onCancelAnalysis: vi.fn(),
    analysisCancelling: false,
    onClearRole: vi.fn(),
    ready: true,
    quota: makeQuota(true),
    premium: false,
    onPremiumChange: vi.fn(),
    onPremiumLockedUpgrade: vi.fn(),
    ...overrides,
  };
  render(<AnalysisRunner {...props} />);
  return props;
}

describe("AnalysisRunner premium tier gate (PR #6)", () => {
  it("FREE: tapping the locked Premium toggle fires the upgrade CTA, not a state change", async () => {
    const onPremiumChange = vi.fn();
    const onPremiumLockedUpgrade = vi.fn();
    renderRunner({
      quota: makeQuota(false),
      onPremiumChange,
      onPremiumLockedUpgrade,
    });

    await userEvent.setup().click(screen.getByLabelText(TOGGLE_LABEL));

    expect(onPremiumLockedUpgrade).toHaveBeenCalledTimes(1);
    expect(onPremiumChange).not.toHaveBeenCalled();
  });

  it("PRO: toggling Premium flips the run mode (no upgrade CTA)", async () => {
    const onPremiumChange = vi.fn();
    const onPremiumLockedUpgrade = vi.fn();
    renderRunner({
      quota: makeQuota(true),
      onPremiumChange,
      onPremiumLockedUpgrade,
    });

    await userEvent.setup().click(screen.getByLabelText(TOGGLE_LABEL));

    expect(onPremiumChange).toHaveBeenCalledWith(true);
    expect(onPremiumLockedUpgrade).not.toHaveBeenCalled();
  });
});
