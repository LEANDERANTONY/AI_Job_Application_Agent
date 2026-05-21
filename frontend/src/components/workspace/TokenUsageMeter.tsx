"use client";

// Weekly LLM token usage meter (token-meter migration, T6).
//
// Surfaces how much of the user's weekly AI-token allowance is spent —
// the unified `llm_tokens` gate that replaced the scattered per-feature
// LLM caps. Rendered in the workspace account popover. The bar's tone
// shifts as the allowance runs low: it is the conversion signal a Free
// user feels building up before they hit the wall.

import type { WorkspaceQuotaCounter } from "@/lib/api-types";

export type TokenUsageMeterProps = {
  /** The `llm_tokens` counter from the /workspace/quota snapshot. */
  counter: WorkspaceQuotaCounter;
  /** ISO date (YYYY-MM-DD) the weekly meter next resets on. */
  resetAt: string;
};

/** 31200 → "31.2K", 90000 → "90K", 1_000_000 → "1M". Exact token
 *  counts aren't actionable for the user; a compact figure keeps the
 *  meter line readable. */
function formatTokens(value: number): string {
  if (value >= 1_000_000) {
    return `${(value / 1_000_000).toFixed(value % 1_000_000 === 0 ? 0 : 1)}M`;
  }
  if (value >= 1_000) {
    return `${(value / 1_000).toFixed(value % 1_000 === 0 ? 0 : 1)}K`;
  }
  return String(value);
}

function formatResetDate(iso: string): string {
  const parsed = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return "";
  return parsed.toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

export function TokenUsageMeter({ counter, resetAt }: TokenUsageMeterProps) {
  const limit = counter.limit;
  // Every tier has a finite weekly llm_tokens cap, so an UNLIMITED
  // (-1) / zero limit shouldn't occur — guard so a future change can't
  // divide-by-zero or NaN the bar.
  if (limit <= 0) return null;

  const used = Math.max(0, counter.current);
  const pct = Math.min(100, Math.round((used / limit) * 100));
  // ok → low (≥75%) → over (at/past cap): drives the bar colour.
  const tone = pct >= 100 ? "over" : pct >= 75 ? "low" : "ok";
  const resetLabel = formatResetDate(resetAt);

  return (
    <div className="b-token-meter" data-tone={tone}>
      <div className="b-token-meter-head">
        <span className="b-token-meter-label">AI usage · this week</span>
        <span className="b-token-meter-count">
          {formatTokens(used)} / {formatTokens(limit)}
        </span>
      </div>
      <div
        aria-label="Weekly AI token usage"
        aria-valuemax={100}
        aria-valuemin={0}
        aria-valuenow={pct}
        className="b-token-meter-track"
        role="progressbar"
      >
        <div
          className="b-token-meter-fill"
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="b-token-meter-foot">
        {tone === "over" ? "Weekly allowance used up" : `${pct}% used`}
        {resetLabel ? ` · resets ${resetLabel}` : ""}
      </div>
    </div>
  );
}
