"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { BrandLogo } from "@/components/BrandLogo";
import {
  exchangeGoogleCode,
  restoreAuthSession,
  signOutAuthSession,
  startWorkspaceHandoff,
  startGoogleSignIn,
} from "@/lib/api";
import type { AuthSessionResponse } from "@/lib/api-types";
import {
  buildAuthRedirectUrl,
  clearAuthQueryParams,
  clearLegacyAuthTokens,
} from "@/lib/auth-session";

const SOCIAL_LINKS = [
  {
    label: "GitHub",
    href: "https://github.com/LEANDERANTONY/AI_Job_Application_Agent",
  },
  {
    label: "LinkedIn",
    href: "https://www.linkedin.com/in/leander-antony-a-176319147",
  },
] as const;

type LandingAuthStatus = "loading" | "restoring" | "signed_out" | "signed_in";
// Tracks WHICH auth action is in flight rather than a shared boolean.
// Without this, clicking "Enter workspace" flipped a single
// authActionLoading flag → the sibling "Sign out" button (which
// switched its label on the same flag) would show "Signing out…" until
// the workspace handoff redirect completed.
type LandingPendingAction = "signin" | "signout" | "handoff" | null;

export function LandingPage() {
  const [authStatus, setAuthStatus] = useState<LandingAuthStatus>("loading");
  const [authSession, setAuthSession] = useState<AuthSessionResponse | null>(null);
  const [pendingAction, setPendingAction] =
    useState<LandingPendingAction>(null);
  const [authError, setAuthError] = useState<string | null>(null);

  const anyActionPending = pendingAction !== null;

  useEffect(() => {
    let cancelled = false;

    async function bootAuthState() {
      // One-shot migration off the old localStorage token blob; safe to
      // remove a few weeks after the cookie cutover lands.
      clearLegacyAuthTokens();

      const currentUrl = new URL(window.location.href);
      const authCode = currentUrl.searchParams.get("code");
      const authFlow = currentUrl.searchParams.get("auth_flow") ?? "";
      const authErrorDescription =
        currentUrl.searchParams.get("error_description") ??
        currentUrl.searchParams.get("error");

      if (authErrorDescription) {
        clearAuthQueryParams();
        if (!cancelled) {
          setAuthSession(null);
          setAuthStatus("signed_out");
          setAuthError(authErrorDescription);
        }
        return;
      }

      if (authCode) {
        setAuthStatus("restoring");
        setAuthError(null);
        try {
          const response = await exchangeGoogleCode(
            authCode,
            authFlow,
            buildAuthRedirectUrl("/"),
          );
          if (!cancelled) {
            setAuthSession(response);
            setAuthStatus("signed_in");
          }
        } catch (error) {
          if (!cancelled) {
            setAuthSession(null);
            setAuthStatus("signed_out");
            setAuthError(
              error instanceof Error
                ? error.message
                : "Google sign-in failed unexpectedly.",
            );
          }
        } finally {
          clearAuthQueryParams();
        }
        return;
      }

      // No URL code: try a silent restore. Cookie may or may not be
      // present; failure here is the expected first-visit state, so we
      // suppress the error toast.
      setAuthStatus("restoring");
      setAuthError(null);
      try {
        const response = await restoreAuthSession();
        if (!cancelled) {
          setAuthSession(response);
          setAuthStatus("signed_in");
        }
      } catch {
        if (!cancelled) {
          setAuthSession(null);
          setAuthStatus("signed_out");
        }
      }
    }

    void bootAuthState();

    return () => {
      cancelled = true;
    };
  }, []);

  async function handleGoogleSignIn() {
    setPendingAction("signin");
    setAuthError(null);
    try {
      const response = await startGoogleSignIn(buildAuthRedirectUrl("/"));
      window.location.href = response.url;
    } catch (error) {
      setAuthError(
        error instanceof Error
          ? error.message
          : "Google sign-in could not be started.",
      );
      setPendingAction(null);
    }
  }

  async function handleSignOut() {
    setPendingAction("signout");
    setAuthError(null);

    try {
      await signOutAuthSession();
    } catch {
      // Sign-out may fail if the cookie is already invalid. Treat as
      // success on the client. Backend clears cookies on failure too.
    } finally {
      setAuthSession(null);
      setAuthStatus("signed_out");
      setPendingAction(null);
    }
  }

  async function handleEnterWorkspace() {
    setPendingAction("handoff");
    setAuthError(null);
    try {
      const response = await startWorkspaceHandoff(
        "https://app.job-application-copilot.xyz",
      );
      window.location.href = response.redirect_url;
    } catch (error) {
      setAuthError(
        error instanceof Error
          ? error.message
          : "Workspace handoff failed unexpectedly.",
      );
      setPendingAction(null);
    }
  }

  const isSignedIn = authStatus === "signed_in";
  const signedInLabel =
    authSession?.app_user.display_name ||
    authSession?.app_user.email ||
    "Signed in";

  return (
    <div className="app-shell">
      <div className="bg-orb bg-orb-one" />
      <div className="bg-orb bg-orb-two" />

      <header className="topbar">
          <div className="brand">
            <div className="brand-mark">
              <BrandLogo className="brand-logo-image" size={44} />
            </div>
            <div>
              <p className="brand-title">Job Application Copilot</p>
            </div>
          </div>
          <nav className="nav-links" aria-label="Landing navigation">
            {isSignedIn ? (
              <>
                <span className="status-chip status-chip-live">Signed in</span>
                <button
                  className="secondary-button landing-nav-button landing-nav-signout"
                  disabled={anyActionPending}
                  onClick={() => void handleSignOut()}
                  type="button"
                >
                  {pendingAction === "signout" ? "Signing out..." : "Sign out"}
                </button>
              </>
            ) : authStatus === "restoring" ? (
              <button
                className="nav-link nav-link-active landing-nav-button"
              disabled={anyActionPending || authStatus === "restoring"}
              onClick={() => void handleGoogleSignIn()}
              type="button"
            >
              {authStatus === "restoring"
                ? "Restoring session..."
                : pendingAction === "signin"
                  ? "Redirecting..."
                  : "Sign in"}
            </button>
          ) : null}
        </nav>
      </header>

      <main className="page-frame landing-page-frame">
        <section className="hero landing-hero">
          <h1>Job Application Copilot</h1>
          <p className="hero-copy landing-hero-copy">
            Upload your resume, find or import the right role, review the job description,
            and generate tailored application documents in one guided flow.
          </p>

          {authError ? <div className="notice-panel notice-warning">{authError}</div> : null}

          <div className="hero-actions">
            {isSignedIn ? (
              <button
                className="primary-button"
                disabled={anyActionPending}
                onClick={() => void handleEnterWorkspace()}
                type="button"
              >
                {pendingAction === "handoff"
                  ? "Opening workspace..."
                  : "Enter workspace"}
              </button>
            ) : (
              <button
                className="primary-button"
                disabled={anyActionPending || authStatus === "restoring"}
                onClick={() => void handleGoogleSignIn()}
                type="button"
              >
                {authStatus === "restoring"
                  ? "Restoring session..."
                  : pendingAction === "signin"
                    ? "Redirecting..."
                    : "Sign in"}
              </button>
            )}
          </div>
        </section>
      </main>

      <footer className="landing-footer">
        <div className="landing-footer-inner">
          <div className="landing-footer-brand">
            <p className="landing-footer-title">Job Application Copilot</p>
            <p className="landing-footer-copy">
              A focused workspace for preparing stronger applications from one place.
            </p>
            <p className="landing-footer-credit">Built by Leander Antony A</p>
          </div>

          <div className="landing-footer-links">
            <div className="landing-footer-column">
              <p className="landing-footer-heading">Navigation</p>
              <Link href="/privacy" className="landing-footer-link">
                Privacy Policy
              </Link>
            </div>

            <div className="landing-footer-column">
              <p className="landing-footer-heading">Socials</p>
              {SOCIAL_LINKS.map((item) => (
                <a
                  key={item.label}
                  href={item.href}
                  className="landing-footer-link"
                  target="_blank"
                  rel="noreferrer"
                >
                  {item.label}
                </a>
              ))}
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
