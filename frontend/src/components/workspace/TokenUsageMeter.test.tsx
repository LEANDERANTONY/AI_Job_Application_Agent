import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

import { TokenUsageMeter } from "@/components/workspace/TokenUsageMeter";
import type { WorkspaceQuotaCounter } from "@/lib/api-types";

function counter(current: number, limit: number): WorkspaceQuotaCounter {
  return {
    current,
    limit,
    remaining: Math.max(0, limit - current),
    reset_period: "weekly",
  };
}

describe("TokenUsageMeter", () => {
  it("renders the progressbar at the computed percentage with the formatted count", () => {
    const { container } = render(
      <TokenUsageMeter counter={counter(45000, 90000)} resetAt="2026-06-01" />,
    );
    expect(screen.getByRole("progressbar")).toHaveAttribute(
      "aria-valuenow",
      "50",
    );
    expect(container.querySelector(".b-token-meter-count")?.textContent).toBe(
      "45K / 90K",
    );
  });

  it("shows the 'allowance used up' copy at/over 100%", () => {
    render(
      <TokenUsageMeter counter={counter(90000, 90000)} resetAt="2026-06-01" />,
    );
    expect(screen.getByRole("progressbar")).toHaveAttribute(
      "aria-valuenow",
      "100",
    );
    expect(screen.getByText(/Weekly allowance used up/)).toBeInTheDocument();
  });

  it("renders nothing when the limit is the unlimited sentinel / non-positive", () => {
    const { container } = render(
      <TokenUsageMeter counter={counter(10, -1)} resetAt="2026-06-01" />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
