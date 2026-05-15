"use client";

/**
 * PostHogProvider — initializes posthog-js on first client render and
 * keeps it tied to the Supabase user across navigation.
 *
 * Wired in ``src/app/layout.tsx`` so every route (landing, workspace,
 * auth callback) emits page-view + autocapture events into the same
 * project.
 *
 * Identity flow:
 *   1. On mount, ``posthog.init`` runs once — but ONLY if the user
 *      has clicked "Accept" on the cookie banner. Until then the SDK
 *      stays uninitialized (no cookies, no events).
 *   2. The workspace shell calls ``identifyPostHogUser`` once the
 *      Supabase auth session resolves; that pairs the anonymous
 *      pre-login session to the authenticated user id (preserves the
 *      funnel — anonymous lands → signs up → runs first analysis).
 *
 * Failure modes:
 *   • NEXT_PUBLIC_POSTHOG_KEY unset → the provider renders children
 *     unchanged and emits no events. Useful for local dev.
 *   • posthog-js fails to load (network blocked, ad blocker) → the
 *     ``try/catch`` around init keeps a broken analytics import from
 *     blocking the workspace render.
 *
 * Pageview tracking lives in ``PostHogPageView`` (mounted next to
 * this provider). It's a separate component because Next 15+ requires
 * ``useSearchParams`` consumers to be wrapped in their own
 * ``<Suspense>`` boundary, and we don't want that boundary to also
 * block PostHog init for children below it.
 */

import { Suspense, useEffect } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import posthog from "posthog-js";

import { useCookieConsent } from "@/components/cookie-consent";

type PostHogProviderProps = {
  children: React.ReactNode;
};

function initPostHog(): void {
  const key = process.env.NEXT_PUBLIC_POSTHOG_KEY;
  if (!key) return;
  if (typeof window === "undefined") return;
  if ((posthog as unknown as { __loaded?: boolean }).__loaded) return;
  try {
    posthog.init(key, {
      api_host: process.env.NEXT_PUBLIC_POSTHOG_HOST || "https://eu.i.posthog.com",
      capture_pageview: false,
      autocapture: true,
      session_recording: {
        maskAllInputs: true,
      },
      respect_dnt: true,
      persistence: "localStorage+cookie",
    });
  } catch (err) {
    // eslint-disable-next-line no-console
    console.warn("[posthog] init failed", err);
  }
}

function PostHogPageView(): null {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (!(posthog as unknown as { __loaded?: boolean }).__loaded) return;
    const url = pathname + (searchParams?.toString() ? `?${searchParams.toString()}` : "");
    posthog.capture("$pageview", { $current_url: window.location.origin + url });
  }, [pathname, searchParams]);
  return null;
}

/**
 * Tie the current PostHog session to a Supabase user id. Safe to call
 * with the same id on every render — posthog-js dedupes identify
 * calls internally. Passing ``null`` resets the session to anonymous
 * (logout flow).
 */
export function identifyPostHogUser(
  userId: string | null,
  traits?: Record<string, unknown>,
): void {
  if (typeof window === "undefined") return;
  if (!(posthog as unknown as { __loaded?: boolean }).__loaded) return;
  try {
    if (!userId) {
      posthog.reset();
      return;
    }
    posthog.identify(userId, traits);
  } catch (err) {
    // eslint-disable-next-line no-console
    console.warn("[posthog] identify failed", err);
  }
}

/**
 * Attach the current user to a group for cohort analytics. Use
 * group_type="tier" with the user's plan as the key (e.g. "free",
 * "pro", "business") so dashboards can filter "free-tier funnel"
 * without per-event property filters.
 */
export function setPostHogTierGroup(tier: string | null): void {
  if (typeof window === "undefined") return;
  if (!(posthog as unknown as { __loaded?: boolean }).__loaded) return;
  if (!tier) return;
  try {
    posthog.group("tier", tier);
  } catch (err) {
    // eslint-disable-next-line no-console
    console.warn("[posthog] group failed", err);
  }
}

export function PostHogProvider({ children }: PostHogProviderProps) {
  const consent = useCookieConsent();
  useEffect(() => {
    // GDPR / ePrivacy: PostHog analytics + session replay are not
    // strictly necessary, so we only initialize after the user
    // explicitly accepts the cookie banner. Declined / pending both
    // bail — no events, no distinct_id cookie.
    if (consent === "accepted") {
      initPostHog();
      try {
        if ((posthog as unknown as { __loaded?: boolean }).__loaded) {
          posthog.opt_in_capturing();
        }
      } catch {
        /* older SDK without opt_in_capturing — init is enough */
      }
    } else if (consent === "declined") {
      try {
        if ((posthog as unknown as { __loaded?: boolean }).__loaded) {
          posthog.opt_out_capturing();
        }
      } catch {
        /* older SDK without opt_out_capturing — best effort */
      }
    }
  }, [consent]);
  return (
    <>
      <Suspense fallback={null}>
        <PostHogPageView />
      </Suspense>
      {children}
    </>
  );
}
