"use client";

import { useEffect, useRef, useState } from "react";
import Image from "next/image";
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
import { humanizeApiError } from "@/lib/humanizeApiError";
import {
  buildAuthRedirectUrl,
  clearAuthQueryParams,
  clearLegacyAuthTokens,
} from "@/lib/auth-session";

const GITHUB_URL = "https://github.com/LEANDERANTONY/AI_Job_Application_Agent";
const LINKEDIN_URL = "https://www.linkedin.com/in/leander-antony-a-176319147";

// The four workspace steps, narrated for the landing. The component below
// renders these as a sticky-pinned scroll narrative — the left column
// holds the current step's visual, the right column scrolls through the
// step bodies.
const WORKBENCH_STEPS = [
  {
    eyebrow: "01 · Resume",
    title: "Drop a resume or chat one into existence",
    body:
      "Upload a PDF, Word doc, or text file and our AI pulls out everything that matters — your skills, experience, projects, publications. The layout adapts to your career stage so students lead with education and seniors lead with experience.",
    aside:
      "No resume yet? Chat with our AI builder — one question at a time, change your answers whenever you need, and your draft saves automatically for a week.",
  },
  {
    eyebrow: "02 · Job Search",
    title: "Search 12,000+ open roles in one place",
    body:
      "Live listings from Greenhouse, Lever, Ashby, and Workday — refreshed several times a day so you always see what's actually open. Filter by company, work mode, role type, or how recent the posting is. Sort by best match, newest, or alphabetically.",
    aside:
      "Saved a job that's no longer hiring? Your bookmark stays put with a clear \"Expired\" tag — nothing gets lost from your shortlist.",
  },
  {
    eyebrow: "03 · Job Detail",
    title: "See exactly what each role is asking for",
    body:
      "Our AI reads the full posting and pulls out the must-have skills, the nice-to-haves, and a clean summary. The original wording stays intact, so nothing gets lost in translation.",
    aside:
      "Picked a job from search? The job description loads instantly when you open it — no waiting around.",
  },
  {
    eyebrow: "04 · Analysis",
    title: "Get a tailored resume and cover letter",
    body:
      "Our AI rewrites your resume to highlight what matters most for the role, then writes a personalized cover letter to match. Pick from two clean themes and download as Word or PDF — whichever your application portal asks for.",
    aside:
      "Watch the AI work in real time. The first words appear in about a second, and every claim is rooted in your actual experience — no made-up details.",
  },
] as const;

type LandingAuthStatus = "loading" | "restoring" | "signed_out" | "signed_in";
type LandingPendingAction = "signin" | "signout" | "handoff" | null;

export function LandingPage() {
  const [authStatus, setAuthStatus] = useState<LandingAuthStatus>("loading");
  const [authSession, setAuthSession] = useState<AuthSessionResponse | null>(null);
  const [pendingAction, setPendingAction] =
    useState<LandingPendingAction>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  // Mobile hamburger menu state. Driven by a button in the topbar that
  // only renders on small viewports (CSS-controlled). The dropdown panel
  // sits as a floating card under the header; tapping a link or the
  // backdrop closes it. ESC also closes via the keydown effect below.
  const [menuOpen, setMenuOpen] = useState(false);

  const anyActionPending = pendingAction !== null;

  useEffect(() => {
    let cancelled = false;

    async function bootAuthState() {
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
              humanizeApiError(error, "Google sign-in failed unexpectedly."),
            );
          }
        } finally {
          clearAuthQueryParams();
        }
        return;
      }

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

  // While the mobile menu is open, listen for ESC to close it and lock
  // body scroll so the backgrounded page doesn't move under the fixed
  // panel + backdrop. Both side-effects are scoped to `menuOpen` so
  // they tear down cleanly when the menu closes.
  useEffect(() => {
    if (!menuOpen) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setMenuOpen(false);
    }
    window.addEventListener("keydown", onKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [menuOpen]);

  async function handleGoogleSignIn() {
    setPendingAction("signin");
    setAuthError(null);
    try {
      const response = await startGoogleSignIn(buildAuthRedirectUrl("/"));
      window.location.href = response.url;
    } catch (error) {
      setAuthError(
        humanizeApiError(error, "Google sign-in could not be started."),
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
      // Sign-out may fail if the cookie is already invalid. Treat as success.
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
        humanizeApiError(error, "Workspace handoff failed unexpectedly."),
      );
      setPendingAction(null);
    }
  }

  const isSignedIn = authStatus === "signed_in";
  const primaryCtaLabel = isSignedIn
    ? pendingAction === "handoff"
      ? "Opening workspace…"
      : "Enter workspace"
    : authStatus === "restoring"
    ? "Restoring session…"
    : pendingAction === "signin"
    ? "Redirecting…"
    : "Sign in with Google";

  const onPrimaryCta = isSignedIn
    ? handleEnterWorkspace
    : handleGoogleSignIn;

  return (
    <div className="l-shell">
      {/* Soft accent orbs in the page background. The opacity + blur are
          tuned so they read as ambience, not decoration. */}
      <div className="l-orb l-orb-1" aria-hidden />
      <div className="l-orb l-orb-2" aria-hidden />
      <div className="l-grain" aria-hidden />

      <header className="l-topbar">
        <div className="l-topbar-inner">
          <Link href="/" className="l-brand">
            <BrandLogo className="l-brand-logo" size={32} />
            <span className="l-brand-name">Job Application Copilot</span>
          </Link>
          {/* Desktop nav — hidden on mobile via CSS at the same
              breakpoint where the hamburger appears. */}
          <nav className="l-topbar-nav" aria-label="Landing navigation">
            <a href="#workbench" className="l-topbar-link">Workflow</a>
            <a href="#bento" className="l-topbar-link">Features</a>
            {isSignedIn ? (
              <button
                className="l-btn l-btn-ghost l-btn-sm"
                disabled={anyActionPending}
                onClick={() => void handleSignOut()}
                type="button"
              >
                {pendingAction === "signout" ? "Signing out…" : "Sign out"}
              </button>
            ) : null}
            <button
              className="l-btn l-btn-primary l-btn-sm"
              disabled={anyActionPending || authStatus === "restoring"}
              onClick={() => void onPrimaryCta()}
              type="button"
            >
              {primaryCtaLabel}
            </button>
          </nav>
          {/* Mobile hamburger button — hidden on desktop via CSS. The
              dropdown panel below renders only when open. */}
          <button
            type="button"
            className="l-topbar-burger"
            aria-label={menuOpen ? "Close menu" : "Open menu"}
            aria-expanded={menuOpen}
            aria-controls="l-topbar-menu"
            onClick={() => setMenuOpen((prev) => !prev)}
          >
            <BurgerGlyph open={menuOpen} />
          </button>
        </div>
        {menuOpen ? (
          <>
            {/* Backdrop covers the rest of the page so a tap outside
                the menu closes it. The panel itself stops propagation
                so taps inside don't bubble to the backdrop. */}
            <button
              type="button"
              className="l-topbar-menu-backdrop"
              aria-label="Close menu"
              onClick={() => setMenuOpen(false)}
            />
            <nav
              id="l-topbar-menu"
              className="l-topbar-menu"
              aria-label="Mobile navigation"
            >
              <a
                href="#workbench"
                className="l-topbar-menu-link"
                onClick={() => setMenuOpen(false)}
              >
                Workflow
              </a>
              <a
                href="#bento"
                className="l-topbar-menu-link"
                onClick={() => setMenuOpen(false)}
              >
                Features
              </a>
              <div className="l-topbar-menu-divider" aria-hidden />
              {isSignedIn ? (
                <button
                  className="l-btn l-btn-ghost l-topbar-menu-action"
                  disabled={anyActionPending}
                  onClick={() => {
                    setMenuOpen(false);
                    void handleSignOut();
                  }}
                  type="button"
                >
                  {pendingAction === "signout" ? "Signing out…" : "Sign out"}
                </button>
              ) : null}
              <button
                className="l-btn l-btn-primary l-topbar-menu-action"
                disabled={anyActionPending || authStatus === "restoring"}
                onClick={() => {
                  setMenuOpen(false);
                  void onPrimaryCta();
                }}
                type="button"
              >
                {primaryCtaLabel}
              </button>
            </nav>
          </>
        ) : null}
      </header>

      <main className="l-main">
        <LandingHero
          authError={authError}
          authStatus={authStatus}
          isSignedIn={isSignedIn}
          pendingAction={pendingAction}
          onPrimaryCta={() => void onPrimaryCta()}
          anyActionPending={anyActionPending}
        />

        <WorkbenchSection />

        <BentoSection />

        <PricingSection
          isSignedIn={isSignedIn}
          pendingAction={pendingAction}
          onPrimaryCta={() => void onPrimaryCta()}
          anyActionPending={anyActionPending}
          authStatus={authStatus}
        />

        <FinalCtaSection
          authStatus={authStatus}
          isSignedIn={isSignedIn}
          pendingAction={pendingAction}
          onPrimaryCta={() => void onPrimaryCta()}
          anyActionPending={anyActionPending}
        />
      </main>

      <LandingFooter />
    </div>
  );
}

// ─── Hero ─────────────────────────────────────────────────────────────

type HeroProps = {
  authError: string | null;
  authStatus: LandingAuthStatus;
  isSignedIn: boolean;
  pendingAction: LandingPendingAction;
  onPrimaryCta: () => void;
  anyActionPending: boolean;
};

function LandingHero({
  authError,
  authStatus,
  isSignedIn,
  pendingAction,
  onPrimaryCta,
  anyActionPending,
}: HeroProps) {
  const ctaLabel = isSignedIn
    ? pendingAction === "handoff"
      ? "Opening workspace…"
      : "Enter workspace"
    : authStatus === "restoring"
    ? "Restoring session…"
    : pendingAction === "signin"
    ? "Redirecting…"
    : "Sign in with Google";

  return (
    <section className="l-hero">
      <div className="l-hero-stack">
        <div className="l-hero-copy">
          <span className="l-eyebrow l-hero-eyebrow">
            <span className="l-eyebrow-dot" /> AI-powered application workbench
          </span>

          {/* Three deliberate lines so the title reads as a stack
              rather than a balanced wrap-pyramid:
                  Tailor every job application
                  with an
                  AI workbench.
              Each span stagger-fades on its own delay (.l-fade-up). */}
          <h1 className="l-hero-title">
            <span className="l-fade-up" style={{ animationDelay: "60ms" }}>
              Tailor every job application
            </span>
            <span className="l-fade-up" style={{ animationDelay: "180ms" }}>
              with an
            </span>
            <span
              className="l-fade-up l-hero-title-accent"
              style={{ animationDelay: "300ms" }}
            >
              AI workbench
            </span>
          </h1>

          <p
            className="l-hero-sub l-fade-up"
            style={{ animationDelay: "440ms" }}
          >
            Upload your resume, find a role you actually want, review the
            job description, and walk away with a tailored resume and
            cover letter.
          </p>

          {authError ? (
            <div className="l-notice l-notice-warning">{authError}</div>
          ) : null}

          <div
            className="l-hero-actions l-fade-up"
            style={{ animationDelay: "560ms" }}
          >
            <button
              className="l-btn l-btn-primary"
              disabled={anyActionPending || authStatus === "restoring"}
              onClick={onPrimaryCta}
              type="button"
            >
              <GoogleGlyph />
              {ctaLabel}
            </button>
            <a
              href={GITHUB_URL}
              target="_blank"
              rel="noreferrer"
              className="l-btn l-btn-ghost"
            >
              <GitHubGlyph />
              View on GitHub
            </a>
          </div>

          <ul
            className="l-hero-pills l-fade-up"
            style={{ animationDelay: "680ms" }}
          >
            <li>Smart resume reader</li>
            <li>12k+ live jobs</li>
            <li>Tailored Word + PDF</li>
            <li>Built-in AI assistant</li>
          </ul>
        </div>

        {/* Real workspace screenshot below the title at full width.
            The wrapper handles the glow + drop shadow + accent corner
            so the image feels like the centerpiece of the hero. */}
        <div className="l-hero-visual">
          <div className="l-artifact">
            <div className="l-artifact-glow" />
            <Image
              className="l-artifact-image"
              src="/landing/hero-workspace.png"
              alt="Job Application Copilot workspace — Job Search with results and saved jobs"
              width={1200}
              height={827}
              priority
            />
          </div>
        </div>
      </div>
    </section>
  );
}

// ─── Workbench (sticky scroll narrative) ──────────────────────────────
//
// Left column is `position: sticky` and stays in view while the right
// column scrolls through four step blocks. An IntersectionObserver
// watches each step block and updates `currentStep`; the left column
// has all four visuals stacked, only the active one has opacity 1.
//
// This is the centerpiece of the page — the workflow narrative.

function WorkbenchSection() {
  const [currentStep, setCurrentStep] = useState(0);
  const stepRefs = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    // Use a single "horizontal line" observer in the middle of the
    // viewport. With rootMargin -50% top / -50% bottom, the
    // observer's effective viewport collapses to a 1px line at the
    // viewport's vertical center — the step whose block crosses that
    // line is the active one. This avoids the failure mode where a
    // step block that's taller than the narrowed band can never reach
    // the threshold ratio.
    const observers: IntersectionObserver[] = [];
    stepRefs.current.forEach((node, index) => {
      if (!node) return;
      const observer = new IntersectionObserver(
        (entries) => {
          entries.forEach((entry) => {
            if (entry.isIntersecting) {
              setCurrentStep(index);
            }
          });
        },
        {
          rootMargin: "-50% 0px -50% 0px",
          threshold: 0,
        },
      );
      observer.observe(node);
      observers.push(observer);
    });
    return () => {
      observers.forEach((o) => o.disconnect());
    };
  }, []);

  return (
    <section className="l-workbench" id="workbench">
      <div className="l-section-head">
        <span className="l-eyebrow">Four steps · One flow</span>
        <h2 className="l-section-title">
          From a fresh resume to job ready application
        </h2>
      </div>

      <div className="l-workbench-grid">
        <div className="l-workbench-visual" aria-hidden>
          <div className="l-workbench-visual-stage">
            <WorkbenchVisual0 active={currentStep === 0} />
            <WorkbenchVisual1 active={currentStep === 1} />
            <WorkbenchVisual2 active={currentStep === 2} />
            <WorkbenchVisual3 active={currentStep === 3} />
          </div>
          {/* Mini step rail so the user sees they're in a 4-step
              narrative even on smaller screens where the sticky
              breaks down. */}
          <div className="l-workbench-rail">
            {WORKBENCH_STEPS.map((step, idx) => (
              <button
                key={step.eyebrow}
                type="button"
                className={`l-workbench-rail-step ${
                  currentStep === idx ? "is-active" : ""
                }`}
                onClick={() => {
                  stepRefs.current[idx]?.scrollIntoView({
                    behavior: "smooth",
                    block: "center",
                  });
                }}
                aria-label={step.eyebrow}
              >
                <span className="l-workbench-rail-num">
                  {String(idx + 1).padStart(2, "0")}
                </span>
              </button>
            ))}
          </div>
        </div>

        <div className="l-workbench-steps">
          {WORKBENCH_STEPS.map((step, idx) => (
            <div
              key={step.eyebrow}
              ref={(node) => {
                stepRefs.current[idx] = node;
              }}
              className={`l-workbench-step ${
                currentStep === idx ? "is-active" : ""
              }`}
            >
              {/* Per-step inline visual — only shown on mobile via CSS
                  (.l-workbench-step-visual { display: none } by default,
                  flipped to block at the workbench's mobile breakpoint).
                  The desktop sticky visual is hidden in that same media
                  query, so each layout has exactly one visual surface. */}
              <div className="l-workbench-step-visual" aria-hidden>
                {idx === 0 ? <WorkbenchVisual0 active /> : null}
                {idx === 1 ? <WorkbenchVisual1 active /> : null}
                {idx === 2 ? <WorkbenchVisual2 active /> : null}
                {idx === 3 ? <WorkbenchVisual3 active /> : null}
              </div>
              <span className="l-eyebrow l-workbench-eyebrow">
                {step.eyebrow}
              </span>
              <h3 className="l-workbench-title">{step.title}</h3>
              <p className="l-workbench-body">{step.body}</p>
              <p className="l-workbench-aside">{step.aside}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

// Four small "visual mocks" — pure HTML/CSS, each represents the active
// state of one workspace step. Stacked behind each other; only the
// currently-active one has opacity 1. These are intentionally minimal —
// they communicate the *shape* of each step, not pixel-perfect product
// renderings.

function WorkbenchVisual0({ active }: { active: boolean }) {
  return (
    <div
      className={`l-workbench-mock l-mock-resume ${active ? "is-active" : ""}`}
    >
      <div className="l-mock-eyebrow">STEP 01 · RESUME</div>
      <div className="l-mock-file-pill">
        <span className="l-mock-file-name">resume_v3.pdf</span>
        <span className="l-mock-file-tag">PARSED</span>
      </div>
      <div className="l-mock-hero">
        <div className="l-mock-hero-name">Aria Patel</div>
        <div className="l-mock-hero-meta">
          Staff ML Engineer · San Francisco
        </div>
      </div>
      <div className="l-mock-stats">
        <div className="l-mock-stat">
          <span className="l-mock-stat-num">12</span>
          <span className="l-mock-stat-label">roles</span>
        </div>
        <div className="l-mock-stat">
          <span className="l-mock-stat-num">27</span>
          <span className="l-mock-stat-label">skills</span>
        </div>
        <div className="l-mock-stat">
          <span className="l-mock-stat-num">9</span>
          <span className="l-mock-stat-label">years</span>
        </div>
      </div>
      <div className="l-mock-skills-block">
        <div className="l-mock-skills-head">SKILLS DETECTED</div>
        <div className="l-mock-skills">
          <span className="l-mock-chip l-mock-chip-hard">Python</span>
          <span className="l-mock-chip l-mock-chip-hard">PyTorch</span>
          <span className="l-mock-chip l-mock-chip-hard">CUDA</span>
          <span className="l-mock-chip l-mock-chip-hard">Triton</span>
          <span className="l-mock-chip l-mock-chip-hard">+12 more</span>
        </div>
      </div>
    </div>
  );
}

function WorkbenchVisual1({ active }: { active: boolean }) {
  return (
    <div
      className={`l-workbench-mock l-mock-search ${active ? "is-active" : ""}`}
    >
      <div className="l-mock-eyebrow">STEP 02 · JOB SEARCH</div>
      <div className="l-mock-search-bar">
        <span className="l-mock-search-icon">⌕</span>
        <span className="l-mock-search-text">machine learning engineer</span>
        <span className="l-mock-search-divider" />
        <span className="l-mock-search-loc">Remote</span>
      </div>
      <div className="l-mock-filters">
        <span className="l-mock-filter">Source · 2</span>
        <span className="l-mock-filter">Mode · Remote</span>
        <span className="l-mock-filter">Posted · 7d</span>
        <span className="l-mock-filter">Sort · Best match</span>
      </div>
      <div className="l-mock-matches-head">47 MATCHES · BY RELEVANCE</div>
      <div className="l-mock-results">
        <div className="l-mock-result l-mock-result-top">
          <span className="l-mock-result-badge">★ TOP MATCH</span>
          <div className="l-mock-result-title">Senior ML Engineer</div>
          <div className="l-mock-result-meta">Stripe · greenhouse · Remote</div>
        </div>
        <div className="l-mock-result">
          <div className="l-mock-result-title">ML Engineer, Inference</div>
          <div className="l-mock-result-meta">Pinterest · greenhouse</div>
        </div>
        <div className="l-mock-result">
          <div className="l-mock-result-title">Founding ML Engineer</div>
          <div className="l-mock-result-meta">Notion · ashby</div>
        </div>
      </div>
    </div>
  );
}

function WorkbenchVisual2({ active }: { active: boolean }) {
  return (
    <div
      className={`l-workbench-mock l-mock-jd ${active ? "is-active" : ""}`}
    >
      <div className="l-mock-eyebrow">STEP 03 · JOB DETAIL</div>
      <div className="l-mock-jd-title">Senior ML Engineer, Inference</div>
      <div className="l-mock-jd-sub">Anthropic · San Francisco · Hybrid</div>
      <div className="l-mock-metrics">
        <div className="l-mock-metric l-mock-metric-accent">
          <div className="l-mock-metric-num">
            87<span className="l-mock-metric-unit">%</span>
          </div>
          <div className="l-mock-metric-label">Match score</div>
        </div>
        <div className="l-mock-metric">
          <div className="l-mock-metric-num">12</div>
          <div className="l-mock-metric-label">Hard skills</div>
        </div>
        <div className="l-mock-metric">
          <div className="l-mock-metric-num">5+</div>
          <div className="l-mock-metric-label">Years req</div>
        </div>
      </div>
      <div className="l-mock-skills-block">
        <div className="l-mock-skills-head">HARD SKILLS · 5 OF 12</div>
        <div className="l-mock-skills">
          <span className="l-mock-chip l-mock-chip-hard">Python</span>
          <span className="l-mock-chip l-mock-chip-hard">CUDA</span>
          <span className="l-mock-chip l-mock-chip-hard">Triton</span>
          <span className="l-mock-chip l-mock-chip-hard">Distributed</span>
          <span className="l-mock-chip l-mock-chip-hard">Postgres</span>
        </div>
      </div>
      <div className="l-mock-skills-block">
        <div className="l-mock-skills-head">SOFT SKILLS</div>
        <div className="l-mock-skills">
          <span className="l-mock-chip l-mock-chip-soft">Mentorship</span>
          <span className="l-mock-chip l-mock-chip-soft">Cross-functional</span>
          <span className="l-mock-chip l-mock-chip-soft">Pragmatic</span>
        </div>
      </div>
    </div>
  );
}

function WorkbenchVisual3({ active }: { active: boolean }) {
  return (
    <div
      className={`l-workbench-mock l-mock-analysis ${active ? "is-active" : ""}`}
    >
      <div className="l-mock-eyebrow">STEP 04 · ANALYSIS</div>
      <div className="l-mock-pipeline">
        <div className="l-mock-stage l-mock-stage-done">
          <span className="l-mock-stage-dot l-mock-stage-dot-done">✓</span>
          <div className="l-mock-stage-body">
            <div className="l-mock-stage-row">
              <span className="l-mock-stage-title">Matchmaker</span>
              <span className="l-mock-stage-pct">100%</span>
            </div>
            <div className="l-mock-stage-detail">Scored role fit</div>
          </div>
        </div>
        <div className="l-mock-stage l-mock-stage-done">
          <span className="l-mock-stage-dot l-mock-stage-dot-done">✓</span>
          <div className="l-mock-stage-body">
            <div className="l-mock-stage-row">
              <span className="l-mock-stage-title">Forge agent</span>
              <span className="l-mock-stage-pct">100%</span>
            </div>
            <div className="l-mock-stage-detail">Drafted tailored resume</div>
          </div>
        </div>
        <div className="l-mock-stage l-mock-stage-running">
          <span className="l-mock-stage-dot l-mock-stage-dot-running" />
          <div className="l-mock-stage-body">
            <div className="l-mock-stage-row">
              <span className="l-mock-stage-title">Gatekeeper</span>
              <span className="l-mock-stage-pct">62%</span>
            </div>
            <div className="l-mock-stage-detail">Reviewing outputs…</div>
            <div className="l-mock-stage-bar">
              <div className="l-mock-stage-fill" />
            </div>
          </div>
        </div>
        <div className="l-mock-stage l-mock-stage-pending">
          <span className="l-mock-stage-dot" />
          <div className="l-mock-stage-body">
            <div className="l-mock-stage-row">
              <span className="l-mock-stage-title">Cover letter agent</span>
              <span className="l-mock-stage-pct">standby</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Bento (single-tile carousel) ─────────────────────────────────────
//
// Each tile is a full-width "stage" — only ONE is visible at a time and
// the user navigates with the arrow buttons or trackpad swipe. This
// replaces the side-by-side strip where every tile was visible at once,
// which read as a wall-of-tiles instead of a focused "now look at this
// one feature" carousel.
//
// Implementation:
//   - Strip is overflow-x: auto + scroll-snap-type: x mandatory.
//   - Each tile is `flex: 0 0 100%` so only one fills the visible
//     strip at a time.
//   - Arrow buttons + dot indicators both drive `scrollToIndex()`.
//   - Scroll listener derives the active index from scrollLeft so
//     swipe / drag interactions sync the dots without React state
//     fighting the user.

const BENTO_TILES_COUNT = 4;

function BentoSection() {
  const stripRef = useRef<HTMLDivElement | null>(null);
  const [activeIndex, setActiveIndex] = useState(0);

  function scrollToIndex(index: number) {
    const strip = stripRef.current;
    if (!strip) return;
    const clamped = Math.max(0, Math.min(BENTO_TILES_COUNT - 1, index));
    // Width per tile = strip's clientWidth (since each tile is 100%
    // wide). scrollTo by `clamped * width` lands on the tile's left.
    strip.scrollTo({
      left: clamped * strip.clientWidth,
      behavior: "smooth",
    });
  }

  // Keep `activeIndex` in sync with the user's scroll/swipe position.
  // Debounce-ish via rAF to avoid spamming setState on every scroll
  // tick.
  useEffect(() => {
    const strip = stripRef.current;
    if (!strip) return;
    let rafId = 0;
    function onScroll() {
      cancelAnimationFrame(rafId);
      rafId = requestAnimationFrame(() => {
        const width = strip!.clientWidth;
        if (!width) return;
        const idx = Math.round(strip!.scrollLeft / width);
        setActiveIndex(idx);
      });
    }
    strip.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      strip.removeEventListener("scroll", onScroll);
      cancelAnimationFrame(rafId);
    };
  }, []);

  return (
    <section className="l-bento" id="bento">
      {/* Section head matches the workbench pattern: eyebrow centered
          above title, title centered below. Arrows live below the
          carousel beside the dots — keeps the head clean and matches
          the standard carousel pattern. */}
      <div className="l-section-head">
        <span className="l-eyebrow">Built into the workbench</span>
        <h2 className="l-section-title">
          Everything else worth knowing about
        </h2>
      </div>

      <div className="l-bento-strip-wrap">
        <div className="l-bento-strip" ref={stripRef}>
          <article className="l-bento-tile">
            <span className="l-bento-eyebrow">12,000+ open jobs</span>
            <h3 className="l-bento-title">
              Greenhouse · Lever · Ashby · Workday
            </h3>
            <p className="l-bento-body">
              Live listings from 130+ companies including Stripe, Pinterest,
              Anthropic, Notion, Walmart, and Disney. Refreshed several
              times a day so you&apos;re always seeing what&apos;s actually open.
            </p>
            <div className="l-bento-providers">
              <span className="l-bento-provider">greenhouse</span>
              <span className="l-bento-provider">lever</span>
              <span className="l-bento-provider">ashby</span>
              <span className="l-bento-provider">workday</span>
            </div>
          </article>

          <article className="l-bento-tile">
            <span className="l-bento-eyebrow">Polished exports</span>
            <h3 className="l-bento-title">Two themes, two formats</h3>
            <p className="l-bento-body">
              Pick a clean ATS-safe layout or a more polished neutral look.
              Download as Word or PDF — both are identical, so use whichever
              your application portal asks for.
            </p>
            <div className="l-bento-format-row">
              <span className="l-bento-format">PDF</span>
              <span className="l-bento-format">DOCX</span>
              <span className="l-bento-format-divider" />
              <span className="l-bento-format-tag">classic_ats</span>
              <span className="l-bento-format-tag">professional_neutral</span>
            </div>
          </article>

          <article className="l-bento-tile">
            <span className="l-bento-eyebrow">No resume? No problem.</span>
            <h3 className="l-bento-title">Chat one into existence</h3>
            <p className="l-bento-body">
              Don&apos;t have a resume yet? Chat with our AI — answer
              questions naturally, change your mind whenever, and we&apos;ll
              polish everything into a clean resume at the end. Your draft
              saves for 7 days.
            </p>
            <div className="l-bento-chat">
              <div className="l-bento-chat-turn l-bento-chat-turn-bot">
                What&apos;s your latest role?
              </div>
              <div className="l-bento-chat-turn l-bento-chat-turn-user">
                Senior ML Engineer at Stripe
              </div>
              <div className="l-bento-chat-turn l-bento-chat-turn-bot">
                <span className="l-artifact-caret" />
              </div>
            </div>
          </article>

          <article className="l-bento-tile">
            <span className="l-bento-eyebrow">Built-in AI assistant</span>
            <h3 className="l-bento-title">
              Get instant answers about your application
            </h3>
            <p className="l-bento-body">
              Ask anything — which skills to highlight, how to phrase your
              summary, what gaps to address. The AI reads your resume and
              the job description so the advice is actually relevant to
              you.
            </p>
            <div className="l-bento-chat">
              <div className="l-bento-chat-turn l-bento-chat-turn-user">
                What gaps should I address for this role?
              </div>
              <div className="l-bento-chat-turn l-bento-chat-turn-bot">
                Looking at this role, you&apos;d benefit from emphasizing
                your distributed-systems work
                <span className="l-artifact-caret" />
              </div>
            </div>
          </article>
        </div>

        {/* Carousel nav row — prev arrow, dots, next arrow. Centered
            below the strip. Active dot widens into a pill; arrows
            disable at the ends. */}
        <div className="l-bento-controls">
          <button
            type="button"
            className="l-bento-nav-btn"
            onClick={() => scrollToIndex(activeIndex - 1)}
            disabled={activeIndex === 0}
            aria-label="Previous"
          >
            <ArrowGlyph direction="left" />
          </button>
          <div className="l-bento-dots" role="tablist" aria-label="Carousel">
            {Array.from({ length: BENTO_TILES_COUNT }).map((_, i) => (
              <button
                key={i}
                type="button"
                role="tab"
                aria-selected={i === activeIndex}
                aria-label={`Go to slide ${i + 1}`}
                className={`l-bento-dot ${i === activeIndex ? "is-active" : ""}`}
                onClick={() => scrollToIndex(i)}
              />
            ))}
          </div>
          <button
            type="button"
            className="l-bento-nav-btn"
            onClick={() => scrollToIndex(activeIndex + 1)}
            disabled={activeIndex === BENTO_TILES_COUNT - 1}
            aria-label="Next"
          >
            <ArrowGlyph direction="right" />
          </button>
        </div>
      </div>
    </section>
  );
}

function ArrowGlyph({ direction }: { direction: "left" | "right" }) {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
      style={{
        transform: direction === "left" ? "rotate(180deg)" : undefined,
      }}
    >
      <path d="M5 12h14" />
      <path d="m13 5 7 7-7 7" />
    </svg>
  );
}

// ─── Pricing ──────────────────────────────────────────────────────────
//
// Three-tier card with the middle "Pro" tier filled-and-floated as the
// focal anchor. Same visual structure as HelpmateAI's landing-pricing
// (mint accent over there, electric blue here). Free + Pro CTAs route
// through the existing onPrimaryCta auth handoff so a click here is
// identical to clicking "Sign in with Google" in the hero. Business
// is a mailto until there's a real sales flow.
//
// Tier caps are aspirational — there's no backend enforcement of these
// values yet; that's a follow-up. The numbers below are stylistically
// matched to HelpmateAI's pricing matrix (Free / Pro $9 / Business
// $39 per seat) so the two products price coherently as siblings.

type PricingProps = Omit<HeroProps, "authError">;

type PricingTier = {
  id: "free" | "pro" | "business";
  name: string;
  price: number;
  blurb: string;
  features: string[];
  featured?: boolean;
  ctaLabel: string;
  ctaKind: "primary" | "mailto";
  ctaHref?: string;
};

const PRICING_TIERS: PricingTier[] = [
  {
    id: "free",
    name: "Free",
    price: 0,
    blurb: "Get a feel for the workbench on a few applications.",
    ctaLabel: "Start free",
    ctaKind: "primary",
    features: [
      "3 tailored applications / month",
      "20 assistant chat turns / month",
      "50 job searches / month",
      "5 saved jobs",
      "PDF export, ATS theme",
    ],
  },
  {
    id: "pro",
    name: "Pro",
    price: 9,
    blurb: "For active job seekers running multiple tailored applications a week.",
    featured: true,
    ctaLabel: "Get Pro",
    ctaKind: "primary",
    features: [
      "20 tailored applications / month",
      "5 premium applications with GPT-5.5",
      "Unlimited job searches + saved jobs",
      "150 assistant chat turns / month",
      "PDF + DOCX export, all themes",
      "30-day workspace history",
    ],
  },
  {
    id: "business",
    name: "Business",
    price: 39,
    blurb: "Career coaches and recruiting teams. Billed per seat, per month.",
    ctaLabel: "Contact us",
    ctaKind: "mailto",
    ctaHref: "mailto:antony.leander@gmail.com?subject=Job%20Application%20Copilot%20%E2%80%94%20Business%20tier",
    features: [
      "Everything in Pro",
      "80 tailored applications / seat",
      "25 premium applications with GPT-5.5",
      "500 assistant chat turns / seat",
      "SSO, admin dashboard, shared shortlists",
      "Unlimited history, no retention TTL",
      "Priority email support",
    ],
  },
];

function PricingCheck() {
  // Inline SVG so we don't import an icon set just for one section.
  // Stroke weight matches the rest of the landing.
  return (
    <svg
      aria-hidden="true"
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}

function PricingSection({
  authStatus,
  isSignedIn,
  pendingAction,
  onPrimaryCta,
  anyActionPending,
}: PricingProps) {
  // Free + Pro share the auth-aware disabled state with the hero /
  // final CTA so they grey out during a redirect/restore. Business
  // CTA is a plain anchor — no shared state, mailto is always
  // clickable.
  const primaryDisabled = anyActionPending || authStatus === "restoring";
  void isSignedIn;
  void pendingAction;

  return (
    <section className="l-pricing" id="pricing">
      <div className="l-section-head">
        <span className="l-eyebrow">Pricing</span>
        <h2 className="l-section-title">
          Start free, upgrade when you need more
        </h2>
      </div>
      <div className="l-pricing-grid">
        {PRICING_TIERS.map((tier) => {
          const isFeatured = Boolean(tier.featured);
          return (
            <article
              key={tier.id}
              className={
                isFeatured ? "l-pricing-card is-featured" : "l-pricing-card"
              }
            >
              {isFeatured ? (
                <span className="l-pricing-badge" aria-hidden>
                  Most popular
                </span>
              ) : null}
              <header className="l-pricing-card-head">
                <p className="l-pricing-name">{tier.name}</p>
                <p className="l-pricing-blurb">{tier.blurb}</p>
              </header>
              <p className="l-pricing-price">
                <span className="num">${tier.price}</span>
                <span className="per">/month</span>
              </p>
              {/* Chrome 148+ in dark color-scheme refuses to honor
                  background-color on <button> elements — even hex !important
                  gets clobbered to the system "ButtonFace" dark gray. We
                  side-step the bug by rendering an <a role="button"> for
                  primary CTAs too; anchors respect CSS normally. The
                  onClick still triggers the auth handoff, just without
                  the native <button> semantics. */}
              {tier.ctaKind === "primary" ? (
                <a
                  className="l-pricing-cta"
                  role="button"
                  href="#"
                  tabIndex={primaryDisabled ? -1 : 0}
                  aria-disabled={primaryDisabled || undefined}
                  onClick={(event) => {
                    event.preventDefault();
                    if (primaryDisabled) return;
                    onPrimaryCta();
                  }}
                >
                  {tier.ctaLabel}
                </a>
              ) : (
                <a className="l-pricing-cta" href={tier.ctaHref}>
                  {tier.ctaLabel}
                </a>
              )}
              <ul className="l-pricing-features">
                {tier.features.map((feature) => (
                  <li key={feature}>
                    <PricingCheck />
                    <span>{feature}</span>
                  </li>
                ))}
              </ul>
            </article>
          );
        })}
      </div>
    </section>
  );
}

// ─── Final CTA ────────────────────────────────────────────────────────

type FinalCtaProps = Omit<HeroProps, "authError">;

function FinalCtaSection({
  authStatus,
  isSignedIn,
  pendingAction,
  onPrimaryCta,
  anyActionPending,
}: FinalCtaProps) {
  const ctaLabel = isSignedIn
    ? pendingAction === "handoff"
      ? "Opening workspace…"
      : "Enter workspace"
    : authStatus === "restoring"
    ? "Restoring session…"
    : pendingAction === "signin"
    ? "Redirecting…"
    : "Sign in with Google";

  return (
    <section className="l-final">
      <div className="l-final-inner">
        {/* "Ready to tailor?" promoted from a tiny eyebrow to the
            primary headline so it visually carries weight against the
            big primary button below. The earlier sub line ("One
            workspace from raw resume to…") was removed — it just
            repeated what the hero already said. */}
        <h2 className="l-final-title">Ready to tailor?</h2>
        <div className="l-final-actions">
          <button
            className="l-btn l-btn-primary l-btn-lg"
            disabled={anyActionPending || authStatus === "restoring"}
            onClick={onPrimaryCta}
            type="button"
          >
            <GoogleGlyph />
            {ctaLabel}
          </button>
        </div>
      </div>
    </section>
  );
}

// ─── Footer ───────────────────────────────────────────────────────────

function LandingFooter() {
  return (
    <footer className="l-footer">
      <div className="l-footer-inner">
        <div className="l-footer-brand">
          <p className="l-footer-name">Job Application Copilot</p>
          <p className="l-footer-copy">
            A focused workspace for preparing stronger applications from one
            place.
          </p>
          <p className="l-footer-credit">Built by Leander Antony A</p>
        </div>

        <div className="l-footer-cols">
          <div className="l-footer-col">
            <p className="l-footer-heading">Navigation</p>
            <Link href="/privacy" className="l-footer-link">
              Privacy Policy
            </Link>
          </div>
          <div className="l-footer-col">
            <p className="l-footer-heading">Socials</p>
            <a
              href={GITHUB_URL}
              target="_blank"
              rel="noreferrer"
              className="l-footer-link"
            >
              GitHub
            </a>
            <a
              href={LINKEDIN_URL}
              target="_blank"
              rel="noreferrer"
              className="l-footer-link"
            >
              LinkedIn
            </a>
          </div>
        </div>
      </div>
    </footer>
  );
}

// ─── Inline icon glyphs ───────────────────────────────────────────────

function GoogleGlyph() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 18 18"
      aria-hidden
      className="l-glyph"
    >
      <path
        fill="#4285F4"
        d="M17.64 9.2c0-.64-.06-1.25-.16-1.84H9v3.48h4.84a4.14 4.14 0 0 1-1.8 2.71v2.26h2.91c1.7-1.57 2.69-3.88 2.69-6.61z"
      />
      <path
        fill="#34A853"
        d="M9 18c2.43 0 4.47-.8 5.96-2.18l-2.91-2.26c-.81.54-1.84.86-3.05.86-2.34 0-4.32-1.58-5.03-3.71H.96v2.33A9 9 0 0 0 9 18z"
      />
      <path
        fill="#FBBC05"
        d="M3.97 10.7A5.41 5.41 0 0 1 3.68 9c0-.59.1-1.16.29-1.7V4.97H.96A9 9 0 0 0 0 9c0 1.45.35 2.83.96 4.03l3.01-2.33z"
      />
      <path
        fill="#EA4335"
        d="M9 3.58c1.32 0 2.5.45 3.44 1.34l2.58-2.58A9 9 0 0 0 9 0 9 9 0 0 0 .96 4.97l3.01 2.33C4.68 5.16 6.66 3.58 9 3.58z"
      />
    </svg>
  );
}

// Animated hamburger ↔ close glyph. Three horizontal bars when closed
// (the conventional hamburger), rotated into an X when open. Pure
// inline SVG so it inherits the button's `currentColor` and respects
// the same theming pipeline as every other glyph on the page.
function BurgerGlyph({ open }: { open: boolean }) {
  return (
    <svg
      width="22"
      height="22"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      aria-hidden
    >
      {open ? (
        <>
          <line x1="6" y1="6" x2="18" y2="18" />
          <line x1="6" y1="18" x2="18" y2="6" />
        </>
      ) : (
        <>
          <line x1="4" y1="6" x2="20" y2="6" />
          <line x1="4" y1="12" x2="20" y2="12" />
          <line x1="4" y1="18" x2="20" y2="18" />
        </>
      )}
    </svg>
  );
}

function GitHubGlyph() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="currentColor"
      aria-hidden
      className="l-glyph"
    >
      <path d="M12 .5C5.65.5.5 5.65.5 12c0 5.08 3.29 9.39 7.86 10.91.58.11.79-.25.79-.55 0-.27-.01-1-.02-1.96-3.2.7-3.87-1.54-3.87-1.54-.52-1.32-1.27-1.67-1.27-1.67-1.04-.71.08-.7.08-.7 1.15.08 1.75 1.18 1.75 1.18 1.02 1.75 2.69 1.25 3.34.96.1-.74.4-1.25.72-1.54-2.55-.29-5.24-1.27-5.24-5.66 0-1.25.45-2.27 1.18-3.07-.12-.29-.51-1.46.11-3.04 0 0 .96-.31 3.15 1.17.91-.25 1.89-.38 2.86-.39.97 0 1.95.13 2.86.39 2.18-1.48 3.14-1.17 3.14-1.17.62 1.58.23 2.75.11 3.04.74.8 1.18 1.82 1.18 3.07 0 4.4-2.69 5.36-5.25 5.65.41.36.78 1.06.78 2.14 0 1.55-.01 2.79-.01 3.17 0 .31.21.67.8.55C20.21 21.39 23.5 17.08 23.5 12 23.5 5.65 18.35.5 12 .5z" />
    </svg>
  );
}
