# ADR-009: Google Sign-In via Supabase for Persistent Identity

## Status

Accepted

## Context

The current product can already benefit from persistent identity even before billing exists.

Session-based Streamlit state is sufficient for local prototype flow, but it is not a durable foundation for:

- per-user usage tracking
- plan-based or daily assisted limits
- cross-device continuity
- saved workspace continuity
- future subscriptions or billing entitlements

The product direction now includes assisted workflow usage tracking and eventually monetization. That makes browser-only session identity too weak to govern product access and usage.

## Decision

Adopt Google sign-in as the primary user login method, using Supabase Auth as the initial identity and persistence layer.

The architecture decision is:

1. keep Streamlit as the current product UI
2. move from browser-session-only identity toward persistent authenticated users
3. use Supabase Auth with Google as the first implementation path
4. persist usage and account metadata outside local Streamlit session state
5. treat quotas, plans, and future billing as account-level concerns rather than UI-only state

Google sign-in is the chosen user-facing authentication method because it reduces friction. Supabase is the chosen implementation foundation because it combines auth and persistent storage with lower delivery overhead than a custom auth backend.

## Alternatives Considered

### 1. Keep anonymous session-only usage

Rejected because it does not support durable quotas, meaningful tracking, or future paid plans.

### 2. Build a custom backend-auth stack first

Rejected for the current phase because it is slower to deliver and unnecessary before stronger evidence of custom auth requirements exists.

### 3. Use Firebase Auth as the first path

Considered viable, but not chosen initially because Supabase better aligns with the need for relational product data such as usage records, saved workspace state, and entitlement state.

## Consequences

- auth becomes a first-class product concern rather than a later add-on
- usage limits can evolve from session-based estimates to real per-user enforcement
- saved workspace state can attach to a stable account identity
- the app will need secure handling of auth sessions and user-owned data
- backend persistence becomes part of the product foundation even while Streamlit remains the UI shell
- Google sign-in should be implemented before daily quotas or billing so those later systems rest on real identity
