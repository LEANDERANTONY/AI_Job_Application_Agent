import { describe, it, expect } from "vitest";

import {
  securityHeaders,
  contentSecurityPolicyReportOnly,
} from "@/lib/securityHeaders";

// Pins the FE-SEC-1 header set so a regression (a dropped header, or the CSP
// being flipped to enforcing before it's been tuned) fails CI.
describe("securityHeaders (FE-SEC-1)", () => {
  function valueOf(key: string) {
    return securityHeaders.find((h) => h.key === key)?.value;
  }

  it("enforces clickjacking protection immediately via X-Frame-Options: DENY", () => {
    expect(valueOf("X-Frame-Options")).toBe("DENY");
  });

  it("ships the CSP as Report-Only (not enforcing) and never as an enforcing CSP", () => {
    expect(valueOf("Content-Security-Policy-Report-Only")).toBeTruthy();
    // The enforcing header must NOT be present yet — tuning happens first.
    expect(valueOf("Content-Security-Policy")).toBeUndefined();
  });

  it("the CSP denies framing and defaults to self", () => {
    expect(contentSecurityPolicyReportOnly).toContain("frame-ancestors 'none'");
    expect(contentSecurityPolicyReportOnly).toContain("default-src 'self'");
  });

  it("sets HSTS, nosniff, and a referrer policy", () => {
    expect(valueOf("Strict-Transport-Security")).toContain("max-age=63072000");
    expect(valueOf("X-Content-Type-Options")).toBe("nosniff");
    expect(valueOf("Referrer-Policy")).toBe("strict-origin-when-cross-origin");
  });
});
