"use client";

import { useEffect, useRef, useState } from "react";
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
    title: "Drop a resume — or chat one into existence.",
    body:
      "An LLM-first hybrid parser turns a PDF, DOCX or TXT into a structured profile in seconds — Skills bucketed by category, Experience, Projects + Publications, with a per-profile section order so students lead with Education and seniors with Experience.",
    aside:
      "No resume yet? An LLM builder asks one question at a time, backtracks when you correct it, and auto-saves your draft for 7 days.",
  },
  {
    eyebrow: "02 · Job Search",
    title: "Search a cached index of ~12k roles across four ATSes.",
    body:
      "Greenhouse, Lever, Ashby, and Workday — refreshed every ~30 minutes by a pg_cron job. Filter by source, work mode, employment type, and posted-within window. Sort by relevance, recency, or company A → Z.",
    aside:
      "Saved a job that closed upstream? The cleanup pass tombstones it instead of deleting — your bookmark survives with an honest \"Expired\" badge.",
  },
  {
    eyebrow: "03 · Job Detail",
    title: "Parse a JD with hard + soft skills extracted.",
    body:
      "An LLM hybrid parser hits 0.99 across a 15-fixture quality runner — vs 0.78 from the deterministic baseline. Hard skills, soft skills, summary, and the original body sections rendered verbatim from the parser, no reorder, no dedupe.",
    aside:
      "Selected a job from search? The JD prefills from the cached index — one Supabase read, no extra round trip.",
  },
  {
    eyebrow: "04 · Analysis",
    title: "Generate a tailored resume + cover letter.",
    body:
      "The agentic workflow runs Tailoring → Review → Resume Generation → Cover Letter. Two themes — Classic ATS and Professional Neutral — both shipped through PDF and DOCX with a shared palette so they read as the same document.",
    aside:
      "Streaming SSE: meta → delta × N → followups → done. First token visible in under 1.5 s, grounded in your workspace state.",
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
          <nav className="l-topbar-nav" aria-label="Landing navigation">
            <a href="#workbench" className="l-topbar-link">Workflow</a>
            <a href="#bento" className="l-topbar-link">Features</a>
            <a
              href={GITHUB_URL}
              target="_blank"
              rel="noreferrer"
              className="l-topbar-link"
            >
              GitHub
            </a>
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
        </div>
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
              AI workbench.
            </span>
          </h1>

          <p
            className="l-hero-sub l-fade-up"
            style={{ animationDelay: "440ms" }}
          >
            Upload your resume, find or import a role, review the job
            description, and ship a tailored resume + cover letter in one
            guided flow.
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
            <li>Resume parsing</li>
            <li>Cached job search</li>
            <li>Tailored DOCX + PDF</li>
            <li>Streaming assistant</li>
          </ul>
        </div>

        {/* Artifact mock now sits below the title at full width. The
            existing <ArtifactPreview /> markup is unchanged — only the
            wrapper styling shifted in globals.css. */}
        <div className="l-hero-visual">
          <ArtifactPreview />
        </div>
      </div>
    </section>
  );
}

// ─── Hero artifact preview ────────────────────────────────────────────
//
// A static-but-alive preview of the workspace's artifact viewer. Pure
// HTML/CSS — no screenshot — so it stays pixel-perfect at every viewport.
// The streaming caret blinks via a CSS keyframe (see globals.css).

function ArtifactPreview() {
  return (
    <div className="l-artifact" aria-hidden>
      {/* Soft glow ring behind the card. */}
      <div className="l-artifact-glow" />

      <div className="l-artifact-card">
        <div className="l-artifact-head">
          <div className="l-artifact-tabs">
            <span className="l-artifact-tab l-artifact-tab-active">
              Tailored Resume
            </span>
            <span className="l-artifact-tab">Cover Letter</span>
          </div>
          <span className="l-artifact-stream-chip">
            <span className="l-artifact-stream-dot" /> Streaming
          </span>
        </div>

        <div className="l-artifact-body">
          <div className="l-artifact-name">Aria Patel</div>
          <div className="l-artifact-role">
            Senior ML Engineer · Inference Platform
          </div>

          <div className="l-artifact-section">
            <div className="l-artifact-section-eyebrow">SUMMARY</div>
            <p className="l-artifact-paragraph">
              Eight years building inference platforms across Anthropic and
              Stripe. Led the rate-limiter rewrite and the multi-tenant
              tokenizer that landed inside the SLO.
            </p>
          </div>

          <div className="l-artifact-section">
            <div className="l-artifact-section-eyebrow">SKILLS</div>
            <div className="l-artifact-skills">
              <span className="l-artifact-chip">Python</span>
              <span className="l-artifact-chip">PyTorch</span>
              <span className="l-artifact-chip">CUDA</span>
              <span className="l-artifact-chip">Triton</span>
              <span className="l-artifact-chip">Ray</span>
              <span className="l-artifact-chip">Postgres</span>
            </div>
          </div>

          {/* Experience section makes the artifact preview feel like a
              real recruiter-ready resume rather than a 3-row mock.
              Streaming caret lives mid-bullet to suggest the AI is
              actively writing this section right now. */}
          <div className="l-artifact-section">
            <div className="l-artifact-section-eyebrow">EXPERIENCE</div>
            <div className="l-artifact-job">
              <div className="l-artifact-job-head">
                <span className="l-artifact-job-title">
                  Staff ML Engineer · Anthropic
                </span>
                <span className="l-artifact-job-dates">2023 — Present</span>
              </div>
              <ul className="l-artifact-bullets">
                <li>
                  Cut p99 inference latency 38% by rewriting the
                  rate-limiter around a token-bucket per-tenant pool.
                </li>
                <li>
                  Owned the multi-tenant tokenizer rollout — shipped
                  inside the 99.9% availability SLO across 14 regions
                  <span className="l-artifact-caret" />
                </li>
              </ul>
            </div>
            <div className="l-artifact-job">
              <div className="l-artifact-job-head">
                <span className="l-artifact-job-title">
                  Senior ML Engineer · Stripe
                </span>
                <span className="l-artifact-job-dates">2020 — 2023</span>
              </div>
              <ul className="l-artifact-bullets">
                <li>
                  Built Stripe&apos;s feature platform serving 30k+ models
                  with low-latency online retrieval.
                </li>
              </ul>
            </div>
          </div>
        </div>

        <div className="l-artifact-foot">
          <div className="l-artifact-theme">
            <span className="l-artifact-theme-label">Theme</span>
            <span className="l-artifact-theme-chip l-artifact-theme-chip-active">
              Classic ATS
            </span>
            <span className="l-artifact-theme-chip">Professional Neutral</span>
          </div>
          <div className="l-artifact-downloads">
            <span className="l-artifact-download">PDF</span>
            <span className="l-artifact-download">DOCX</span>
          </div>
        </div>
      </div>
    </div>
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
          A guided workflow from raw resume to recruiter-ready DOCX.
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
      <div className="l-mock-dropzone">
        <div className="l-mock-file">resume_v3.pdf</div>
        <div className="l-mock-file-meta">2.1 MB · parsed</div>
      </div>
      <div className="l-mock-fields">
        <div className="l-mock-field">
          <span className="l-mock-field-label">Name</span>
          <span className="l-mock-field-value">Aria Patel</span>
        </div>
        <div className="l-mock-field">
          <span className="l-mock-field-label">Role</span>
          <span className="l-mock-field-value">Staff ML Engineer</span>
        </div>
        <div className="l-mock-field">
          <span className="l-mock-field-label">Skills</span>
          <span className="l-mock-field-value">Python, PyTorch, CUDA + 14</span>
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
      </div>
      <div className="l-mock-filters">
        <span className="l-mock-filter">Source · 2 selected</span>
        <span className="l-mock-filter">Work mode · Remote</span>
        <span className="l-mock-filter">Sort · Most recent</span>
      </div>
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
      <div className="l-mock-skills-block">
        <div className="l-mock-skills-head">HARD SKILLS</div>
        <div className="l-mock-skills">
          <span className="l-mock-chip l-mock-chip-hard">Python</span>
          <span className="l-mock-chip l-mock-chip-hard">CUDA</span>
          <span className="l-mock-chip l-mock-chip-hard">Triton</span>
          <span className="l-mock-chip l-mock-chip-hard">Distributed systems</span>
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
      <div className="l-mock-timeline">
        <div className="l-mock-timeline-row">
          <span className="l-mock-timeline-dot l-mock-timeline-dot-done" />
          Tailoring · 0:02
        </div>
        <div className="l-mock-timeline-row">
          <span className="l-mock-timeline-dot l-mock-timeline-dot-done" />
          Review · 0:04
        </div>
        <div className="l-mock-timeline-row l-mock-timeline-row-active">
          <span className="l-mock-timeline-dot l-mock-timeline-dot-running" />
          Resume generation · running
        </div>
        <div className="l-mock-timeline-row l-mock-timeline-row-pending">
          <span className="l-mock-timeline-dot" />
          Cover letter
        </div>
      </div>
      <div className="l-mock-doc">
        <div className="l-mock-doc-name">Tailored Resume · Aria Patel</div>
        <div className="l-mock-doc-line" />
        <div className="l-mock-doc-line l-mock-doc-line-short" />
        <div className="l-mock-doc-line" />
        <div className="l-mock-doc-line l-mock-doc-line-mid">
          <span className="l-artifact-caret" />
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

const BENTO_TILES_COUNT = 5;

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
          Everything else worth knowing about.
        </h2>
      </div>

      <div className="l-bento-strip-wrap">
        <div className="l-bento-strip" ref={stripRef}>
          <article className="l-bento-tile">
            <span className="l-bento-eyebrow">FOUR ATS COVERAGE</span>
            <h3 className="l-bento-title">
              Greenhouse · Lever · Ashby · Workday
            </h3>
            <p className="l-bento-body">
              ~12,000 active roles indexed across 79 Greenhouse boards, 30
              Lever sites, 36 Ashby boards, and 11 Workday Fortune-500
              tenants. Refreshed by a pg_cron job every ~30 minutes.
            </p>
            <div className="l-bento-providers">
              <span className="l-bento-provider">greenhouse</span>
              <span className="l-bento-provider">lever</span>
              <span className="l-bento-provider">ashby</span>
              <span className="l-bento-provider">workday</span>
            </div>
          </article>

          <article className="l-bento-tile">
            <span className="l-bento-eyebrow">RANKED SEARCH</span>
            <h3 className="l-bento-title">~360 ms warm</h3>
            <p className="l-bento-body">
              FTS + filters + sort branches inside a single Postgres RPC.
              ~25 s live fan-out replaced by one round trip.
            </p>
            <pre className="l-bento-code">
{`-- search_cached_jobs_ranked
SELECT * FROM cached_jobs
 WHERE removed_at IS NULL
   AND tsv @@ websearch_to_tsquery($1)
 ORDER BY ts_rank(tsv, q) DESC
 LIMIT $2;`}
            </pre>
          </article>

          <article className="l-bento-tile">
            <span className="l-bento-eyebrow">EXPORT</span>
            <h3 className="l-bento-title">Two themes, two formats.</h3>
            <p className="l-bento-body">
              Classic ATS or Professional Neutral, both shipped through PDF
              and DOCX with a shared palette so they read as the same
              document.
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
            <span className="l-bento-eyebrow">RESUME BUILDER</span>
            <h3 className="l-bento-title">Chat one into existence.</h3>
            <p className="l-bento-body">
              An LLM-led conversation that backtracks when you correct it,
              auto-saves your draft for 7 days, and structures everything
              into a tailored profile at export time.
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
            <span className="l-bento-eyebrow">STREAMING ASSISTANT</span>
            <h3 className="l-bento-title">
              First token under 1.5 s, grounded in your workspace.
            </h3>
            <p className="l-bento-body">
              SSE event stream — meta → delta × N → followups → done. The
              assistant reads your candidate profile, the parsed JD, and the
              current artifact to ground its answer.
            </p>
            <div className="l-bento-stream">
              <div className="l-bento-stream-event">
                <span className="l-bento-stream-key">event</span> meta
              </div>
              <div className="l-bento-stream-event">
                <span className="l-bento-stream-key">event</span> delta
                <span className="l-bento-stream-text">
                  Based on your experience, the strongest match is…
                  <span className="l-artifact-caret" />
                </span>
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
            <p className="l-footer-heading">Project</p>
            <a
              href={GITHUB_URL}
              target="_blank"
              rel="noreferrer"
              className="l-footer-link"
            >
              GitHub
            </a>
            <a
              href={`${GITHUB_URL}/blob/main/DEVLOG.md`}
              target="_blank"
              rel="noreferrer"
              className="l-footer-link"
            >
              DEVLOG
            </a>
            <a
              href={`${GITHUB_URL}/tree/main/docs/adr`}
              target="_blank"
              rel="noreferrer"
              className="l-footer-link"
            >
              ADRs
            </a>
          </div>
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
