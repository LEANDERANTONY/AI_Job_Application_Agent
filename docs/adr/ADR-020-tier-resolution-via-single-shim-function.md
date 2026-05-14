# ADR-020: Tier Resolution via a Single Shim Function

- Status: Accepted
- Date: 2026-05-15

## Context

The Day 42 tier-enforcement series wired eight quota gates (`tailored_applications`, `premium_applications`, `resume_builder_sessions`, `assistant_turns`, `resume_parses`, `job_searches`, `saved_jobs`, `saved_workspaces`), a tier-aware retention sweeper for `saved_workspaces`, and a tier-aware premium model router. Each of these surfaces needs to answer the same question — *what subscription tier does this user have?* — at request time.

Two facts shaped the decision:

1. **Payments aren't shipping in the same week as enforcement.** The tier-enforcement series shipped to `main` and deployed; the Lemon Squeezy integration (Day 43) lives on a separate branch and goes live after the LS variant IDs are configured. Until then, every authenticated user is on the Free tier by definition — there are no paid subscribers because there's no checkout.
2. **Once payments do ship, we need every gate to honour the new tier on the same deploy.** Anything less means a partial-rollout window where some surfaces gate on the real tier and others still gate on `"free"`, which is the worst possible state for a billing surface.

We needed a structural answer to "where does tier come from?" that lets enforcement code ship today against a static Free baseline AND flips cleanly to live subscriptions tomorrow.

## Decision

A single function — `backend.tiers.resolve_user_tier(app_user: AppUserRecord | None) -> Literal["free", "pro", "business"]` — is the canonical entry point for tier resolution. Every gate, the model router, the retention sweeper, and the `/workspace/quota` snapshot all call it. Today the body is:

```python
def resolve_user_tier(app_user: AppUserRecord | None) -> Tier:
    _user_id = getattr(app_user, "id", None)
    return "free"
```

— it accepts the `app_user` (so the call-site signature is already what the live version will need), touches `app_user.id` defensively, and returns the literal `"free"`. When payments go live (Day 43, commit `1b8cf95`), the body is rewritten to consult the `aijobagent_subscriptions` table:

```python
def resolve_user_tier(app_user: AppUserRecord | None) -> Tier:
    user_id = getattr(app_user, "id", None)
    if not user_id:
        return "free"
    active = subscriptions_store.find_active(user_id=user_id)
    if active is None or active.current_period_end <= datetime.now(timezone.utc):
        return "free"
    return active.tier
```

No gate, no router, no sweeper, no test fixture, no snapshot endpoint changes. The Stripe / Razorpay swap is identical in shape: rewrite the body, leave the signature intact.

## Alternatives Considered

### 1. Per-gate tier checks inline at each call site
Rejected. Eight gates × one tier check each = eight places that need to learn about subscriptions on the payment cutover. The model router and retention sweeper are two more. That's ten chances for an inconsistency to ship — and worse, the consistency is *invisible* (no compile error catches a forgotten call site, only a production overage does).

### 2. Decorator pattern (`@require_tier("pro")` on each endpoint)
Rejected for two reasons. First, the tier requirement is rarely binary — `/workspace/analyze` accepts everyone but charges different counters based on tier (`tailored_applications` for all, `premium_applications` only for Pro+ when `premium=True`). A decorator that resolves to "allow / deny" doesn't model that. Second, decorators bind tier-knowledge to *route* handlers, but the same tier needs to reach the model router and the per-pipeline construction-time `model_overrides` (see ADR-022). Threading the decorator's result through to deep call paths means lifting it to a request-context attribute anyway, at which point it's just a worse version of the shim.

### 3. Class-based `TierResolver` injected into the request context
Considered. Object-oriented version of the same idea — DI a resolver, swap its implementation on the cutover. Adds construction wiring at every entry point without changing the substantive call shape. Rejected on the basis that a free function with one body to swap is the simplest thing that could possibly work, and we have no existing DI container to plug a resolver into. Revisit if we ever grow multiple resolution strategies (e.g. tier-by-tenant for B2B), but that's not on the roadmap.

### 4. Compute tier eagerly at sign-in and stash on `AppUserRecord.plan_tier`
Considered, partially rejected. The `app_users` table does have a `plan_tier` column, populated at signup. We could trust it as the source of truth — but stale state is exactly the failure mode subscriptions introduce. A user who cancels at 23:59 and runs a workflow at 00:01 has the new tier ("free") even though their session still carries the old `plan_tier == "pro"`. The Day 43 store-backed resolver consults `current_period_end` on every call, which is correct by construction; the `plan_tier` column becomes a denormalized hint we may or may not refresh. Centralizing resolution in the shim means we get the live answer for free without per-call-site decisions about whether to trust the cache.

## Consequences

### Positive

- Payment cutover is a one-function rewrite. No call sites change, no tests change (beyond the resolver's own), no signatures change.
- Test fixtures that need to simulate a Pro user just monkeypatch `resolve_user_tier`. We already do this in `test_workspace_retention.py` and `test_tier_aware_workflow_model.py` to exercise the Pro / Business code paths against today's Free-only resolver.
- The `app_user` argument is accepted today even though it's unused; this keeps the call-site code identical pre- and post-cutover, which means git blame stays clean and reviewers don't have to context-switch on the signature.
- The tier *type* is a `Literal` — adding a new tier (`"enterprise"`) is a tiny PR that updates the type alias, `TIER_CAPS`, the retention table, and the resolver body. The type checker catches every missing branch.

### Negative

- Every gate pays a tier resolution call per request. Today that's one Python branch; post-cutover it's a Supabase round-trip per gated request. The `/workspace/quota` snapshot endpoint calls it once per page mount, and each workspace action that's gated calls it once. We avoid stampedes by reading the active subscription once per request (memoize on the FastAPI request scope when the live resolver lands).
- A bug in the resolver body affects every gate simultaneously. Mitigated by the tier-specific Pro / Business test paths already exercising the wiring against a patched resolver — the patch surface IS the resolver, so any regression in its behaviour is caught.
- The shim hides the fact that subscriptions exist from the call sites. New gates added in the future need to *not* re-derive tier from `app_user.plan_tier` directly — they need to call the resolver. This is a code-review checklist item.

## Follow-Up

- When Day 43 (Lemon Squeezy) lands and the resolver body is rewritten, add a request-scoped memoization layer so a single `/workspace/analyze` request doesn't issue N tier lookups for N gated steps.
- Linter rule (or grep guard in CI): forbid direct reads of `app_user.plan_tier` outside `backend/tiers.py` and `backend/subscriptions.py`. The `plan_tier` column stays as a denormalized hint for the account popover; it isn't load-bearing for enforcement.

## Related

- [ADR-021](ADR-021-atomic-quota-with-refund-on-failure.md): the quota helper called by every gate; together with the resolver, these are the two functions every enforcement surface routes through.
- [ADR-022](ADR-022-tier-aware-model-selection-via-constructor-injection.md): the model router consumes `resolve_user_tier`'s output at construction time.
- [ADR-023](ADR-023-lemon-squeezy-merchant-of-record-for-v1.md): the payment processor whose subscription rows the post-cutover resolver consults.
