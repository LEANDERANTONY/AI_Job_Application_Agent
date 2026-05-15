// Sentry — Browser runtime config (jobagent-frontend project).
//
// Next 15+ replaced the legacy ``sentry.client.config.ts`` convention
// with ``instrumentation-client.ts``, which is loaded once at app
// boot in the browser. We initialize the Sentry browser SDK here and
// turn on the BrowserTracing integration for navigation spans.
//
// GDPR / ePrivacy gate. We split the Sentry integrations into two
// categories matching the cookie-banner contract:
//
//   * Always-on (legitimate interest under GDPR Art. 6(1)(f) — we
//     need crash reporting to operate the service securely):
//       - error tracking + traces
//       - User Feedback widget
//   * Consent-gated (requires the user to accept the banner):
//       - Session Replay (records DOM mutations + user input)
//
// At boot we read localStorage["jobagent-cookie-consent"] inline
// (importing the helper would pull React into a config module). If
// it's "accepted" we ship Replay; otherwise we skip it. When the
// user later accepts via the banner, the dispatched event hot-adds
// Replay without a page reload.

import * as Sentry from "@sentry/nextjs";

const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;

function readConsent(): "pending" | "accepted" | "declined" {
  if (typeof window === "undefined") return "pending";
  try {
    const raw = window.localStorage.getItem("jobagent-cookie-consent");
    if (raw === "accepted" || raw === "declined") return raw;
  } catch {
    /* incognito / Safari ITP — treat as pending */
  }
  return "pending";
}

// Derive the integration-array type from Sentry.init's signature so a
// future SDK type change can't silently widen this. ``@sentry/nextjs``
// doesn't re-export the bare ``Integration`` type from its public
// barrel — Parameters<...> is the supported path.
type SentryIntegrations = NonNullable<
  NonNullable<Parameters<typeof Sentry.init>[0]>["integrations"]
>;

function buildIntegrations(consent: "pending" | "accepted" | "declined"): SentryIntegrations {
  const integrations: SentryIntegrations = [
    Sentry.feedbackIntegration({
      colorScheme: "dark",
      autoInject: true,
      showBranding: false,
      triggerLabel: "Report an issue",
      formTitle: "Report an issue",
      submitButtonLabel: "Send",
      enableScreenshot: true,
    }),
  ];
  if (consent === "accepted") {
    integrations.push(
      Sentry.replayIntegration({
        // Mask all text + media by default. Workspace can show resume
        // content + free-text answers; we can't ship that to Sentry
        // without making PII commitments we haven't reviewed legally.
        maskAllText: true,
        blockAllMedia: true,
      }),
    );
  }
  return integrations;
}

if (dsn) {
  const consentAtBoot = readConsent();
  Sentry.init({
    dsn,
    environment:
      process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT ||
      process.env.NODE_ENV ||
      "development",
    tracesSampleRate: Number(
      process.env.NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE ?? 0.1,
    ),
    // Replay strategy: skip ambient session sampling (PostHog handles
    // full session replay), capture 100% of sessions that hit an
    // error — only when the user has consented. Without consent the
    // replay integration isn't loaded so these numbers are inert.
    replaysSessionSampleRate: 0,
    replaysOnErrorSampleRate:
      consentAtBoot === "accepted"
        ? Number(process.env.NEXT_PUBLIC_SENTRY_REPLAYS_ON_ERROR_SAMPLE_RATE ?? 1.0)
        : 0,
    integrations: buildIntegrations(consentAtBoot),
    debug: false,
  });

  // Hot-add Replay if the user accepts AFTER the initial boot.
  if (typeof window !== "undefined") {
    window.addEventListener("jobagent-cookie-consent-change", () => {
      const next = readConsent();
      if (next === "accepted") {
        try {
          Sentry.addIntegration(
            Sentry.replayIntegration({
              maskAllText: true,
              blockAllMedia: true,
            }),
          );
        } catch {
          /* already added or SDK doesn't support hot-add — fine */
        }
      }
    });
  }
}

// Required export for Next's instrumentation hook on the client —
// runs once per navigation, lets the Sentry SDK record the route
// transition as a span.
export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
