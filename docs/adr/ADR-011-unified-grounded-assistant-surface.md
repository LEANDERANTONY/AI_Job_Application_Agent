# ADR-011: Unified Grounded Assistant Surface

## Status

Accepted

## Context

The product originally exposed one assistant surface with two explicit modes:

- `Using the App`
- `About My Resume`

That separation helped at first, but the product has since changed in ways that made the split less useful and more brittle:

- the JD flow now exposes multiple first-class artifacts, including the tailored resume, cover letter, and application strategy report
- saved workspace restore is now a first-class authenticated behavior and part of the normal user flow
- assistant prompts and static product knowledge had started to drift from the actual runtime experience because the same feature had to be described in two separate assistant paths
- the UI forced users to decide which assistant mode they needed before asking a question, even when many questions naturally span both product usage and current-output interpretation

In practice, users ask blended questions such as:

- where a generated artifact came from
- what was saved and what reload restores
- whether a current output is safe or grounded
- how to use a current feature in the context of the active workflow state

Those are not cleanly separable into product-help-only versus application-QA-only categories.

## Decision

Adopt one unified in-app assistant surface that can answer both product and workflow questions in the same conversation.

Implementation details:

1. keep one assistant UI with one shared chat history instead of a mode toggle
2. build one assistant prompt contract that receives both product context and workflow context together
3. keep runtime session data authoritative for current page state, quotas, saved-workspace behavior, and active artifacts
4. allow broader coaching when appropriate, but require workflow-grounded answers for candidate-specific or artifact-specific claims
5. preserve deterministic fallback behavior so the assistant still works when model responses fail or assisted limits are reached
6. keep the assistant outside the supervised artifact-generation pipeline because it is still conversational support, not a workflow output stage

## Alternatives Considered

### 1. Keep the two-mode assistant panel

Rejected because the split had become a UX burden and a maintenance burden. It duplicated prompt logic, knowledge maintenance, and session handling while no longer matching how users ask questions.

### 2. Route all assistant questions to a completely freeform chatbot

Rejected because the product still needs strong grounding to the current runtime state and active workflow artifacts. A generic chatbot would increase drift and reduce trust.

### 3. Add more specialist assistant modes

Rejected because the current problem was too much mode complexity, not too little. More modes would make the UI harder to use and increase prompt maintenance cost further.

## Consequences

- the assistant becomes easier to use because users no longer have to classify their question before asking it
- product explanations and artifact explanations now share one source of conversational truth
- the assistant can answer cross-cutting questions about resume, cover letter, report, saved workspace restore, and quotas without switching modes
- prompt and knowledge maintenance become simpler because current-flow updates only need to be applied once
- the assistant still needs careful grounding discipline so that broader coaching does not drift into unsupported claims about the user's materials
