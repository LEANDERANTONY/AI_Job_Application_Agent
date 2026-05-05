"use client";

// Small disclosure wrapper for the workspace's `.b-twoup-section`
// blocks. Renders the same surface the design system already uses,
// but the section head becomes a button — click to collapse the body.
//
// Defaults open so first-paint matches what desktop users saw before.
// On phones the user can tap any section closed to scroll past it
// quickly. Body uses CSS height transition + aria-hidden when closed
// for a11y.

import { useId, useState, type ReactNode } from "react";

import { ChevronRightIcon } from "@/components/workspace/icons";

export type CollapsibleSectionProps = {
  title: string;
  sub?: string;
  /** Default to true (open) on first paint. */
  defaultOpen?: boolean;
  children: ReactNode;
};

export function CollapsibleSection({
  title,
  sub,
  defaultOpen = true,
  children,
}: CollapsibleSectionProps) {
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = useId();

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
