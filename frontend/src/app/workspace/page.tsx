import { JobApplicationWorkspace } from "@/components/job-application-workspace";
import { WorkspaceShell } from "@/components/workspace-shell";

export default function WorkspacePage() {
  return (
    <main className="workspace-page">
      <WorkspaceShell>
        <JobApplicationWorkspace />
      </WorkspaceShell>
    </main>
  );
}
