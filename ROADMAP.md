# Roadmap

This roadmap reflects the current product state and the next major build priorities for the AI Job Application Agent.

## Now: Finish The Job-Application Product

Current product baseline:

- Google sign-in via Supabase
- login-required AI workflow and assistant
- resume upload plus manual JD flow
- supervised agentic analysis
- tailored resume generation
- cover letter generation
- application strategy report
- latest saved-workspace reload
- Render-hosted Docker deployment

Highest-priority remaining product work:

- turn `Job Search` from a placeholder into a real job-application input path or remove it
- tighten the end-to-end job-application flow for normal users, not just demo usage
- keep exported outputs visually strong and operationally reliable
- improve artifact naming, copy, and review UX where the product still feels internal or MVP-like
- continue refining grounded assistant behavior around the active outputs

Status:

- Active delivery focus

## Next: Production Hardening On The Current Stack

- keep the Streamlit + Render + Supabase deployment reliable
- harden saved-workspace persistence and reload behavior
- improve deployment and runtime observability
- keep auth, quota refresh, and export paths stable under hosted conditions
- add more smoke-test discipline around the hosted workflow

Status:

- In progress

## Later: Extract A Real Backend

The next major architecture step is a backend extraction when the product needs more than a single Streamlit session model can comfortably support.

Targets:

- expose orchestration, persistence, and export boundaries through FastAPI
- keep Docker as the standard runtime and deployment unit
- support background jobs for long-running workflow execution
- enable better concurrency, including assistant interactions that do not block on the main workflow
- keep Streamlit usable as a demo or internal client during the transition

Triggers that justify this step:

- need for parallel user interactions during workflow execution
- need for non-Streamlit clients
- heavier persistence and job-control requirements
- more production-grade operational control than Streamlit alone provides

Status:

- Planned, not started

## Future: Dedicated Frontend

- move the public product UI to a dedicated frontend only when the current UX clearly outgrows Streamlit
- keep the backend API stable first
- treat a React or Next.js frontend as a second-stage product investment, not the immediate next step

Status:

- Deferred until backend extraction is real
