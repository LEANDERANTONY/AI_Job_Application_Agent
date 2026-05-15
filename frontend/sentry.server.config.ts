// Sentry — Node.js runtime config (jobagent-frontend project).
//
// Loaded by ``instrumentation.ts`` when ``NEXT_RUNTIME === "nodejs"``.
// Covers RSC, route handlers, Server Actions, and any other code path
// that executes in the Node worker.
//
// We share the same DSN as the browser bundle (Sentry routes events by
// project, not by runtime), but pull the value through ``SENTRY_DSN``
// (server-only) with a fallback to ``NEXT_PUBLIC_SENTRY_DSN`` so a
// single env var works in both places. When the DSN is empty,
// ``Sentry.init`` is a no-op — useful for dev / preview deployments
// that haven't enabled Sentry yet.

import * as Sentry from "@sentry/nextjs";

const dsn = process.env.SENTRY_DSN || process.env.NEXT_PUBLIC_SENTRY_DSN;

if (dsn) {
  Sentry.init({
    dsn,
    environment:
      process.env.SENTRY_ENVIRONMENT ||
      process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT ||
      process.env.NODE_ENV ||
      "development",
    tracesSampleRate: Number(process.env.SENTRY_TRACES_SAMPLE_RATE ?? 0.1),
    debug: false,
  });
}
