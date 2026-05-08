"use client";

// Disclosure wrapper for workspace sections.
//
// Two visual variants:
//   - "card" (default): the bordered .b-twoup-section surface — used
//     for top-level groupings (Skills, Experience, Hard skills, etc.).
//   - "bare": editorial pattern — just a hairline + numbered heading
//     row + body. No card chrome, so stacked siblings read as one
//     continuous document rather than five identical bordered boxes.
//     Used inside containers where the parent already provides a
//     surface (Draft profile, JD body sections).
//
// Both default to open on first paint; tapping the header collapses
// the body. `hidden` attribute drives a11y + browser find-in-page.

import { useId, useState, type ReactNode } from "react";

import { ChevronRightIcon } from "@/components/workspace/icons";

export type CollapsibleSectionVariant = "card" | "bare";

export type CollapsibleSectionProps = {
  title: string;
  sub?: string;
  /**
   * Mono index shown to the left of the title in `bare` mode
   * (e.g. "01" → numbered editorial sections). Ignored by `card`.
   */
  index?: string;
  variant?: CollapsibleSectionVariant;
  /** Default to true (open) on first paint. */
  defaultOpen?: boolean;
  children: ReactNode;
};

export function CollapsibleSection({
  title,
  sub,
  index,
  variant = "card",
  defaultOpen = true,
  children,
}: CollapsibleSectionProps) {
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = useId();

  if (variant === "bare") {
    return (
      <div className="b-doc-section" data-collapsed={!open || undefined}>
        <button
          aria-controls={bodyId}
          aria-expanded={open}
          className="b-doc-section-head"
          onClick={() => setOpen((current) => !current)}
          type="button"
        >
          {index ? (
            <span className="b-doc-section-index">{index}</span>
          ) : null}
          <span className="b-doc-section-title">{title}</span>
          {sub ? <span className="b-doc-section-sub">{sub}</span> : null}
          <span aria-hidden="true" className="b-doc-section-toggle">
            <ChevronRightIcon />
          </span>
        </button>
        <div
          aria-hidden={!open}
          className="b-doc-section-body"
          id={bodyId}
          hidden={!open}
        >
          {children}
        </div>
      </div>
    );
  }

  return (
    <div className="b-twoup-section" data-collapsed={!open || undefined}>
      <button
        aria-controls={bodyId}
        aria-expanded={open}
        className="b-twoup-head b-twoup-head-toggle"
        onClick={() => setOpen((current) => !current)}
        type="button"
      >
        <div>
          <div className="b-twoup-title">{title}</div>
          {sub ? <div className="b-twoup-sub">{sub}</div> : null}
        </div>
        <span aria-hidden="true" className="b-twoup-toggle-caret">
          <ChevronRightIcon />
        </span>
      </button>
      <div
        aria-hidden={!open}
        className="b-twoup-collapse-body"
        id={bodyId}
        hidden={!open}
      >
        {children}
      </div>
    </div>
  );
}
