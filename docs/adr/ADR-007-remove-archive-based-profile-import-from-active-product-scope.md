# ADR-007: Remove archive-based profile import from active product scope

## Status

Accepted

## Context

The project originally supported profile-export archive ingestion as a safer alternative to direct profile scraping or API access.

That workflow was technically workable, but it created product friction at exactly the wrong point in the user journey:

- users had to leave the app and request an external profile export
- delivery depended on a third-party archive flow and timing
- the imported data quality varied across exports
- the feature expanded schema, UI, parser, and testing surface area without improving the core resume-to-application outcome enough to justify the complexity

The current MVP is stronger when it focuses on the lowest-friction path: resume input plus target job description.

## Decision

Remove archive-based profile import from the active product and codebase.

Keep the product centered on:

- resume parsing
- job-description structuring
- deterministic fit and tailoring helpers
- supervised agent refinement
- exportable application-package generation

## Consequences

- The user journey is simpler and faster.
- Candidate-profile handling becomes easier to reason about because there is one active intake source.
- The codebase loses parser, schema, UI, and test complexity that was specific to the archive-ingestion experiment.
- Historical ADR-004 remains useful as a record of an earlier product direction, but it no longer governs the active application scope.