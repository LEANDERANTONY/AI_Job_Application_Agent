# ADR-007: Remove LinkedIn import from active product scope

## Status

Accepted

## Context

The project originally supported LinkedIn data-export ZIP ingestion as a safer alternative to direct profile scraping or API access.

That workflow was technically workable, but it created product friction at exactly the wrong point in the user journey:

- users had to leave the app and request an export from LinkedIn
- delivery depended on LinkedIn's archive flow and timing
- the imported data quality varied across exports
- the feature expanded schema, UI, parser, and testing surface area without improving the core resume-to-application outcome enough to justify the complexity

The current MVP is stronger when it focuses on the lowest-friction path: resume input plus target job description.

## Decision

Remove LinkedIn import from the active product and codebase.

Keep the product centered on:

- resume parsing
- job-description structuring
- deterministic fit and tailoring helpers
- supervised agent refinement
- exportable application-package generation

## Consequences

- The user journey is simpler and faster.
- Candidate-profile handling becomes easier to reason about because there is one active intake source.
- The codebase loses parser, schema, UI, and test complexity that was specific to LinkedIn ingestion.
- Historical ADR-004 remains useful as a record of an earlier product direction, but it no longer governs the active application scope.