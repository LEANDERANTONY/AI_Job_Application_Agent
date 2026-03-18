# ADR-005: Streamlit-first, backend-ready delivery strategy

## Status

Accepted

## Context

The AI Job Application Agent needs to ship an initial public version quickly, but it also has a likely long-term path toward a production architecture with a dedicated backend and a richer frontend.

The team discussed whether to begin immediately with:

- FastAPI
- Redis
- Postgres
- React or Next.js
- Dockerized deployment

That stack is appropriate later, but would add significant platform complexity before the core workflow is validated.

## Decision

Use Streamlit for the first deployable product version, while structuring the codebase so business logic can later be exposed through FastAPI and consumed by a separate frontend.

Specific implications:

- `app.py` remains a UI layer
- business logic should move into `src/` services and agent modules
- the app keeps sidebar navigation because the product has multiple workflows
- Redis is deferred until background jobs or shared cache become necessary
- Docker is not required to justify the initial product, but remains the right runtime boundary once backend extraction becomes real
- Next.js is the preferred frontend target when the app outgrows Streamlit

## Consequences

### Positive

- faster delivery of the first public version
- simpler development and deployment in the short term
- easier product validation before infrastructure expansion
- cleaner future migration path because logic is separated from the UI

### Negative

- some production concerns remain deferred
- Streamlit continues to limit frontend flexibility in the short term
- the backend boundary remains implicit until FastAPI is introduced

### Follow-up

The codebase should now evolve toward:

- typed schemas
- service modules
- supervised agent orchestration
- deterministic report assembly
- backend-ready persistence and export boundaries

That work will make the later FastAPI and Next.js migration much easier.
