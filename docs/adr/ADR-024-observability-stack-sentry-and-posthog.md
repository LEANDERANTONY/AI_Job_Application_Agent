# ADR-024: Observability Stack — Sentry + PostHog with Consent-Gated Analytics

Date: 2026-05-16

Status: Shipped

## Context

By the end of Day 43 (tier enforcement + Lemon Squeezy scaffold), the AI Job Application Agent was running in production with no first-class crash reporter on the backend, no LLM-cost attribution beyond the per-trace `aijobagent_run_traces` table, and no user-cohort analytics. The FastAPI container's failures landed in `docker logs ai-job-application-agent-api` and stayed there until someone happened to look.

Three things made adding an observability layer urgent now rather than after first revenue:

- **Payment cutover is close.** When the LS variant IDs flip live, the dashboards need to already show free-vs-pro cohort behavior + LLM cost per tier. Retrofitting after a paid user signs up is the wrong direction of dependency.
- **AI Agents Monitoring is now a first-class Sentry feature.** The `OpenAIIntegration` auto-emits AI-aware spans (token counts, model, latency, cost) without per-call instrumentation. Free on the Developer plan. The orchestrated workflow (TailoringAgent → ReviewAgent → ResumeGenAgent → CoverLetterAgent) makes multiple LLM calls per `/workspace/analyze` request, and attributing slowness to a specific agent used to need a manual debug print pass.
- **PostHog free tier is generous enough for an MVP.** 1M events/month + 5K replays/month + 100K exceptions covers far more traffic than the product will see this year.

The third constraint was **GDPR / ePrivacy posture**. The backend is in Frankfurt (EU), the PostHog and Sentry projects are EU-region, and EU users hitting the landing page can't be tracked without explicit consent. The integration had to make that compliance posture explicit at the SDK level, not as a layer of legal disclosure on top of a leaky baseline.

## Decision

Adopt a two-vendor observability stack:

- **Sentry** for error tracking, performance traces, AI Agents Monitoring, Logs, Crons, and session replay (errors-only). One Sentry org (`leander-antony-a`) hosts two paired projects: `jobagent-backend` + `jobagent-frontend`. Backend Python integrations: `FastApiIntegration`, `StarletteIntegration`, `LoggingIntegration`, `OpenAIIntegration` (`include_prompts=False` for PII). Frontend integrations: `feedbackIntegration` (always on, legitimate interest), `replayIntegration` (consent-gated, masked).
- **PostHog** for product analytics, session replay, identify/group cohort analytics. Free Developer plan caps at 1 project per org, so the project is shared with infrastructure run under the same org for the developer's other products; every event carries a `product: "jobagent"` super-property so dashboards can slice cleanly by `where product = 'jobagent'`.

Both clients are bootstrapped via a single module (`backend/observability.py`) at import time, before `FastAPI()` is constructed in `backend/app.py` so the Sentry ASGI middleware wraps the app at startup. The module is a no-op when either DSN / API key is empty, so dev and CI run unchanged.

### Free-tier-maxed configuration

| Sentry feature | Setting | Why |
| --- | --- | --- |
| Tracing | `traces_sample_rate=0.1` | 10% sample is the Sentry default; bumpable via env if a feature needs deeper coverage |
| Profiling | `profiles_sample_rate=0.05` | 5% keeps free quota healthy while surfacing slow code paths |
| Logs | `enable_logs=True` | New Sentry Logs product, separate from breadcrumbs, full-text searchable |
| Replay (FE) | `replaysSessionSampleRate=0, replaysOnErrorSampleRate=1.0` | No ambient session sampling (PostHog handles full session replay), but 100% on errored sessions for high-signal debugging |
| User Feedback widget | always on | Tied to current Sentry session — user reports include breadcrumbs + active replay |
| AI Agents | `OpenAIIntegration` | Per-LLM-call spans with token + cost + model + latency |

### PostHog configuration

| PostHog feature | Setting | Why |
| --- | --- | --- |
| Autocapture | on | Click + form submit capture without per-event wiring |
| Session replay | `maskAllInputs: true` | Free tier covers 5K replays/mo; PII-safe by default |
| Heatmaps | on | Workspace UX iteration signal |
| Surveys | on (project-level toggle) | Future NPS / feedback survey wiring |
| Exception capture | **off** | Sentry is the source of truth; avoid double-billing the free-tier exception budget |

### Consent gating (paired with [ADR-025](ADR-025-eu-cookie-consent-banner-and-gdpr-analytics-gating.md))

Sentry split into two integration categories:

- **Always-on** (legitimate interest under GDPR Art. 6(1)(f)): error tracking, traces, Feedback widget. These load regardless of cookie banner state — crash reporting is operationally necessary.
- **Consent-gated** (requires explicit opt-in): Session Replay. Loads only when `localStorage["jobagent-cookie-consent"] === "accepted"`. The state-change event listener hot-adds the Replay integration via `Sentry.addIntegration(...)` without a page reload when consent flips.

PostHog is fully consent-gated: `posthog.init` only runs after consent acceptance. State changes call `posthog.opt_in_capturing()` / `opt_out_capturing()` for runtime flips.

### Vercel-Sentry integration vs manual env vars

The Sentry-Vercel marketplace integration auto-provisions `SENTRY_AUTH_TOKEN` + `NEXT_PUBLIC_SENTRY_DSN` and creates release markers per Vercel deploy. For the Job Agent's `job-application-copilot` Vercel project, the integration's env-var-upsert step conflicted with already-set env vars (the manual setup happened first), so the manual fallback was used — `SENTRY_AUTH_TOKEN` was set directly in Vercel env. Both paths give the same source-map upload behavior; only the auto-created release markers are missing in the manual case (those can be backfilled from `VERCEL_GIT_COMMIT_SHA` via `withSentryConfig` if needed).

## Consequences

### Positive

- **Single bootstrap path.** `initialize_observability(settings)` is the only place the two clients are touched. Adding a third vendor (e.g. Datadog APM, if scale ever justifies) means adding one call in that function and leaving every route handler unchanged.
- **No-op safe defaults.** Empty DSN / API key → SDK init is skipped → zero network calls, zero memory cost. Local dev, CI, and the test suite run without observability wiring.
- **Pytest-skip guard.** The `_running_under_pytest()` check skips Sentry entirely when `PYTEST_CURRENT_TEST` is set, so `uv run pytest` against a real DSN doesn't fire test fixtures into the production project.
- **HTTPException filter.** `before_send` drops intentional 4xx flow control + 5xx "not configured" / "temporarily unavailable" guards. Keeps the issue feed focused on genuine bugs (RuntimeError, IntegrityError, OpenAI APIError, etc.) instead of "user uploaded a 26MB file at a 25MB cap" noise.
- **PostHog `product` tag pattern.** Every event carries `product: "jobagent"` at SDK init (via `posthog.register({product: "jobagent"})`) plus the backend `capture_event` merges the same tag into every server-side event. Dashboards stay cleanly product-scoped regardless of how PostHog projects are organized at the org level.

### Negative

- **Two vendors instead of one.** Sentry + PostHog have overlapping replay capability. The split — Sentry-Replay for errored sessions, PostHog Replay for ambient session sampling — is defensible but adds a second SDK to the browser bundle (~80KB gzipped combined).
- **Free tier quota is finite.** 5K errors / 50 FE replays / 1M PostHog events per month. If a user-facing bug fires a tight loop of errors, the quota burns fast. The HTTPException filter mitigates this for backend; the `replaysOnErrorSampleRate=1.0` is the highest-risk knob (one error per replay).
- **GDPR posture depends on a custom banner.** ADR-025 captures the consent banner; if that banner breaks (e.g. state never persists), analytics silently never load. Mitigation: a small click-test in the deploy smoke check would catch regressions, but it's not yet automated.

### Neutral

- **Sentry release tagging via GitHub commit SHA**, not Vercel deploy ID — works whether the Vercel-Sentry integration is installed or the manual env-var fallback is used. Suspect Commits feature works in both cases because the GitHub integration is the source of commit context.

## Alternatives considered

- **LogRocket + custom error reporter.** LogRocket has stronger session replay but no free tier above 1K sessions/month. Rejected on cost.
- **Datadog APM.** Far more capable but priced for series-A startups, not solo MVPs. Rejected on cost.
- **PostHog alone (using PostHog's exception tracking).** PostHog covers errors as a feature, so a single-vendor stack is tempting. Rejected because Sentry's Python + JS error groupings are categorically better (stack-trace fingerprinting, release tracking, code mappings to GitHub) and free-tier Sentry doesn't compete with PostHog's free-tier event budget.
- **Self-hosted observability (Plausible + Glitchtip).** Theoretical $0 cost but operational burden of another container set on the VPS. Rejected as scope creep.
- **Skip observability until first revenue.** Tempting but wrong direction of dependency — without observability we can't measure free-vs-pro cohort behavior, which is the data the payment cutover analysis needs.

## References

- DEVLOG Day 46: Observability stack + cookie consent
- `backend/observability.py` — single bootstrap module
- `frontend/instrumentation-client.ts`, `instrumentation.ts`, `sentry.server.config.ts`, `sentry.edge.config.ts`
- `frontend/src/components/posthog-provider.tsx`, `cookie-consent.tsx`
- ADR-025: EU cookie consent banner + GDPR-aligned analytics gating
- ADR-013: Cached jobs cache layer (the only other long-running scheduled job + the only pg_cron job on the Supabase project; LLM-free polling, not observability-relevant but worth knowing exists)
