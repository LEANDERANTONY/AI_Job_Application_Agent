import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs";

// Security response headers (review FE-SEC-1). Defined in src/lib/securityHeaders
// so a unit test can import and assert them without loading this Sentry-wrapped
// config. X-Frame-Options is enforcing; the CSP ships Report-Only (see that file).
import { securityHeaders } from "./src/lib/securityHeaders";

const apiRewriteTarget =
  process.env.API_REWRITE_TARGET ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  allowedDevOrigins: ["localhost", "127.0.0.1"],
  async headers() {
    // Apply to every route (HTML documents, assets, and the /api rewrite
    // alike). The HTML responses are what carry the clickjacking / XSS
    // exposure these headers close.
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiRewriteTarget}/api/:path*`,
      },
    ];
  },
};

// withSentryConfig wraps the Next config with the Sentry webpack plugin
// (source-map upload at build time + automatic instrumentation of
// route handlers / RSC). When SENTRY_AUTH_TOKEN is unset the plugin
// still runs but skips the upload step — local builds and PR previews
// without Sentry secrets succeed silently. The org / project values
// match the projects created in Sentry (org: leander-antony-a,
// project: jobagent-frontend).
const sentryOptions = {
  org: process.env.SENTRY_ORG || "leander-antony-a",
  project: process.env.SENTRY_PROJECT || "jobagent-frontend",
  silent: !process.env.CI,
  widenClientFileUpload: true,
  hideSourceMaps: true,
};

export default withSentryConfig(nextConfig, sentryOptions);
