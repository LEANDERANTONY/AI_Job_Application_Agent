"use client";

// Workspace drawer/sidebar shell — extracted from
// `job-application-workspace.tsx` as part of the Item 2 frontend split
// (see `docs/NEXT-STEPS-FRONTEND.md`).
//
// Pure presentational: owns the structural markup (drawer toggle,
// backdrop, <aside>, brand head) and exposes `children` as the slot
// for sidebar cards. Today the only child is `<AssistantPanel />`;
// future sidebar cards drop in alongside it.

import type { ReactNode } from "react";

export type SidebarProps = {
  collapsed: boolean;
  onCollapse: (collapsed: boolean) => void;
  children: ReactNode;
};

export function Sidebar({ collapsed, onCollapse, children }: SidebarProps) {
  return (
    <>
      {collapsed ? (
        <button
          aria-expanded={!collapsed}
          aria-label="Open workspace drawer"
          className="workspace-drawer-toggle"
          onClick={() => onCollapse(false)}
          type="button"
        >
          <span />
          <span />
          <span />
        </button>
      ) : null}

      {!collapsed ? (
        <button
          aria-label="Close workspace drawer"
          className="workspace-drawer-backdrop"
          onClick={() => onCollapse(true)}
          type="button"
        />
      ) : null}

      <aside
        className={
          collapsed
            ? "workspace-sidebar workspace-sidebar-closed"
            : "workspace-sidebar workspace-sidebar-open"
        }
        aria-hidden={collapsed}
      >
        <div className="workspace-sidebar-shell">
          <div className="workspace-sidebar-head">
            <div className="workspace-brand-lockup">
              <span className="workspace-brand-mark">AJ</span>
              <div>
                <p className="workspace-brand-title">Job Application Agent</p>
              </div>
            </div>

            <button
              aria-label="Close workspace drawer"
              className="workspace-sidebar-toggle workspace-sidebar-close"
              onClick={() => onCollapse(true)}
              type="button"
            >
              <span />
              <span />
            </button>
          </div>

          {children}
        </div>
      </aside>
    </>
  );
}
