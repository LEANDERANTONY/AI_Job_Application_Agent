"use client";

/**
 * CookieConsent — EU/ePrivacy-compliant cookie banner.
 *
 * Legal posture (the rule we're encoding):
 *   • Strictly-necessary cookies (Supabase Auth session, CSRF, and
 *     this consent-preference cookie itself) load regardless of
 *     consent. Allowed by ePrivacy Directive Art. 5(3) as "strictly
 *     necessary for the service the user requested." Storing the
 *     user's own consent choice is the textbook example.
 *   • Error tracking (Sentry, errors only — no Session Replay) loads
 *     regardless of consent. Legitimate interest under GDPR
 *     Art. 6(1)(f) — crash reporting to operate the service securely.
 *   • Everything else (PostHog product analytics, PostHog session
 *     replay, Sentry Session Replay) requires EXPLICIT opt-in.
 *
 * Persistence — a FIRST-PARTY COOKIE, not localStorage:
 *   The marketing site is the apex `job-application-copilot.xyz`
 *   (Next host rewrite → /landing) and the workspace is
 *   `app.job-application-copilot.xyz`. Those are different ORIGINS,
 *   so localStorage can't be shared — a user who consented on the
 *   landing was re-prompted on the app. We store the choice in a
 *   cookie scoped to the parent domain
 *   (`Domain=.job-application-copilot.xyz`) so BOTH hosts read the
 *   same value: consent given on either side is honored on the other,
 *   in either visit order. On any other host (localhost,
 *   *.vercel.app previews) we omit Domain so it's a host-only cookie
 *   — the browser would reject a `.job-application-copilot.xyz`
 *   cookie there anyway and there's no cross-subdomain story to
 *   support.
 *
 *   Cookie name `jobagent-cookie-consent`, values:
 *     (absent)   → "pending": banner shown, no analytics fired
 *     "accepted" → banner hidden, PostHog + Sentry Replay live
 *     "declined" → banner hidden, no analytics, no replay
 *
 *   A one-time read-fallback honors the OLD localStorage key so users
 *   who consented before this change aren't re-prompted on the origin
 *   they accepted on.
 *
 * Re-opening the choice: a footer link "Cookie preferences" calls
 * ``openCookiePreferences()`` which clears the cookie (back to
 * "pending") and dispatches a CustomEvent so the banner re-mounts. We
 * don't call ``location.reload()`` so workspace state is preserved.
 *
 * Why not Cookiebot/Iubenda/Termly:
 *   • Their pricing for our scale (~$11-27/mo) buys compliance theater
 *     dashboards we don't need
 *   • Their banners load third-party JS BEFORE the user has consented
 *     to third-party JS, which is its own compliance footgun
 *   • Our policy is simple: two categories ("essential" + "all"),
 *     two buttons. Building it ourselves is ~120 lines and gives us
 *     pixel control over the theme
 *
 * Boot-time note: ``frontend/instrumentation-client.ts`` re-implements
 * the cookie read inline (it's a config module that must not import
 * React). Keep ``readConsentCookie`` here and its ``readConsent``
 * there in sync.
 */

import { useEffect, useState } from "react";

/** Cookie name AND the legacy localStorage key (same string — the
 *  pre-cookie implementation used localStorage under this key). */
const STORAGE_KEY = "jobagent-cookie-consent";
const CHANGE_EVENT = "jobagent-cookie-consent-change";
/** ~12 months. Long enough not to nag; short enough to be a
 *  defensible re-consent interval under common DPA guidance. */
const MAX_AGE_SECONDS = 60 * 60 * 24 * 365;

export type CookieConsentValue = "pending" | "accepted" | "declined";

/**
 * Cross-tab change signal. Cookies (unlike localStorage) don't emit a
 * `storage` event, so without this, accepting in one tab would leave
 * the banner stuck in another open tab. BroadcastChannel is supported
 * across all our target browsers; if absent we simply lose instant
 * cross-tab sync (a minor nicety), never correctness.
 */
const consentChannel: BroadcastChannel | null =
  typeof window !== "undefined" && "BroadcastChannel" in window
    ? new BroadcastChannel(STORAGE_KEY)
    : null;

/**
 * The `; Domain=...` attribute that lets the cookie be shared across
 * the marketing apex and the app subdomain. Empty (host-only) on any
 * other host so dev/preview keep working.
 */
function consentCookieDomain(): string {
  if (typeof window === "undefined") return "";
  const host = window.location.hostname;
  if (
    host === "job-application-copilot.xyz" ||
    host.endsWith(".job-application-copilot.xyz")
  ) {
    return "; Domain=.job-application-copilot.xyz";
  }
  return "";
}

function readConsentCookie(): CookieConsentValue {
  if (typeof document === "undefined") return "pending";
  const prefix = `${STORAGE_KEY}=`;
  const row = document.cookie.split("; ").find((c) => c.startsWith(prefix));
  if (!row) return "pending";
  const raw = decodeURIComponent(row.slice(prefix.length));
  if (raw === "accepted" || raw === "declined") return raw;
  return "pending";
}

/**
 * Read the current consent without subscribing to changes. Safe on
 * the server (returns "pending" — banner shows on first paint, then
 * the mount guard re-reads on the client).
 */
export function getCookieConsent(): CookieConsentValue {
  if (typeof window === "undefined") return "pending";
  const fromCookie = readConsentCookie();
  if (fromCookie !== "pending") return fromCookie;
  // One-time migration read: users who consented BEFORE this cookie
  // existed only have the value in localStorage on whatever origin
  // they accepted on. Honor it so they aren't re-prompted. Getter
  // stays side-effect-free; we don't rewrite it as a cookie here —
  // the legacy value only ever helps on the same origin, which is
  // exactly the (correct) pre-change behavior.
  try {
    const legacy = window.localStorage.getItem(STORAGE_KEY);
    if (legacy === "accepted" || legacy === "declined") return legacy;
  } catch {
    // localStorage can throw in incognito + Safari ITP — ignore.
  }
  return "pending";
}

/**
 * Hook that returns the current consent and re-renders when it
 * changes. Use from any client component that gates behavior on
 * consent (e.g. PostHogProvider, Sentry Replay opt-in).
 */
export function useCookieConsent(): CookieConsentValue {
  const [value, setValue] = useState<CookieConsentValue>(() => getCookieConsent());
  useEffect(() => {
    if (typeof window === "undefined") return;
    function handler() {
      setValue(getCookieConsent());
    }
    window.addEventListener(CHANGE_EVENT, handler);
    consentChannel?.addEventListener("message", handler);
    return () => {
      window.removeEventListener(CHANGE_EVENT, handler);
      consentChannel?.removeEventListener("message", handler);
    };
  }, []);
  return value;
}

/**
 * Imperatively set the consent state. Called by the banner buttons +
 * the footer "Cookie preferences" link. Writes the parent-domain
 * cookie (or clears it for "pending"), then notifies same-tab
 * (CHANGE_EVENT) and other tabs (BroadcastChannel).
 */
function setCookieConsent(next: CookieConsentValue): void {
  if (typeof document === "undefined") return;
  const domain = consentCookieDomain();
  const secure = window.location.protocol === "https:" ? "; Secure" : "";
  if (next === "pending") {
    // Clearing: Domain/Path MUST match the set call or the delete
    // misses the parent-domain cookie and the banner won't reappear.
    document.cookie = `${STORAGE_KEY}=; Max-Age=0; Path=/; SameSite=Lax${secure}${domain}`;
    // Drop any legacy localStorage copy too so it can't resurrect a
    // stale choice through the migration read above.
    try {
      window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore — incognito / quota
    }
  } else {
    document.cookie = `${STORAGE_KEY}=${next}; Max-Age=${MAX_AGE_SECONDS}; Path=/; SameSite=Lax${secure}${domain}`;
  }
  window.dispatchEvent(new CustomEvent(CHANGE_EVENT));
  try {
    consentChannel?.postMessage("change");
  } catch {
    // channel closed (e.g. during teardown) — same-tab event already fired
  }
}

/**
 * Public function for the footer link "Cookie preferences". Resets
 * the consent to "pending" which re-renders the banner so the user
 * can change their mind.
 */
export function openCookiePreferences(): void {
  setCookieConsent("pending");
}

export function CookieConsentBanner(): React.ReactElement | null {
  const consent = useCookieConsent();
  // Mount guard — server renders this null, then on hydration the
  // useEffect inside useCookieConsent reads the cookie. Without
  // this we get a hydration mismatch warning when consent !== "pending".
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    // Intentional one-shot mount/hydration guard: the server renders
    // null, the client flips mounted post-hydration so reading the
    // consent cookie can't cause a hydration mismatch. setState-in-
    // effect is correct here (syncing React with "we're now on the
    // client") — not a cascading-render smell.
    setMounted(true);
  }, []);
  if (!mounted) return null;
  if (consent !== "pending") return null;

  return (
    <div
      role="dialog"
      aria-labelledby="cookie-consent-heading"
      aria-describedby="cookie-consent-body"
      className="ja-cookie-banner"
    >
      <div className="ja-cookie-content">
        <div className="ja-cookie-text">
          <p id="cookie-consent-heading" className="ja-cookie-heading">
            We use cookies
          </p>
          <p id="cookie-consent-body" className="ja-cookie-body">
            Essential cookies keep you signed in. With your consent we also use
            product analytics and session replay to understand how the workspace
            is used and fix bugs faster. You can change this any time from the
            footer.
          </p>
        </div>
        <div className="ja-cookie-actions">
          <button
            type="button"
            className="ja-cookie-btn ja-cookie-btn-ghost"
            onClick={() => setCookieConsent("declined")}
          >
            Decline non-essential
          </button>
          <button
            type="button"
            className="ja-cookie-btn ja-cookie-btn-primary"
            onClick={() => setCookieConsent("accepted")}
          >
            Accept
          </button>
        </div>
      </div>
    </div>
  );
}
