# ADR-003: Streamlit session state for navigation and persistence

## Status

Superseded by ADR-012

## Context

The product is a Streamlit MVP with multiple user flows that share parsed inputs.

## Decision

Use `st.session_state` to preserve the active menu and parsed payloads across reruns.

## Consequences

- Navigation stays simple without introducing a backend session store.
- Parsed inputs survive page switches in the same browser session.
- This approach is not sufficient for multi-user persistence or resumable workflows.

