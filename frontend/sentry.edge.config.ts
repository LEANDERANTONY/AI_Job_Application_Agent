// Sentry — Edge runtime config (jobagent-frontend project).
//
// Loaded by ``instrumentation.ts`` when ``NEXT_RUNTIME === "edge"``.
// Covers Next middleware and any route handler that opts into the edge
// runtime. The edge runtime has a leaner Node API surface, so the
// SDK auto-loads a subset of integrations here — we don't override
// any. Mirrors the server config otherwise.

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
