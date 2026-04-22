"use client";

import type { ReactNode } from "react";

type WorkspaceShellProps = {
  children: ReactNode;
};

export function WorkspaceShell({ children }: WorkspaceShellProps) {
  return (
    <div className="workspace-shell">
      <div className="workspace-shell-inner">{children}</div>
    </div>
  );
}
