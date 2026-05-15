"use client";

/**
 * CookieConsent — EU/ePrivacy-compliant cookie banner.
 *
 * Mirror of HelpmateAI's component with a dedicated localStorage key
 * (``jobagent-cookie-consent``) and event name
 * (``jobagent-cookie-consent-change``) so the two products don't
 * cross-contaminate when a developer has both running locally on
 * different ports.
 *
 * Legal posture (the rule we're encoding):
 *   • Strictly-necessary cookies (Supabase Auth session, CSRF) load
 *     regardless of consent. They're allowed by ePrivacy Directive
 *     Art. 5(3) as "strictly necessary for the service the user
 *     requested."
 *   • Error tracking (Sentry, errors only — no Session Replay) loads
 *     regardless of consent. Justified as legitimate interest under
 *     GDPR Art. 6(1)(f).
 *   • Everything else (PostHog product analytics, PostHog session
 *     replay, Sentry Session Replay) requires EXPLICIT opt-in.
 *
 * State machine — three values in localStorage["jobagent-cookie-consent"]:
 *   "pending"  → banner shown, no analytics fired
 *   "accepted" → banner hidden, PostHog + Sentry Replay live
 *   "declined" → banner hidden, no analytics, no replay
 */

import { useEffect, useState } from "react";

const STORAGE_KEY = "jobagent-cookie-consent";
const CHANGE_EVENT = "jobagent-cookie-consent-change";

export type CookieConsentValue = "pending" | "accepted" | "declined";

export function getCookieConsent(): CookieConsentValue {
  if (typeof window === "undefined") return "pending";
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === "accepted" || raw === "declined") return raw;
  } catch {
    /* incognito / Safari ITP — treat as pending */
  }
  return "pending";
}

export function useCookieConsent(): CookieConsentValue {
  const [value, setValue] = useState<CookieConsentValue>(() => getCookieConsent());
  useEffect(() => {
    if (typeof window === "undefined") return;
    function handler() {
      setValue(getCookieConsent());
    }
    window.addEventListener(CHANGE_EVENT, handler);
    window.addEventListener("storage", (event: StorageEvent) => {
      if (event.key === STORAGE_KEY) handler();
    });
    return () => {
      window.removeEventListener(CHANGE_EVENT, handler);
    };
  }, []);
  return value;
}

function setCookieConsent(next: CookieConsentValue): void {
  if (typeof window === "undefined") return;
  try {
    if (next === "pending") {
      window.localStorage.removeItem(STORAGE_KEY);
    } else {
      window.localStorage.setItem(STORAGE_KEY, next);
    }
  } catch {
    /* localStorage rejected — in-page state still updates */
  }
  window.dispatchEvent(new CustomEvent(CHANGE_EVENT));
}

export function openCookiePreferences(): void {
  setCookieConsent("pending");
}

export function CookieConsentBanner(): React.ReactElement | null {
  const consent = useCookieConsent();
  // Mount guard — server renders this null, then on hydration the
  // useEffect inside useCookieConsent reads localStorage. Without
  // this we get a hydration mismatch warning when consent !== "pending".
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
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
