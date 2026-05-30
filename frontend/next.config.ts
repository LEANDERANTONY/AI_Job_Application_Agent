import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs";

const apiRewriteTarget =
  process.env.API_REWRITE_TARGET ?? "http://127.0.0.1:8000";

// Security response headers (review FE-SEC-1). The app shipped with NO
// CSP / framing / HSTS / nosniff / referrer headers, leaving clickjacking
// and zero XSS defense-in-depth on a surface that injects server-built
// HTML into srcDoc iframes.
//
// X-Frame-Options is ENFORCING immediately (the app is never legitimately
// framed). The CSP ships as Content-Security-Policy-Report-Only so a day
// of real traffic reveals any origin this allowlist misses BEFORE it is
// switched to enforcing — do NOT flip it to enforce in this change.
const contentSecurityPolicyReportOnly = [
  "default-src 'self'",
  "base-uri 'self'",
  "object-src 'none'",
  "frame-ancestors 'none'",
  // Next.js injects inline bootstrap scripts; 'unsafe-inline' is the
  // pragmatic interim (a nonce-based policy is the tightening follow-up).
  "script-src 'self' 'unsafe-inline' https://va.vercel-scripts.com",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https:",
  "font-src 'self' data:",
  // PostHog (analytics + replay), Sentry (errors), Supabase (auth),
  // Lemon Squeezy (checkout — "Coming soon"), Vercel (analytics). The
  // backend API is same-origin via the /api rewrite, so 'self' covers it.
  "connect-src 'self' https://eu.i.posthog.com https://eu-assets.i.posthog.com https://*.sentry.io https://*.supabase.co https://*.lemonsqueezy.com https://va.vercel-scripts.com https://vitals.vercel-insights.com",
  "frame-src 'self' https://*.lemonsqueezy.com",
  "worker-src 'self' blob:",
  "form-action 'self'",
].join("; ");

const securityHeaders = [
  // Enforcing immediately — defends against clickjacking now.
  { key: "X-Frame-Options", value: "DENY" },
  // Report-Only for now (see note above). Tighten + switch to enforcing
  // in a follow-up once 48h of reports confirm the allowlist.
  {
    key: "Content-Security-Policy-Report-Only",
    value: contentSecurityPolicyReportOnly,
  },
  {
    key: "Strict-Transport-Security",
    value: "max-age=63072000; includeSubDomains; preload",
  },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
];

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
