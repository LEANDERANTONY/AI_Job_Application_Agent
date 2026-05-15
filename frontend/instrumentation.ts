// Next.js instrumentation hook — fires once per server worker boot.
//
// Loads the right Sentry config for the current runtime. Without this
// shim, the Sentry SDK never initializes on the server / edge side
// and only client-side errors flow into the dashboard.
//
// ``onRequestError`` is the modern App Router hook that captures
// uncaught exceptions thrown inside a Server Component or a Route
// Handler. Without it, server-rendered errors die in the Next.js
// dev overlay with no Sentry trail.

import * as Sentry from "@sentry/nextjs";

export async function register() {
  if (process.env.NEXT_RUNTIME === "nodejs") {
    await import("./sentry.server.config");
  }

  if (process.env.NEXT_RUNTIME === "edge") {
    await import("./sentry.edge.config");
  }
}

export const onRequestError = Sentry.captureRequestError;
