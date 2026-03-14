# Google Sign-In Implementation Plan

## Goal

Add Google sign-in in a way that improves both user experience and product operations.

This should support:

- simple login for end users
- persistent per-user usage tracking
- future daily or plan-based limits
- future billing and paid plans
- stable identity for saved artifacts and workflow history

## Recommendation

Use Supabase Auth with Google as the first implementation path.

Reasoning:

- it is faster to ship than a custom backend-auth stack
- it gives both authentication and persistent data storage
- it fits the app's current stage better than a fully custom auth service
- it creates a clean path to quotas, account records, and subscriptions later

## Target Architecture

### Frontend

Streamlit remains the product UI.

Responsibilities:

- sign-in and sign-out entry points
- authenticated session display
- route gating for protected workflows
- showing per-user usage and plan state

### Auth and Data Layer

Supabase becomes the source of truth for:

- user identity
- linked Google account
- usage records
- quota state
- saved workflow metadata
- future billing/account metadata

### Current Limitation To Fix

Right now assisted-usage tracking is browser-session based.

That is acceptable for a prototype, but not for:

- real quotas
- per-day limits
- cross-device usage tracking
- abuse prevention
- subscriptions

## Phased Implementation

## Phase 1: Auth Foundation

### Deliverables

- Supabase project setup
- Google OAuth provider configured in Supabase
- app config for Supabase URL and anon key
- auth service wrapper in the codebase
- UI login/logout surface
- authenticated user info persisted in UI state

### Code Changes

- add `src/auth_service.py`
- add auth-related config in `src/config.py`
- add auth state helpers in `src/ui/state.py`
- add login/logout and account display in `src/ui/pages.py` or `src/ui/components.py`
- gate assisted workflows behind login if desired, or allow anonymous read-only behavior

### Product Decisions

- choose whether anonymous usage is allowed at all
- choose whether resume upload is allowed before login
- choose whether assisted workflow requires login immediately or only for heavy usage

### Recommended Product Rule

- allow browsing and basic deterministic exploration without login
- require Google sign-in before assisted workflow runs and persistent artifact history

## Phase 2: Persistent User Record

### Deliverables

- create user profile table in Supabase
- store app-level metadata per user
- sync first sign-in and returning sign-in behavior

### Suggested Tables

#### `app_users`

- `id`
- `email`
- `display_name`
- `avatar_url`
- `created_at`
- `last_seen_at`
- `plan_tier`
- `account_status`

#### `user_sessions` optional

- `id`
- `user_id`
- `started_at`
- `ended_at`
- `client_fingerprint` optional

### Purpose

This creates a real user object that quotas and billing can attach to later.

## Phase 3: Usage Persistence

### Deliverables

- persist usage per user instead of only per browser session
- store request counts and token totals server-side
- store usage by model and by task

### Suggested Tables

#### `usage_events`

- `id`
- `user_id`
- `session_id` optional
- `task_name`
- `model_name`
- `request_count`
- `prompt_tokens`
- `completion_tokens`
- `total_tokens`
- `response_id`
- `status`
- `created_at`

#### `usage_rollups_daily`

- `user_id`
- `date`
- `request_count`
- `prompt_tokens`
- `completion_tokens`
- `total_tokens`

### Code Changes

- add a persistence hook in `src/openai_service.py`
- add a usage repository module such as `src/usage_store.py`
- continue showing session capacity in the UI, but source enforcement from persisted quota checks

## Phase 4: Quotas and Limits

### Deliverables

- per-user daily limits
- plan-tier-based limits
- admin override support
- soft warning and hard stop behavior

### Suggested Rules

- free tier: conservative daily assisted runs
- paid tier: larger daily or monthly allowance
- admin tier: unrestricted or high cap

### Enforcement Order

1. check account status
2. check plan tier
3. check daily quota remaining
4. allow or block the assisted step

### UI Behavior

- show users remaining assisted capacity
- do not show internal dollar cost
- show friendly upgrade or retry messaging only when relevant

## Phase 5: Saved History and Artifacts

### Deliverables

- save workflow summaries per user
- save report metadata and tailored resume metadata
- optional download history
- optional restore last session state

### Suggested Tables

#### `workflow_runs`

- `id`
- `user_id`
- `job_title`
- `fit_score`
- `review_approved`
- `model_policy`
- `created_at`

#### `artifacts`

- `id`
- `workflow_run_id`
- `artifact_type`
- `storage_path`
- `created_at`

## Phase 6: Billing Readiness

### Deliverables

- Stripe or similar billing integration
- plan tier sync into user profile
- billing webhook handling
- entitlement checks before assisted runs

### Important Rule

Billing should attach to account entitlements, not to raw token display in the UI.

## Security and Privacy Requirements

- never store raw Google access tokens in app-visible state longer than needed
- keep Supabase session handling server-trusted where possible
- treat uploaded resumes and JDs as sensitive user data
- define retention and deletion behavior early
- add row-level security for all user-owned records

## Streamlit-Specific Notes

Because this app is Streamlit-first, auth should not rely only on local session state.

Session state should cache authenticated UI context, but the durable source of truth must be:

- Supabase auth session
- Supabase user record
- persisted usage tables

## Proposed File-Level Implementation Sequence

1. `src/config.py`
Add Supabase and Google auth env settings.

2. `src/auth_service.py`
Add sign-in, sign-out, current-user, and session validation helpers.

3. `src/ui/state.py`
Add authenticated user/session state keys.

4. `src/ui/pages.py`
Add login screen, account panel, and workflow gating.

5. `src/openai_service.py`
Attach authenticated user context to usage logging and persistent usage writes.

6. `src/ui/workflow.py`
Block assisted workflow runs if policy requires login or quota is exhausted.

7. `tests/`
Add tests for auth state, quota enforcement, and assisted workflow gating.

## Recommended Rollout

### Step 1

Ship Google sign-in and basic authenticated session support.

### Step 2

Persist user records and usage events.

### Step 3

Add daily limits.

### Step 4

Add plan tiers and billing.

This order keeps the implementation honest. A daily limit before persistent identity would be weak and easy to bypass.

## Immediate Next Build Task

Implement Phase 1 only:

- Supabase config
- Google sign-in flow
- authenticated user state
- basic account panel in the UI

Do not implement billing or daily quota enforcement in the same pass.