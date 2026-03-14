# ADR-008: Two-Mode Grounded Assistant Panel

## Status

Accepted

## Context

The product now generates richer outputs than the original deterministic fit snapshot alone:

- a tailored resume artifact
- an application report / strategy package
- comparison and validation views
- an explicit supervised workflow with revision-aware review

That makes the product more useful, but it also increases navigation and interpretation overhead.

Users need help in two distinct categories:

- how to use the product itself
- how to understand the current resume, JD, and generated outputs

Treating both needs as one undifferentiated assistant would weaken grounding and increase the risk of mixing product guidance with application-specific claims.

## Decision

Add one shared assistant surface with two explicit modes:

- `Using the App`
- `About My Resume`

Implementation details:

1. keep one assistant service in code rather than creating multiple extra orchestrator agents
2. route product-help questions through a bounded product-help mode
3. route application-specific questions through a grounded workflow-Q&A mode
4. keep both modes constrained to structured JSON responses and deterministic fallback behavior
5. expose the assistant in the active UI pages where users need help, instead of creating a separate chat-only destination

## Alternatives Considered

### 1. No assistant

Rejected because the product has passed the point where static UI copy alone is sufficient to explain the flow and outputs.

### 2. One freeform assistant with no explicit modes

Rejected because it increases grounding risk and blurs the difference between product navigation and candidate-specific interpretation.

### 3. Separate orchestrated specialist chat agents

Rejected for now because that would add architectural and cost complexity without strong evidence that the current two-mode panel is insufficient.

## Consequences

- the product gets a lightweight help surface without creating a second orchestration pipeline
- product-help questions can stay on a cheaper model tier
- application-Q&A can use a higher-trust model tier when needed
- assistant behavior remains grounded in current workflow state rather than acting as an open-ended chatbot
- future assistant expansion should start from the current two-mode panel before adding more agent roles