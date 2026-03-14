# ADR-004: Archive-based profile ingestion instead of direct profile access

## Status

Superseded by ADR-007

## Context

Direct third-party profile access is constrained by product restrictions and Terms of Service concerns.

## Decision

Accept user-uploaded profile export archives instead of scraping or attempting direct profile import.

## Consequences

- The app stays inside a safer product boundary.
- Users retain control over what profile data they share with the app.
- The workflow adds friction because users must export their data before upload.
- This decision is no longer active product scope because the export-based flow added too much intake friction for the MVP.