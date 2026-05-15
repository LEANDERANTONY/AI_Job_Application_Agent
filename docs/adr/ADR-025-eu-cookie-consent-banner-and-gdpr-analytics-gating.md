# ADR-025: EU Cookie Consent Banner + GDPR-Aligned Analytics Gating

Date: 2026-05-16

Status: Shipped

## Context

The AI Job Application Agent runs in the EU (Frankfurt VPS + EU-region Sentry + EU-region PostHog) and the landing page is publicly reachable from any geography. The Day 46 observability stack ([ADR-024](ADR-024-observability-stack-sentry-and-posthog.md)) introduced PostHog product analytics + PostHog session replay + Sentry Session Replay. All three set non-essential cookies and start tracking the moment the page loads.

The ePrivacy Directive (Art. 5(3)) + GDPR (Arts. 6, 7) require that non-essential cookies be loaded only after **explicit, granular, freely-given consent**. PostHog's `respect_dnt: true` option honors the Do-Not-Track browser flag, but DNT is set by ~3% of users in practice and isn't accepted as sufficient under ePrivacy. Relying on DNT alone leaves the other 97% being tracked without consent — the textbook scenario the regulation exists to prevent.

The compliance gap had to be closed without:

- shipping a third-party JS bundle (Cookiebot, Iubenda, Termly, Osano) that itself runs before consent is given, which is its own ePrivacy footgun
- paying \$11-27/mo for a vendor cookie banner at a stage where there's no recurring revenue to amortize that cost
- adopting a "weasel-word" posture (banner that says "by using this site you consent" with no actual choice) that fails enforcement scrutiny

The fourth constraint: **error tracking should NOT require consent**, because crash reporting is operationally necessary to keep the service running securely. GDPR Art. 6(1)(f) explicitly allows processing under "legitimate interest" for legitimate purposes the user reasonably expects — debugging crashes the user just experienced qualifies. The banner had to split the analytics surface from the error-tracking surface cleanly.

## Decision

Build a custom three-state cookie consent banner in-house. Wire PostHog initialization + Sentry Replay integration to gate on the consent state. Keep Sentry error tracking + traces + Feedback widget always-on.

### Three-state machine

`localStorage["jobagent-cookie-consent"]` is the source of truth:

| State | What it means | What loads |
| --- | --- | --- |
| `"pending"` | First visit (or user re-opened preferences) | Banner shown. Sentry errors + traces + Feedback. No PostHog. No Sentry Replay. |
| `"accepted"` | User clicked "Accept" | Banner hidden. PostHog init + identify + group + pageview + autocapture + session replay. Sentry adds Replay integration via `Sentry.addIntegration(...)`. |
| `"declined"` | User clicked "Decline non-essential" | Banner hidden. PostHog opt-out via `opt_out_capturing()`. Sentry stays errors-only — no Replay. |

A custom-event `"jobagent-cookie-consent-change"` is dispatched on every state transition so consumers (PostHog provider, Sentry init) re-evaluate without a page reload. A cross-tab `storage` event listener keeps state synced across open tabs.

### Re-opening the choice

The landing footer + workspace shell both expose "Cookie preferences" links that call `openCookiePreferences()` to clear the localStorage key (state → `"pending"`) and dispatch the change event. The banner re-renders in-place over whatever route the user is on, no navigation needed.

### Legal split — what loads when

Categorized per the GDPR posture analysis:

- **Strictly necessary** (ePrivacy Art. 5(3) exception, no consent needed): Supabase Auth session cookies, CSRF tokens. Always load.
- **Legitimate interest** (GDPR Art. 6(1)(f), no consent needed): Sentry error tracking + Sentry traces + Sentry Feedback widget. Always load. Justified because crash reporting is operationally necessary to keep the service running.
- **Opt-in required**: PostHog product analytics + PostHog session replay + Sentry Session Replay. Only load when consent === "accepted".

### Theme

Self-contained CSS class (`.ja-cookie-banner` / `.ja-cookie-content`). Mounts in `layout.tsx` so it overlays every route consistently. Mobile-stacked at <640px width. Animation respects `prefers-reduced-motion`. Hex values are inlined rather than referencing shell-scoped tokens because the banner renders on the landing route too where the workspace shell scope isn't mounted.

The localStorage key + custom-event name use the `jobagent-` prefix specifically so a developer running both this product and infrastructure-paired siblings under the same dev origin doesn't cross-contaminate consent state.

## Consequences

### Positive

- **Zero recurring cost.** No vendor banner license, no per-page metering. ~100 lines of TypeScript + ~120 lines of CSS that ship in the existing bundle.
- **Compliance posture is explicit in code.** The legal categorization (strictly necessary / legitimate interest / opt-in) is enforced at the integration-init level, not in legalese on a privacy policy page that no one reads. Future contributors can see exactly which features load when by reading `posthog-provider.tsx` + `instrumentation-client.ts`.
- **No third-party JS before consent.** Every cookie banner vendor's banner is itself loaded via their CDN, which means a third-party script runs before the user has consented to third-party scripts — circular dependency that most vendor banners gloss over. Our banner ships as part of our own bundle, so the only third-party JS that ever loads is the post-consent SDKs.
- **Sentry stays useful even on declined.** Crashes that a "decline analytics" user experiences still flow into the issue feed (with `user.distinct_id` set to anonymous session token), so we can debug their bug. We don't lose visibility of regressions just because someone declined optional analytics.
- **Hot-add Replay on consent flip.** A user who declines initially and later flips to accept doesn't need a page reload — `Sentry.addIntegration(Sentry.replayIntegration(...))` adds the integration in-place.

### Negative

- **No regional differentiation.** Every user sees the banner — US users who aren't covered by GDPR/ePrivacy + don't legally require explicit consent still get a "We use cookies" interruption on first visit. The simpler compliance posture (worldwide consent prompt) is the tradeoff for not maintaining a geo-IP detection path.
- **Custom code = custom maintenance.** A Cookiebot dashboard would show a compliance report and auto-update when the rules change. We're on the hook for tracking ePrivacy interpretation changes ourselves. Acceptable risk at MVP stage; revisit if/when a paid compliance product becomes worth the cost.
- **Session replay coverage drops.** Pre-banner-shipped, 100% of errored sessions had a replay. Post-banner, only consent-accepted users do. If a bug shows up disproportionately among declined users, the replay coverage gap matters. Best case is ~70-80% of users accept (industry rough avg), so we lose ~20-30% of replays.
- **No granular consent.** Single "accept all non-essential" vs "decline all non-essential" — no per-category toggles (analytics-only, replay-only). Granular consent is technically required under strictest interpretation; the binary form is what most indie SaaS ships and what enforcement focuses on the strict-required side rarely. If enforcement appetite increases, this is the next iteration.

## Alternatives considered

- **Cookiebot / Iubenda / Termly / Osano.** All gate-of-entry vendors charge \$11-27/mo for what's substantively a script tag + a JSON config. The compliance dashboards are useful at scale but unjustifiable at pre-revenue stage. Rejected on cost + the third-party-JS-before-consent paradox.
- **No banner, rely on `respect_dnt: true`.** Honors DNT users (~3%) but tracks the other 97% without explicit opt-in. Fails ePrivacy. Rejected.
- **Geo-IP banner (show banner only to EU users).** Technically valid but adds an IP-geo dependency, fails for VPN'd users + EU citizens traveling, and the cost of always showing the banner is trivial compared to the maintenance cost of a geo path. Rejected on simplicity.
- **Granular per-vendor consent toggles.** Adds a "Manage preferences" expander with checkboxes for PostHog Analytics / PostHog Replay / Sentry Replay separately. Higher compliance ceiling, more UI complexity, lower acceptance rate (more clicks). Deferred for now; the binary banner satisfies the common-case interpretation.

## References

- DEVLOG Day 46: Observability stack + cookie consent
- `frontend/src/components/cookie-consent.tsx` — banner + state machine + hooks
- `frontend/src/components/posthog-provider.tsx` — consent-gated PostHog init
- `frontend/instrumentation-client.ts` — `buildIntegrations(consent)` splits Sentry into always-on + consent-gated
- ADR-024: Observability stack — Sentry + PostHog with consent-gated analytics
- ePrivacy Directive Art. 5(3), GDPR Art. 6(1)(f), GDPR Art. 7
