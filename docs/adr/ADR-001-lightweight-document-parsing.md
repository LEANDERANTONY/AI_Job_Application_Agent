# ADR-001: Lightweight document parsing for MVP

## Status

Accepted

## Context

The project needed a fast way to parse resumes and job descriptions without introducing a large orchestration stack early.

## Decision

Use `pypdf` and `python-docx` for PDF and DOCX ingestion, plus direct text decoding for TXT files.

## Consequences

- Parsing stays simple and easy to debug.
- The app remains lightweight enough for Streamlit-first development.
- Complex layouts and scanned PDFs still need future OCR or richer document tooling.

