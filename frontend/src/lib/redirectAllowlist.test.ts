import { describe, it, expect } from "vitest";

import { isAllowedRedirect } from "@/lib/redirectAllowlist";

// jsdom's default origin is http://localhost:3000.
describe("isAllowedRedirect (M7)", () => {
  it("allows same-origin (relative + absolute) targets", () => {
    expect(isAllowedRedirect("/workspace")).toBe(true);
    expect(isAllowedRedirect("http://localhost:3000/auth/callback")).toBe(true);
  });

  it("allows the known external auth/billing providers", () => {
    expect(
      isAllowedRedirect("https://accounts.google.com/o/oauth2/v2/auth?x=1"),
    ).toBe(true);
    expect(
      isAllowedRedirect("https://abcdef.supabase.co/auth/v1/authorize"),
    ).toBe(true);
    expect(
      isAllowedRedirect("https://checkout.lemonsqueezy.com/buy/123"),
    ).toBe(true);
  });

  it("rejects an off-allowlist origin", () => {
    expect(isAllowedRedirect("https://evil.com/phish")).toBe(false);
  });

  it("rejects a look-alike host that only embeds an allowed domain", () => {
    // Ends with ".attacker.com", NOT ".supabase.co".
    expect(
      isAllowedRedirect("https://login.supabase.co.attacker.com/steal"),
    ).toBe(false);
  });

  it("rejects non-http(s) schemes (javascript:, data:)", () => {
    expect(isAllowedRedirect("javascript:alert(1)")).toBe(false);
    expect(isAllowedRedirect("data:text/html,<script>1</script>")).toBe(false);
  });

  it("rejects a protocol-relative redirect to an off-allowlist host", () => {
    // "//evil.com/x" inherits the base protocol and points off-origin.
    expect(isAllowedRedirect("//evil.com/steal")).toBe(false);
  });
});
