import { BackendHealthCard } from "@/components/backend-health-card";

const workflowStages = [
  {
    title: "Resume Intake",
    status: "Ready to port",
    summary:
      "Move upload, parsing feedback, and candidate snapshot state out of Streamlit session storage into typed Next forms plus API-backed persistence.",
  },
  {
    title: "JD Intake",
    status: "Ready to port",
    summary:
      "Keep manual input and imported-role review as separate panels, then feed both into the same workflow contract behind FastAPI.",
  },
  {
    title: "Agentic Run",
    status: "Needs API contract",
    summary:
      "The orchestration core already lives in Python. The next step is exposing run lifecycle, progress, and result payloads cleanly for the frontend.",
  },
  {
    title: "Artifacts",
    status: "Needs retrieval endpoints",
    summary:
      "Tailored resume, cover letter, and strategy report should become fetchable resources instead of Streamlit-rendered panels.",
  },
  {
    title: "Assistant",
    status: "Needs session model",
    summary:
      "The assistant is currently coupled to Streamlit state. We need an API-friendly session boundary before the richer frontend chat can replace it.",
  },
];

const architectureLanes = [
  {
    title: "Vercel Frontend",
    body:
      "The new frontend lives in `frontend/`, uses the App Router, and talks to the backend through `/api/*` rewrites so local dev and Vercel both stay simple.",
  },
  {
    title: "VPS Backend",
    body:
      "The root Dockerfile now builds the FastAPI service, while `deploy/vps/` carries the Compose plus Caddy bundle for the VPS deployment path.",
  },
  {
    title: "Python Core",
    body:
      "The existing workflow logic in `src/` stays the source of truth. We are changing the shell and API boundaries before we change the underlying pipeline.",
  },
];

export function WorkspaceSkeleton() {
  return (
    <div className="content-stack">
      <BackendHealthCard />

      <section className="section-grid">
        <article className="card">
          <div className="card-header">
            <div>
              <p className="section-kicker">Architecture</p>
              <h2>Current split we are building toward</h2>
            </div>
          </div>
          <div className="tile-grid">
            {architectureLanes.map((lane) => (
              <div className="tile" key={lane.title}>
                <h3>{lane.title}</h3>
                <p>{lane.body}</p>
              </div>
            ))}
          </div>
        </article>

        <article className="card">
          <div className="card-header">
            <div>
              <p className="section-kicker">Workflow Parity</p>
              <h2>Stages mirrored from the Streamlit product</h2>
            </div>
          </div>
          <div className="stack-list">
            {workflowStages.map((stage) => (
              <div className="list-row" key={stage.title}>
                <div>
                  <div className="row-title">{stage.title}</div>
                  <p>{stage.summary}</p>
                </div>
                <span className="status-badge">{stage.status}</span>
              </div>
            ))}
          </div>
        </article>
      </section>

      <article className="card">
        <div className="card-header">
          <div>
            <p className="section-kicker">Why This Branch</p>
            <h2>Main migration first, feature expansion second</h2>
          </div>
        </div>
        <p className="muted-copy">
          This skeleton is intentionally isolated from the active
          <code>feature/jd-summary</code> work. The idea is to stabilize the new
          deployment shape on top of <code>main</code>, then bring the extended
          job-application work across once the frontend/backend split is proven.
        </p>
      </article>
    </div>
  );
}
