// Thin re-export shim. The workspace's full implementation moved to
// `workspace/WorkspaceShell.tsx` as part of the Item 2 frontend split
// (see `docs/NEXT-STEPS-FRONTEND.md`). This file remains as a
// backwards-compat alias so any older import paths keep working; once
// all consumers migrate it can be deleted (handoff task #14).

export { WorkspaceShell as JobApplicationWorkspace } from "@/components/workspace/WorkspaceShell";
