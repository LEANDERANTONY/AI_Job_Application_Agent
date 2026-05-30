// Security response headers (review FE-SEC-1). Extracted from next.config.ts
// so a unit test can import and assert the header set WITHOUT evaluating the
// Sentry-wrapped Next config. Values are byte-identical to what next.config.ts
// ships — the live X-Frame-Options / CSP-Report-Only behavior is unchanged.
//
// X-Frame-Options is ENFORCING immediately (the app is never legitimately
// framed). The CSP ships as Content-Security-Policy-Report-Only so a day of
// real traffic reveals any origin this allowlist misses BEFORE it is switched
// to enforcing — do NOT flip it to enforce here.
export const contentSecurityPolicyReportOnly = [
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

export const securityHeaders = [
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
