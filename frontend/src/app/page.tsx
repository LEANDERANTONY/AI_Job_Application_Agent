import { MigrationShell } from "@/components/migration-shell";

const transitionGoals = [
  {
    title: "Keep the Python workflow core",
    body:
      "The value is already in the parsing, fit analysis, orchestration, and artifact builders. We are not rewriting that logic into JavaScript.",
  },
  {
    title: "Move product UI to Next.js",
    body:
      "The frontend gets cleaner routing, deploys naturally on Vercel, and becomes easier to iterate on without the constraints of Streamlit state.",
  },
  {
    title: "Standardize backend deployment on the VPS",
    body:
      "The FastAPI boundary becomes the single Dockerized service for the product shell to call, matching the HelpMate deployment pattern.",
  },
];

const migrationNotes = [
  "The current Streamlit product remains the reference implementation while parity work is underway.",
  "This branch is aimed at the main-architecture transition only, not the larger extended-job-support branch.",
  "The first useful checkpoint is not visual polish; it is a trustworthy split deployment shape that we can build on.",
];

export default function HomePage() {
  return (
    <MigrationShell
      currentPath="/"
      eyebrow="Transition Overview"
      title="Preparing the platform split before the full UI redesign"
      intro="This branch establishes the deployment and codebase skeleton for a Vercel-hosted Next.js frontend talking to a Dockerized FastAPI backend on the VPS. The goal is to prove the architecture first, then layer the real product screens and style system on top."
      actions={[{ href: "/workspace", label: "Open Workspace" }]}
    >
      <section className="section-grid">
        <article className="card">
          <div className="card-header">
            <div>
              <p className="section-kicker">Primary Goals</p>
              <h2>What this skeleton is solving right now</h2>
            </div>
          </div>
          <div className="tile-grid">
            {transitionGoals.map((goal) => (
              <div className="tile" key={goal.title}>
                <h3>{goal.title}</h3>
                <p>{goal.body}</p>
              </div>
            ))}
          </div>
        </article>

        <article className="card">
          <div className="card-header">
            <div>
              <p className="section-kicker">Guardrails</p>
              <h2>Decisions that keep this move low risk</h2>
            </div>
          </div>
          <div className="stack-list">
            {migrationNotes.map((note) => (
              <div className="list-row" key={note}>
                <div>
                  <div className="row-title">Migration note</div>
                  <p>{note}</p>
                </div>
              </div>
            ))}
          </div>
        </article>
      </section>
    </MigrationShell>
  );
}
