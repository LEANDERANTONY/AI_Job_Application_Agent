# Roadmap

This roadmap reflects the current product state and the next major build priorities for the AI Job Application Agent.

## Now: Finish The Job-Application Product

Current product baseline:

- Google sign-in via Supabase
- login-required AI workflow and assistant
- resume upload plus manual JD flow
- backend-powered job search across Greenhouse and Lever
- direct job-link import into the JD flow
- saved-jobs shortlist on the feature branch
- supervised agentic analysis
- tailored resume generation
- cover letter generation
- application strategy report
- one in-app assistant chat with lighter internal routing and session-scoped conversation reuse on the feature branch
- latest saved-workspace reload
- Render-hosted Docker deployment

Highest-priority remaining product work:

- tighten the end-to-end search -> shortlist -> import -> analysis flow for normal users
- polish search-result cards, shortlist UX, and JD preview clarity
- add the Supabase `saved_jobs` table and policies when this branch is ready for production
- keep exported outputs visually strong and operationally reliable
- improve artifact naming, copy, and review UX where the product still feels internal or MVP-like
- continue refining grounded assistant behavior around the active outputs
- validate that the assistant prewarm and session-memory path actually reduces perceived chat latency in hosted usage

Status:

- Active delivery focus

## Next: Production Hardening On The Current Stack

- keep the Streamlit + Render + Supabase deployment reliable
- harden saved-workspace persistence and reload behavior
- validate saved-job persistence and restore flows under hosted conditions
- improve deployment and runtime observability
- keep auth, quota refresh, and export paths stable under hosted conditions
- add more smoke-test discipline around the hosted workflow
- finish and validate the two-service Render rollout for Streamlit + FastAPI on the feature branch
- verify assistant session reuse behaves well across reruns, page changes, and meaningful workflow-context resets

Status:

- In progress

## Later: Extract A Real Backend

The repo now includes a real FastAPI job backend on the feature branch. The next major architecture step is to finish deploying and validating that boundary, then continue any broader extraction only when the product needs more than the current split can comfortably support.

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

- In progress on the feature branch

## Future: Dedicated Frontend

- move the public product UI to a dedicated frontend only when the current UX clearly outgrows Streamlit
- keep the backend API stable first
- treat a React or Next.js frontend as a second-stage product investment, not the immediate next step

Status:

- Deferred until backend extraction is real
