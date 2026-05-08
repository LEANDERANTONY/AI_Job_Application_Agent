"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import {
  exchangeGoogleCode,
  restoreAuthSession,
  signOutAuthSession,
  startGoogleSignIn,
} from "@/lib/api";
import type { AuthSessionResponse } from "@/lib/api-types";
import {
  buildAuthRedirectUrl,
  clearAuthQueryParams,
  clearStoredAuthTokens,
  persistAuthTokens,
  readStoredAuthTokens,
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

export function LandingPage() {
  const [authStatus, setAuthStatus] = useState<LandingAuthStatus>("loading");
  const [authSession, setAuthSession] = useState<AuthSessionResponse | null>(null);
  const [authActionLoading, setAuthActionLoading] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function bootAuthState() {
      const currentUrl = new URL(window.location.href);
      const authCode = currentUrl.searchParams.get("code");
      const authFlow = currentUrl.searchParams.get("auth_flow") ?? "";
      const authErrorDescription =
        currentUrl.searchParams.get("error_description") ??
        currentUrl.searchParams.get("error");

      if (authErrorDescription) {
        clearStoredAuthTokens();
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
            persistAuthTokens(response.session);
            setAuthSession(response);
            setAuthStatus("signed_in");
          }
        } catch (error) {
          clearStoredAuthTokens();
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

      const storedTokens = readStoredAuthTokens();
      if (!storedTokens) {
        if (!cancelled) {
          setAuthStatus("signed_out");
        }
        return;
      }

      setAuthStatus("restoring");
      setAuthError(null);
      try {
        const response = await restoreAuthSession(storedTokens);
        if (!cancelled) {
          persistAuthTokens(response.session);
          setAuthSession(response);
          setAuthStatus("signed_in");
        }
      } catch (error) {
        clearStoredAuthTokens();
        if (!cancelled) {
          setAuthSession(null);
          setAuthStatus("signed_out");
          setAuthError(
            error instanceof Error
              ? error.message
              : "The saved login session could not be restored.",
          );
        }
      }
    }

    void bootAuthState();

    return () => {
      cancelled = true;
    };
  }, []);

  async function handleGoogleSignIn() {
    setAuthActionLoading(true);
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
      setAuthActionLoading(false);
    }
  }

  async function handleSignOut() {
    setAuthActionLoading(true);
    setAuthError(null);

    try {
      if (authSession?.session) {
        await signOutAuthSession(authSession.session);
      }
    } catch {
      // Local cleanup remains the important part here.
    } finally {
      clearStoredAuthTokens();
      setAuthSession(null);
      setAuthStatus("signed_out");
      setAuthActionLoading(false);
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
            <div className="brand-mark">AJ</div>
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
                  disabled={authActionLoading}
                  onClick={() => void handleSignOut()}
                  type="button"
                >
                  {authActionLoading ? "Signing out..." : "Sign out"}
                </button>
              </>
            ) : authStatus === "restoring" ? (
              <button
                className="nav-link nav-link-active landing-nav-button"
              disabled={authActionLoading || authStatus === "restoring"}
              onClick={() => void handleGoogleSignIn()}
              type="button"
            >
              {authStatus === "restoring"
                ? "Restoring session..."
                : authActionLoading
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
              <Link href="https://app.job-application-copilot.xyz" className="primary-button">
                Enter workspace
              </Link>
            ) : (
              <button
                className="primary-button"
                disabled={authActionLoading || authStatus === "restoring"}
                onClick={() => void handleGoogleSignIn()}
                type="button"
              >
                {authStatus === "restoring"
                  ? "Restoring session..."
                  : authActionLoading
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
