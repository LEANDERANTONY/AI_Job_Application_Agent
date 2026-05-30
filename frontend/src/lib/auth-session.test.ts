import { describe, it, expect, vi } from "vitest";

import {
  buildAuthRedirectUrl,
  clearAuthQueryParams,
  clearLegacyAuthTokens,
} from "@/lib/auth-session";

// Tokens live in HttpOnly cookies (the frontend can't read them); this module's
// real surface is the OAuth redirect/cleanup helpers, covered here.
describe("auth-session", () => {
  it("buildAuthRedirectUrl joins the origin with a normalized path", () => {
    // jsdom's default origin is http://localhost:3000.
    expect(buildAuthRedirectUrl("/workspace")).toBe(
      "http://localhost:3000/workspace",
    );
    // A path without a leading slash gets one.
    expect(buildAuthRedirectUrl("workspace")).toBe(
      "http://localhost:3000/workspace",
    );
  });

  it("clearAuthQueryParams strips OAuth params but keeps unrelated ones", () => {
    const spy = vi.spyOn(window.history, "replaceState");
    window.history.replaceState(
      {},
      "",
      "/workspace?code=xyz&handoff=h&error=nope&keep=1",
    );

    clearAuthQueryParams();

    const lastUrl = String(spy.mock.calls.at(-1)?.[2] ?? "");
    expect(lastUrl).not.toContain("code=");
    expect(lastUrl).not.toContain("handoff=");
    expect(lastUrl).not.toContain("error=");
    expect(lastUrl).toContain("keep=1");
    spy.mockRestore();
  });

  it("clearLegacyAuthTokens removes the legacy localStorage key and never throws", () => {
    window.localStorage.setItem("workspace-auth-session-v1", "stale");
    expect(() => clearLegacyAuthTokens()).not.toThrow();
    expect(
      window.localStorage.getItem("workspace-auth-session-v1"),
    ).toBeNull();
  });
});
