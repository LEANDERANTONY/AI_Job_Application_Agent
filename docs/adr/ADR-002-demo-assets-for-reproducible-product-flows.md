# ADR-002: Demo assets for reproducible product flows

## Status

Accepted

## Context

The app needs to be demoable even when a user does not have a resume or job description ready.

## Decision

Keep sample resumes and job descriptions in `static/` and expose them directly in the UI.

## Consequences

- The parsing flows are easier to validate during development and demos.
- The repo can demonstrate core functionality without external setup.
- Static demo assets must remain curated and non-sensitive.

