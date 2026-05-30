"use client";

// Client-side redirect allowlist (review M7). The OAuth-start, workspace-
// handoff, and billing-portal flows navigate the browser to a URL the
// BACKEND returns. If the backend ever reflects an attacker-influenced
// redirect (an unvalidated `next` / `redirect_to`), a bare
// `window.location.href = response.url` is an open redirect / token-leak on
// the auth callback. `safeRedirect` validates the target against an explicit
// allowlist before navigating and falls back to a trusted local URL
// otherwise. Centralized here so every call site shares one policy.

// Hosts the app legitimately hands off to BEYOND its own domain: Supabase
// (the OAuth-start authorize URL), Google (the OAuth consent screen), and
// Lemon Squeezy (checkout + customer portal). Matched as an exact host or a
// subdomain of these.
const EXTERNAL_ALLOWED_HOSTS = [
  "supabase.co",
  "supabase.in",
  "accounts.google.com",
  "lemonsqueezy.com",
];

/** "app.aijobcopilot.com" -> "aijobcopilot.com"; "localhost" -> "localhost".
 *  Single-label TLDs only (the product domains are .com / .xyz), which is all
 *  this app uses. */
function rootDomain(hostname: string): string {
  const parts = hostname.split(".").filter(Boolean);
  if (parts.length <= 2) return hostname;
  return parts.slice(-2).join(".");
}

/** True when `rawUrl` is a safe navigation target: same origin, a sibling
 *  subdomain of the current root domain (the app <-> landing handoff), or one
 *  of the known external auth/billing providers. Relative URLs resolve
 *  against the current origin and pass; `javascript:` / `data:` are rejected. */
export function isAllowedRedirect(rawUrl: string): boolean {
  if (typeof window === "undefined") return false;
  let target: URL;
  try {
    target = new URL(rawUrl, window.location.origin);
  } catch {
    return false;
  }
  if (target.protocol !== "https:" && target.protocol !== "http:") return false;
  if (target.origin === window.location.origin) return true;

  const host = target.hostname.toLowerCase();
  const root = rootDomain(window.location.hostname.toLowerCase());
  if (host === root || host.endsWith(`.${root}`)) return true;

  return EXTERNAL_ALLOWED_HOSTS.some(
    (allowed) => host === allowed || host.endsWith(`.${allowed}`),
  );
}

/** Navigate to `rawUrl` when it passes {@link isAllowedRedirect}; otherwise
 *  navigate to the trusted `fallback`. */
export function safeRedirect(
  rawUrl: string | null | undefined,
  fallback: string,
): void {
  if (typeof window === "undefined") return;
  const target = String(rawUrl ?? "");
  if (target && isAllowedRedirect(target)) {
    window.location.href = target;
    return;
  }
  if (process.env.NODE_ENV !== "production") {
    // eslint-disable-next-line no-console
    console.warn(`[safeRedirect] blocked off-allowlist redirect: ${target}`);
  }
  window.location.href = fallback;
}
