"use client";

// Auth tokens now live exclusively in HttpOnly cookies set by the
// backend's /auth/google/exchange and /auth/session/restore endpoints,
// and are sent automatically by the browser on every API call via
// `credentials: "include"`. The frontend has no read or write access to
// the raw tokens. That's the whole point.
//
// What stays in this module:
//   - `buildAuthRedirectUrl`: still needed because Google OAuth calls
//     back to our origin and we have to tell it which URL to use.
//   - `clearAuthQueryParams`: post-OAuth cleanup of `?code=` etc.
//   - `clearLegacyAuthTokens`: one-shot cleanup of the old localStorage
//     entry so returning users don't carry stale data across the
//     cookie-migration cutover. Safe to remove after a few weeks.

const LEGACY_AUTH_STORAGE_KEY = "workspace-auth-session-v1";

export function buildAuthRedirectUrl(path = "/") {
  if (typeof window === "undefined") {
    return "";
  }
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${window.location.origin}${normalizedPath}`;
}

export function clearAuthQueryParams() {
  if (typeof window === "undefined") {
    return;
  }
  const url = new URL(window.location.href);
  url.searchParams.delete("code");
  url.searchParams.delete("auth_flow");
  url.searchParams.delete("error");
  url.searchParams.delete("error_description");
  window.history.replaceState({}, document.title, url.toString());
}

export function clearLegacyAuthTokens() {
  if (typeof window === "undefined") {
    return;
  }
  try {
    window.localStorage.removeItem(LEGACY_AUTH_STORAGE_KEY);
  } catch {
    // localStorage may be unavailable in privacy modes / sandboxed
    // contexts; nothing to clean up there anyway.
  }
}
