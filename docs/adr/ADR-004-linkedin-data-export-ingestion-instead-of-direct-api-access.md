# ADR-004: LinkedIn data export ingestion instead of direct API access

## Status

Accepted

## Context

Direct LinkedIn profile access is constrained by product restrictions and Terms of Service concerns.

## Decision

Accept user-uploaded LinkedIn data export ZIP files instead of scraping or attempting direct profile import.

## Consequences

- The app stays inside a safer product boundary.
- Users retain control over what profile data they share with the app.
- The workflow adds friction because users must export their data before upload.

