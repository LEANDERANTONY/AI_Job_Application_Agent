"use client";

// WorkspaceShell — Direction B "Workbench" redesign.
//
// Visual + structural rewrite. All hook signatures, API calls, state
// slices, and handlers from the previous shell are preserved verbatim
// (see Q&A in DEVLOG / handoff README). Only the JSX (chrome + tab
// switching) and the surrounding CSS classes change.
//
// What's new visually:
//   - b-topbar: brand + ⌘K trigger + account popover (sign in fallback)
//   - b-rail: four-step rail with gating + done/active visual states
//   - b-hero: dynamic per-active-tab title/sub + status pill
//   - b-canvas: vertical stack of regions (one per tab body)
//   - Floating assistant FAB (replaces the old left sidebar mount)
//   - ⌘K command palette overlay (new)
//
// Behavior preservation checklist (handoff README §3):
//   ✓ Step rail navigation respects WorkspaceMainTab + completion gates
//   ✓ All resume/upload/builder flows unchanged
//   ✓ Job search + saved jobs + URL import unchanged
//   ✓ JD paste + URL + file upload unchanged
//   ✓ useAnalysisJob polling + currentWorkflowStage unchanged
//   ✓ Streaming SSE + caret behavior unchanged
//   ✓ Artifact tabs + downloads unchanged
//   ✓ Daily quota + plan tier + saved-workspace meta still surfaced in the
//     account popover
//   ✓ FAB-mounted assistant retains useAssistantHistory persistence

import { useEffect, useMemo, useRef, useState } from "react";
import Image from "next/image";

import {
  commitResumeBuilderResume,
  downloadBase64File,
  exportResumeBuilderArtifact,
  generateResumeBuilderResume,
  getCustomerPortalUrl,
  loadLatestResumeBuilderSession,
  previewResumeBuilderArtifact,
  resetResumeBuilderSession,
  resolveJobUrl,
  searchJobs,
  sendResumeBuilderMessage,
  startResumeBuilderSession,
  streamWorkspaceAssistantAnswer,
  updateResumeBuilderDraft,
  uploadJobDescriptionFile,
  saveWorkspaceSnapshot,
  uploadResumeFile,
  TierLimitExceededError,
} from "@/lib/api";
import type {
  ArtifactTheme,
  CandidateProfile,
  DailyQuotaStatus,
  EmploymentType,
  JobPosting,
  JobResolveResponse,
  JobSearchResponse,
  JobSortBy,
  LoadSavedWorkspaceResponse,
  ResumeBuilderSessionResponse,
  WorkMode,
  WorkspaceAnalysisResponse,
  WorkspaceArtifactExportFormat,
  WorkspaceJobDescriptionUploadResponse,
  WorkspaceResumeUploadResponse,
} from "@/lib/api-types";
import {
  identifyPostHogUser,
  setPostHogTierGroup,
} from "@/components/posthog-provider";
import { humanizeApiError } from "@/lib/humanizeApiError";
import { isAllowedRedirect } from "@/lib/redirectAllowlist";
import { useAccessibleDialog } from "@/lib/useAccessibleDialog";
import { buildJobReview } from "@/lib/job-workspace";
import { CheckIcon, SearchIcon } from "@/components/workspace/icons";
import {
  AssistantPanel,
  useAssistantStreamingStore,
} from "@/components/workspace/AssistantPanel";
import { CommandPalette } from "@/components/workspace/CommandPalette";
import { TokenUsageMeter } from "@/components/workspace/TokenUsageMeter";
import {
  ArtifactViewer,
  type ArtifactTab,
} from "@/components/workspace/ArtifactViewer";
import { AnalysisRunner } from "@/components/workspace/AnalysisRunner";
import { JDReview } from "@/components/workspace/JDReview";
import { JobSearch } from "@/components/workspace/JobSearch";
import {
  ResumeIntake,
  type ResumeIntakeMode,
} from "@/components/workspace/ResumeIntake";
import { useArtifactExport } from "@/hooks/useArtifactExport";
import {
  buildAssistantHistoryPayload,
  useAssistantHistory,
} from "@/hooks/useAssistantHistory";
import { useAnalysisJob } from "@/hooks/useAnalysisJob";
import { useSavedJobs } from "@/hooks/useSavedJobs";
import { useWorkspaceQuota } from "@/hooks/useWorkspaceQuota";
import { useWorkspaceSession } from "@/hooks/useWorkspaceSession";

type Notice = {
  level: "info" | "success" | "warning";
  message: string;
  /** Optional CTA shown alongside the message. Used by the 429
   *  tier-limit handling (Step 7b) to render an "Upgrade" link
   *  pointing at the pricing page. Other notices leave this
   *  undefined and only the message renders. */
  action?: {
    label: string;
    href: string;
  };
} | null;

type WorkspaceMainTab = "resume" | "jobs" | "jd" | "analysis";

const STEP_LABELS: Record<
  WorkspaceMainTab,
  { number: string; label: string; shortLabel: string }
> = {
  // `shortLabel` is the mobile-only label shown at ≤ 540 px, where the
  // full "Job Search" / "Job Detail" wraps to two lines inside the rail
  // pill. The CSS hides one or the other based on viewport; the
  // button's `aria-label` carries the full label for screen readers
  // regardless of which span is visible.
  resume: { number: "01", label: "Resume", shortLabel: "Resume" },
  jobs: { number: "02", label: "Job Search", shortLabel: "Jobs" },
  jd: { number: "03", label: "Job Detail", shortLabel: "JD" },
  analysis: { number: "04", label: "Analysis", shortLabel: "Analysis" },
};

// Initial result-page size. Job boards lead with a short page and let
// the user pull more rather than dumping a 50-row wall — "Load more"
// (handleLoadMore) requests another SEARCH_PAGE_SIZE window each click.
// Backend hard-caps a page at 50, so this stays well under the cap.
const SEARCH_PAGE_SIZE = 20;

// Debounce for the auto-apply-on-filter-change effect. A multi-select
// chip toggle fires one state update per click; without a debounce,
// picking three employment types = three searches. 400 ms batches a
// burst of toggles into a single request while still feeling instant.
const FILTER_APPLY_DEBOUNCE_MS = 400;

const STEP_ORDER: WorkspaceMainTab[] = ["resume", "jobs", "jd", "analysis"];

function noticeClassName(level: NonNullable<Notice>["level"]) {
  if (level === "success") return "b-notice b-notice-success";
  if (level === "warning") return "b-notice b-notice-warning";
  return "b-notice";
}

function pipToneClass(tone: "live" | "ready" | "idle" | "next") {
  if (tone === "live") return "rd-pip rd-pip-live";
  if (tone === "ready") return "rd-pip rd-pip-ready";
  return "rd-pip";
}

function latestRole(profile: CandidateProfile | null) {
  const entry = profile?.experience?.[0];
  if (!entry) return null;
  if (entry.title && entry.organization) {
    return `${entry.title} · ${entry.organization}`;
  }
  return entry.title || entry.organization || null;
}

function formatUtcTimestamp(value: string) {
  if (!value) return "";
  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime())) return value;
  return timestamp.toLocaleString(undefined, {
    timeZone: "UTC",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatRemainingCalls(dailyQuota: DailyQuotaStatus | null) {
  if (!dailyQuota) return "Unavailable";
  if (dailyQuota.remaining_calls === null || dailyQuota.max_calls === null) {
    // Unlimited tiers are internal/admin (no daily cost cap). Append
    // the tier so the dev account is obviously identifiable in the
    // popover and a paying user with `null` caps (e.g. an explicit
    // "Unlimited" addon down the road) sees the same shape.
    const tier = (dailyQuota.plan_tier || "").trim().toLowerCase();
    if (tier === "internal" || tier === "admin") {
      return `Unlimited (${formatTier(tier)})`;
    }
    return "Unlimited";
  }
  return `${dailyQuota.remaining_calls}/${dailyQuota.max_calls}`;
}

/**
 * Capitalize a raw plan_tier string ("internal", "business", "pro",
 * "free", "admin") for display. Backend stores these lowercase as
 * enum-ish strings; the UI should render them as proper nouns.
 * Falls back to the raw value (with first letter uppercased) for
 * any tier we haven't enumerated explicitly, so a future "enterprise"
 * tier still renders sanely without a code change.
 */
function formatTier(tier: string | null | undefined): string {
  const normalized = (tier || "").trim().toLowerCase();
  switch (normalized) {
    case "free":
      return "Free";
    case "pro":
    case "paid":
    case "plus":
      return "Pro";
    case "business":
      return "Business";
    case "internal":
      return "Internal";
    case "admin":
      return "Admin";
    default:
      if (!normalized) return "Free";
      return normalized.charAt(0).toUpperCase() + normalized.slice(1);
  }
}

function getInitialMainTab(): WorkspaceMainTab {
  if (typeof window === "undefined") return "resume";

  const tabParam = new URLSearchParams(window.location.search).get("tab");
  if (
    tabParam === "resume" ||
    tabParam === "jobs" ||
    tabParam === "jd" ||
    tabParam === "analysis"
  ) {
    return tabParam;
  }

  const hashTab = window.location.hash.replace(/^#/, "");
  if (
    hashTab === "resume" ||
    hashTab === "jobs" ||
    hashTab === "jd" ||
    hashTab === "analysis"
  ) {
    return hashTab as WorkspaceMainTab;
  }

  return "resume";
}

export function WorkspaceShell() {
  const [mainTab, setMainTab] = useState<WorkspaceMainTab>(getInitialMainTab);
  const [accountMenuOpen, setAccountMenuOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [forceAssistantOpen, setForceAssistantOpen] = useState(false);
  const [workspaceNotice, setWorkspaceNotice] = useState<Notice>(null);
  // Premium toggle state. Owned at this level so both AnalysisRunner
  // (UI) and useAnalysisJob (network call) read the same source of
  // truth. We deliberately DO NOT reset between runs -- if the user
  // turned the toggle on, a Re-run should respect that intent (the
  // toggle is right next to the Run button, so the user sees what
  // they're committing to). The defensive effect below force-flips
  // it off when the quota snapshot reports premium isn't available
  // (e.g. tier downgrade between sessions), so a stale toggle from
  // a previous Pro session can never accidentally fire on Free.
  const [premium, setPremium] = useState(false);

  const {
    authStatus,
    authSession,
    setAuthSession: _setAuthSession,
    authError,
    authActionLoading,
    workspaceSaveMeta,
    setWorkspaceSaveMeta: _setWorkspaceSaveMeta,
    workspaceReloading,
    autoSaving,
    dailyQuota,
    signIn: handleGoogleSignIn,
    signOutAuth,
    persistLatestWorkspace,
    reloadSavedWorkspace,
  } = useWorkspaceSession({ setNotice: setWorkspaceNotice });
  void _setAuthSession;
  void _setWorkspaceSaveMeta;

  // Quota snapshot for the Premium toggle + per-counter indicators.
  // The hook owns the fetch lifecycle (mount + refresh after each
  // workflow run) and gates itself on authStatus="signed_in" so we
  // don't spam the backend with 401s while auth is restoring.
  const { quota: workspaceQuota, refresh: refreshWorkspaceQuota } =
    useWorkspaceQuota({ authStatus });

  // Defensive: if the quota snapshot says premium isn't available
  // (e.g. user signed out + back in as a Free tier), force the
  // toggle off so the next run doesn't 429 with a Pro+ rejection.
  useEffect(() => {
    if (!workspaceQuota) return;
    if (!workspaceQuota.premium_available && premium) {
      setPremium(false);
    }
  }, [workspaceQuota, premium]);

  // Post-LS-checkout return: when the user comes back from the
  // hosted checkout, LS redirects to our success URL with a
  // `?ls_checkout=success` query param appended by the frontend's
  // pricing CTA. We refresh the quota snapshot once so the tier
  // badge picks up the new state without waiting for the next
  // workflow run. The webhook handler also invalidates the backend
  // cache, so the refresh sees the post-upsert tier value.
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (authStatus !== "signed_in") return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("ls_checkout") !== "success") return;
    refreshWorkspaceQuota();
    // Strip the param so a later refresh doesn't re-fire the
    // refetch. replaceState keeps history clean (no extra back-
    // button stop on the success URL).
    params.delete("ls_checkout");
    const search = params.toString();
    const next = `${window.location.pathname}${search ? `?${search}` : ""}${window.location.hash}`;
    window.history.replaceState(null, "", next);
  }, [authStatus, refreshWorkspaceQuota]);

  // Workspace is for signed-in users only. The session restore in
  // `useWorkspaceSession` flips authStatus to "signed_out" once it's
  // confirmed there are no valid auth cookies. Bounce to the landing
  // page — which lives on a DIFFERENT origin in production:
  //   workspace: app.<domain>.xyz
  //   landing:    <domain>.xyz
  // (NEXT_PUBLIC_SITE_URL is the WORKSPACE URL per the existing repo
  // convention, so we can't reuse it here without going in a circle.)
  // We derive the landing host by stripping a leading `app.` from the
  // current hostname — symmetric with the middleware's
  // `hostname.startsWith("app.")` check. In localhost dev there's no
  // `app.` prefix so we just navigate to "/" on the same origin.
  // We DON'T redirect on "loading" or "restoring" because those are
  // transient and would cause an unnecessary landing-page flash for
  // the common case (already signed in).
  useEffect(() => {
    if (authStatus !== "signed_out") return;
    if (typeof window === "undefined") return;
    const { protocol, hostname, port } = window.location;
    const landingHost = hostname.startsWith("app.")
      ? hostname.slice("app.".length)
      : hostname;
    const portSuffix = port ? `:${port}` : "";
    const landingUrl =
      landingHost === hostname
        ? "/"
        : `${protocol}//${landingHost}${portSuffix}/`;
    window.location.href = landingUrl;
  }, [authStatus]);

  const [searchQuery, setSearchQuery] = useState("machine learning engineer");
  const [searchLocation, setSearchLocation] = useState("");
  // Multi-select filter state. Empty arrays = no filter applied. The
  // Source dropdown defaults to "Any source" (empty) so the cache RPC
  // searches across every provider — picking specific ones narrows the
  // results to just those tokens. Same model for work modes + types.
  const [sourceFilters, setSourceFilters] = useState<string[]>([]);
  const [workModes, setWorkModes] = useState<WorkMode[]>([]);
  const [employmentTypes, setEmploymentTypes] = useState<EmploymentType[]>([]);
  const [sortBy, setSortBy] = useState<JobSortBy>("relevance");
  const [postedWithinDays, setPostedWithinDays] = useState("");
  const [searching, setSearching] = useState(false);
  // Distinct from `searching`: a "Load more" fetch keeps the existing
  // results on screen and appends, so the main Search button must NOT
  // show its busy state and the grid must NOT collapse to a spinner.
  const [loadingMore, setLoadingMore] = useState(false);
  const [searchResults, setSearchResults] = useState<JobSearchResponse | null>(
    null,
  );
  const [searchNotice, setSearchNotice] = useState<Notice>(null);
  // Monotonic search token. Filter/sort changes auto-fire searches, so
  // a slow live-path response could land AFTER a newer filtered one and
  // clobber it. Every fresh search (runSearch) bumps this; a response
  // only applies if its token is still current. "Load more" captures
  // the token without bumping — a filter change mid-load supersedes the
  // stale page so we don't append old-filter rows onto a new result set.
  const searchSeqRef = useRef(0);

  const [jobUrl, setJobUrl] = useState("");
  const [importing, setImporting] = useState(false);
  const [activeJob, setActiveJob] = useState<JobPosting | null>(null);

  const [selectedResumeFile, setSelectedResumeFile] = useState<File | null>(
    null,
  );
  const [resumeUploading, setResumeUploading] = useState(false);
  const [resumeNotice, setResumeNotice] = useState<Notice>(null);
  const [resumeState, setResumeState] =
    useState<WorkspaceResumeUploadResponse | null>(null);
  const [resumeIntakeMode, setResumeIntakeMode] =
    useState<ResumeIntakeMode>("upload");
  const [resumeBuilderSession, setResumeBuilderSession] =
    useState<ResumeBuilderSessionResponse | null>(null);
  const [resumeBuilderAnswer, setResumeBuilderAnswer] = useState("");
  const [resumeBuilderLoading, setResumeBuilderLoading] = useState(false);
  const [resumeBuilderGenerating, setResumeBuilderGenerating] = useState(false);
  const [resumeBuilderCommitting, setResumeBuilderCommitting] = useState(false);
  const [resumeBuilderNotice, setResumeBuilderNotice] = useState<Notice>(null);
  const [resumeBuilderInitialized, setResumeBuilderInitialized] =
    useState(false);
  const [resumeBuilderEditing, setResumeBuilderEditing] = useState(false);
  const [resumeBuilderCollapsed, setResumeBuilderCollapsed] = useState(false);
  // Resume-builder conversation log. Appended on every /message
  // response so the user sees the chat thread building up. Resets
  // when the session is cleared (commit / restart). Lives in client
  // state because the backend's `assistant_message` is per-turn — the
  // server-side conversation_history is for LLM continuity, not for
  // the UI to read back.
  const [resumeBuilderChatLog, setResumeBuilderChatLog] = useState<
    Array<{ role: "user" | "assistant"; content: string }>
  >([]);
  // Phase 6 download row state. The user picks a theme + downloads
  // their generated base resume as PDF or DOCX, after Generate
  // finishes. `resumeBuilderExporting` holds the in-flight format
  // string (e.g. "pdf" / "docx") so each button can show a per-button
  // "Preparing…" label without locking out the other button.
  const [resumeBuilderExportTheme, setResumeBuilderExportTheme] =
    useState<ArtifactTheme>("professional_neutral");
  const [resumeBuilderExporting, setResumeBuilderExporting] = useState<
    WorkspaceArtifactExportFormat | null
  >(null);
  // In-builder live themed preview. Once a base resume is generated we
  // render it as themed HTML (the same look the final ArtifactViewer
  // ships) so the user can browse all 6 themes before downloading — a
  // conversion surface, since the gated themes preview freely but only
  // Professional is downloadable on Free. `resumeBuilderExportTheme`
  // doubles as the preview theme: one picker drives both.
  const [resumeBuilderPreviewHtml, setResumeBuilderPreviewHtml] = useState<
    string | null
  >(null);
  const [resumeBuilderPreviewLoading, setResumeBuilderPreviewLoading] =
    useState(false);
  const [resumeBuilderDraftForm, setResumeBuilderDraftForm] = useState({
    full_name: "",
    location: "",
    contact_lines: "",
    target_role: "",
    professional_summary: "",
    experience_notes: "",
    education_notes: "",
    skills: "",
    certifications: "",
    projects_notes: "",
    publications: "",
  });

  const [selectedJobFile, setSelectedJobFile] = useState<File | null>(null);
  const [jobFileUploading, setJobFileUploading] = useState(false);
  const [jobFileNotice, setJobFileNotice] = useState<Notice>(null);
  const [jobFileState, setJobFileState] =
    useState<WorkspaceJobDescriptionUploadResponse | null>(null);
  const [jobInputCollapsed, setJobInputCollapsed] = useState(false);
  // Tracks what produced the current `jobFileState` (review M24). Only a
  // discrete load (file upload, load-from-search, resolved URL, snapshot
  // restore) should auto-collapse the JD textarea; the debounced paste
  // auto-parse must NOT — collapsing the input ~1.5s after a paste yanks it
  // out from under a user who's still reading/editing. Set immediately before
  // each setJobFileState so the collapse effect reads the right source.
  const jobFileSourceRef = useRef<"discrete" | "paste">("discrete");

  const [manualJobText, setManualJobText] = useState("");
  const [analysisState, setAnalysisState] =
    useState<WorkspaceAnalysisResponse | null>(null);

  const {
    artifactTab,
    setArtifactTab,
    artifactExporting,
    artifactPreviewHtml,
    artifactPreviewTitle,
    artifactPreviewLoading,
    currentArtifact,
    resumeTheme,
    coverLetterTheme,
    setResumeTheme,
    setCoverLetterTheme,
    exportArtifact: handleArtifactExport,
    resetArtifacts,
  } = useArtifactExport({
    analysisState,
    setNotice: setWorkspaceNotice,
  });

  const { assistantTurns, setAssistantTurns } = useAssistantHistory({
    analysisState,
    authSession,
  });

  const [assistantQuestion, setAssistantQuestion] = useState("");
  const [assistantSending, setAssistantSending] = useState(false);
  // The in-flight streaming buffer lives in a zustand store consumed
  // only by AssistantPanel (PERF-1). The shell writes it non-reactively
  // via getState() inside submitAssistantQuestion so token deltas no
  // longer re-render the whole workspace tree.
  // Holds the AbortController for the in-flight stream so route changes
  // (or a clear-conversation press) can cancel the fetch and stop
  // accumulating tokens into a turn the user no longer wants.
  const assistantStreamAbortRef = useRef<AbortController | null>(null);

  // Cancel any in-flight stream on unmount so a user navigating away
  // mid-answer doesn't leak the connection.
  useEffect(() => {
    return () => {
      assistantStreamAbortRef.current?.abort();
      assistantStreamAbortRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (activeJob?.description_text) {
      setManualJobText(activeJob.description_text);
      setJobFileState(null);
    }
  }, [activeJob]);

  useEffect(() => {
    // Auto-collapse the JD input on a discrete load only (review M24).
    // `activeJob` (load-from-search) always collapses; a `jobFileState` set by
    // the paste auto-parse does NOT, so the textarea stays put while the user
    // keeps reading/editing right after a paste.
    if (activeJob || (jobFileState && jobFileSourceRef.current !== "paste")) {
      setJobInputCollapsed(true);
    }
  }, [activeJob, jobFileState]);

  // ── JD auto-parse via LLM ─────────────────────────────────────────
  // Debounced effect that pipes pasted / loaded-from-search JD text
  // through the same /workspace/job-description/upload endpoint a
  // file upload uses. The endpoint returns the LLM-parsed
  // jd_summary_view + requirements; that response lands in
  // `jobFileState`, and JDReview's precedence chain
  // (analysisState > jobFileState > review) automatically picks it
  // up to render the Must-Have Themes / Nice-to-Have Signals panels
  // from LLM output instead of the brittle frontend regex.
  //
  // Why we route paste through the SAME endpoint as upload (instead
  // of a new /jd/parse-text route): zero new backend surface, zero
  // new tests, and a single LLM-quality contract for ALL three input
  // paths (paste / upload / load-from-search). The endpoint takes
  // any file via UploadedFilePayloadModel — sending the pasted text
  // as a synthetic ``pasted.txt`` blob skips the file-extraction
  // step internally (it's already text) and falls straight through
  // to build_job_description_from_text_auto.
  //
  // Guards (all four required before firing):
  //   1. authStatus === "signed_in" — the endpoint requires auth.
  //   2. text length >= 100 chars — under that, regex is fine and
  //      we don't want to burn token quota on placeholder text.
  //   3. text hash differs from the last successfully-parsed text
  //      — avoids re-parsing the same content on every render or
  //      after the user pastes back the same JD they had before.
  //   4. text differs from jobFileState.job_description_text — if a
  //      file upload (or earlier paste-parse) already set
  //      jobFileState from the same text, skip.
  //
  // Debounce: 1500 ms after the LAST keystroke. Cancels the prior
  // timer + aborts the in-flight request, so a fast typist who pauses
  // briefly + resumes never fires multiple parses.
  const lastParsedTextRef = useRef<string>("");
  const parseDebounceRef = useRef<number | null>(null);
  const parseAbortRef = useRef<AbortController | null>(null);
  useEffect(() => {
    if (parseDebounceRef.current !== null) {
      window.clearTimeout(parseDebounceRef.current);
      parseDebounceRef.current = null;
    }
    if (parseAbortRef.current) {
      parseAbortRef.current.abort();
      parseAbortRef.current = null;
    }
    const text = manualJobText.trim();
    if (!text || text.length < 100) return;
    if (authStatus !== "signed_in") return;
    if (text === lastParsedTextRef.current) return;
    if (jobFileState?.job_description_text?.trim() === text) {
      // Already parsed by an upload or earlier paste — sync the cache
      // so future renders of the same text don't re-fire.
      lastParsedTextRef.current = text;
      return;
    }

    parseDebounceRef.current = window.setTimeout(async () => {
      parseDebounceRef.current = null;
      const abort = new AbortController();
      parseAbortRef.current = abort;
      setJobFileUploading(true);
      try {
        // Use a synthetic .txt blob to reuse the existing upload path.
        // The backend extracts text from .txt files as a no-op and
        // routes straight into build_job_description_from_text_auto
        // (the same LLM path the file-upload UI uses).
        const blob = new Blob([text], { type: "text/plain" });
        const file = new File([blob], "pasted.txt", { type: "text/plain" });
        // Pass the abort signal so a superseded parse cancels its
        // in-flight fetch instead of running to completion (M16).
        const response = await uploadJobDescriptionFile(file, abort.signal);
        if (abort.signal.aborted) return;
        lastParsedTextRef.current = text;
        // Paste-originated parse — do NOT auto-collapse the input (M24).
        jobFileSourceRef.current = "paste";
        setJobFileState(response);
      } catch (error) {
        if (abort.signal.aborted) return;
        // Surface feedback instead of silently swallowing (M8): the
        // upload route enforces the weekly LLM budget BEFORE parsing, so
        // a token-exhausted user hits a 429 here. There is no global
        // request interceptor — the prior comment claimed one that does
        // not exist. A tier-limit gets the upgrade CTA; any other failure
        // gets a quiet notice (the regex preview still renders the JD).
        if (error instanceof TierLimitExceededError) {
          setJobFileNotice({
            level: "warning",
            message: error.message,
            // Consistent /pricing destination with the other upgrade CTAs
            // (the /pricing route fix is tracked separately as H1/FLOW-2).
            action: { label: "Upgrade plan", href: "/pricing" },
          });
        } else {
          setJobFileNotice({
            level: "warning",
            message:
              "Couldn't auto-parse this job description — showing a basic read instead.",
          });
        }
      } finally {
        if (parseAbortRef.current === abort) {
          parseAbortRef.current = null;
        }
        setJobFileUploading(false);
      }
    }, 1500);

    return () => {
      if (parseDebounceRef.current !== null) {
        window.clearTimeout(parseDebounceRef.current);
        parseDebounceRef.current = null;
      }
    };
    // Intentionally only re-run on manualJobText / authStatus changes.
    // jobFileState IS read inside the effect but we don't want updates
    // to it to re-trigger the effect (the effect SETS it, which would
    // create a loop). The "already-parsed" check above handles the
    // stale-jobFileState case safely on the next text change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [manualJobText, authStatus]);

  const {
    savedJobs,
    savedJobsLoading,
    savedJobsNotice,
    savedJobActionId,
    savedJobIds,
    latestSavedJobAt,
    savedJobsEnabled,
    saveJob: handleSaveJob,
    removeJob: handleRemoveSavedJob,
    resetSavedJobs,
  } = useSavedJobs({ authStatus, authSession });

  const activeResumeState = resumeState ?? analysisState;
  const resumeText = activeResumeState?.resume_document.text ?? "";
  const currentProfile = activeResumeState?.candidate_profile ?? null;
  // Memoized so the multi-pass regex in buildJobReview (job-workspace.ts)
  // does not re-run on every shell render — most importantly on each JD
  // keystroke (PERF-2). A stable `review` identity is ALSO what lets the
  // React.memo on JDReview below actually skip re-renders.
  const review = useMemo(
    () => (manualJobText.trim() ? buildJobReview(manualJobText, activeJob) : null),
    [manualJobText, activeJob],
  );

  const analysisIsStale = Boolean(
    analysisState &&
      (analysisState.resume_document.text !== resumeText ||
        analysisState.job_description.raw_text !== manualJobText.trim()),
  );

  const {
    analysisLoading,
    analysisJobState,
    setAnalysisJobState: _setAnalysisJobState,
    currentWorkflowStage,
    runAnalysis: handleRunAnalysis,
    cancelAnalysis: handleCancelAnalysis,
    analysisCancelling,
    resetAnalysis,
  } = useAnalysisJob({
    resumeText,
    jobDescriptionText: manualJobText,
    resumeFiletype: activeResumeState?.resume_document.filetype,
    resumeSource: activeResumeState?.resume_document.source,
    importedJobPosting: activeJob,
    authStatus,
    premium,
    onRunFinished: refreshWorkspaceQuota,
    setNotice: setWorkspaceNotice,
    setAnalysisState,
    onCompleted: onAnalysisCompleted,
  });
  void _setAnalysisJobState;

  // Hoisted via `function` declaration so it's accessible at the
  // hook-call site above. Closure-resolves at call-time, by which
  // point all referenced bindings (setArtifactTab, resetArtifacts,
  // persistLatestWorkspace) are in scope.
  async function onAnalysisCompleted(
    result: WorkspaceAnalysisResponse,
  ): Promise<string> {
    setArtifactTab("resume");
    setMainTab("analysis");
    resetArtifacts();
    const savedWorkspace = await persistLatestWorkspace(result);
    return savedWorkspace
      ? `Workflow finished in ${result.workflow.mode} mode and saved workspace refreshes until ${formatUtcTimestamp(savedWorkspace.expires_at)} UTC.`
      : `Workflow finished in ${result.workflow.mode} mode.`;
  }

  // ── Step gating + active-tab metadata ───────────────────────────
  // Resume / Job Search / Job Detail are independently accessible —
  // a user might paste a JD they care about before they have a resume,
  // or browse listings without uploading anything. The only step that
  // truly needs prerequisites is Analysis (it can't run without both
  // a resume and a JD), and that's enforced in AnalysisRunner.tsx via
  // the page-level "Upload a resume to proceed" affordance, not by
  // hiding the rail step.
  //
  // Earlier this gated `jobs` on `currentProfile` and `jd` on
  // `currentProfile || activeJob`, which forced an upload-resume-first
  // flow even when the user just wanted to look around. The lock
  // surfaced as "Upload a resume to unlock" tooltips on the rail.
  const stepReady = useMemo(
    () => ({
      resume: true,
      jobs: true,
      jd: true,
      analysis: Boolean(resumeText.trim() && manualJobText.trim()),
    }),
    [manualJobText, resumeText],
  );

  const stepDone = useMemo(
    () => ({
      resume: Boolean(currentProfile),
      jobs: Boolean(activeJob),
      jd: Boolean(review),
      analysis: Boolean(analysisState),
    }),
    [activeJob, analysisState, currentProfile, review],
  );

  type TabMeta = {
    id: WorkspaceMainTab;
    title: string;
    sub: string;
    statusLabel: string;
    tone: "live" | "ready" | "idle" | "next";
  };

  const tabsMeta = useMemo<Record<WorkspaceMainTab, TabMeta>>(() => {
    return {
      resume: {
        id: "resume",
        title: "Resume",
        sub: "Upload an existing resume or build a base one with the assistant.",
        statusLabel: currentProfile ? "Ready" : "Start here",
        tone: currentProfile ? "live" : "ready",
      },
      jobs: {
        id: "jobs",
        title: "Job Search",
        sub: "Find a role from live listings, paste a job link, or open one from your shortlist.",
        statusLabel: activeJob
          ? "Role loaded"
          : searchResults?.results.length
            ? `${searchResults.total_results} matches`
            : "Search or import",
        tone: activeJob
          ? "live"
          : searchResults?.results.length
            ? "ready"
            : "idle",
      },
      jd: {
        id: "jd",
        title: "Job Detail",
        sub: "Add the job description and review the parsed skills, requirements, and summary.",
        statusLabel: review
          ? "JD ready"
          : manualJobText.trim()
            ? "Drafting"
            : "Add a JD",
        tone: review ? "live" : manualJobText.trim() ? "ready" : "idle",
      },
      analysis: {
        id: "analysis",
        title: "Analysis & Outputs",
        sub: "Trigger the agentic workflow, then review and export your tailored documents.",
        statusLabel: analysisState
          ? "Outputs ready"
          : stepReady.analysis
            ? "Ready to run"
            : "Waiting",
        tone: analysisState
          ? "live"
          : stepReady.analysis
            ? "ready"
            : "idle",
      },
    };
  }, [
    activeJob,
    analysisState,
    currentProfile,
    manualJobText,
    review,
    searchResults,
    stepReady.analysis,
  ]);

  const activeTabMeta = tabsMeta[mainTab];

  // Hero context shown across all tabs. Falls back to honest text
  // when no role is loaded — never displays a fake placeholder role
  // (the prior "Anthropic · Senior ML Engineer" placeholder read like
  // a bug to first-time users).
  const heroJobLine = useMemo(() => {
    if (analysisState?.job_description.title) {
      return analysisState.job_description.title;
    }
    if (activeJob?.title) {
      return `${activeJob.company} · ${activeJob.title}`;
    }
    if (jobFileState?.job_description?.title) {
      return jobFileState.job_description.title;
    }
    return "No role loaded yet";
  }, [activeJob, analysisState, jobFileState]);

  // When a profile exists but the parser couldn't extract a name
  // (common with the assistant builder when the user's basics answer
  // didn't include a name in an obvious form), don't fall back all
  // the way to "Resume not uploaded" — that reads like nothing
  // happened. Use the profile's role + first experience entry as a
  // fallback identifier.
  const heroResumeLine = (() => {
    if (!currentProfile) return "Resume not uploaded";
    if (currentProfile.full_name?.trim()) return currentProfile.full_name;
    const firstRole = currentProfile.experience?.[0]?.title;
    if (firstRole) return `${firstRole} (name pending)`;
    return "Profile loaded (name pending)";
  })();

  const accountMenuRef = useRef<HTMLDivElement | null>(null);
  const accountTriggerRef = useRef<HTMLButtonElement | null>(null);
  const accountPopoverRef = useRef<HTMLDivElement | null>(null);
  // Accessible popover (M14): Escape-to-close, a Tab focus trap, and focus
  // restored to the trigger on close. Previously closing left focus on
  // <body>. Treated as a labelled disclosure (the role="menu" + missing
  // menuitem/arrow-roving semantics were dropped in the render below).
  useAccessibleDialog({
    open: accountMenuOpen,
    onClose: () => setAccountMenuOpen(false),
    containerRef: accountPopoverRef,
    restoreFocusRef: accountTriggerRef,
  });
  const accountDisplayName =
    authSession?.app_user.display_name ||
    authSession?.app_user.email ||
    "Signed in";
  const accountInitial = accountDisplayName.slice(0, 1).toUpperCase();

  // Tie the PostHog session to the Supabase user id as soon as the
  // workspace session resolves. ``identify`` is dedupe-safe inside
  // posthog-js so re-firing on every re-render is harmless. Passing
  // null on logout explicitly resets the SDK so subsequent anonymous
  // events don't inherit the prior user's distinct_id.
  const sessionUserId = authSession?.app_user.id ?? null;
  const sessionUserEmail = authSession?.app_user.email ?? null;
  const sessionUserDisplayName = authSession?.app_user.display_name ?? null;
  const sessionUserTier = authSession?.app_user.plan_tier ?? null;
  useEffect(() => {
    identifyPostHogUser(sessionUserId, {
      email: sessionUserEmail ?? undefined,
      display_name: sessionUserDisplayName ?? undefined,
    });
  }, [sessionUserId, sessionUserEmail, sessionUserDisplayName]);
  useEffect(() => {
    setPostHogTierGroup(sessionUserTier);
  }, [sessionUserTier]);

  // ── Effects (preserved verbatim from previous shell) ────────────
  useEffect(() => {
    if (
      resumeIntakeMode !== "assistant" ||
      resumeBuilderSession ||
      resumeBuilderLoading ||
      resumeBuilderInitialized
    ) {
      return;
    }

    void handleLoadOrStartResumeBuilder();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- handleLoadOrStartResumeBuilder is intentionally re-resolved per call. The gate above + these state deps fully describes when this effect should fire; adding the function would make the effect re-run on every render.
  }, [
    authStatus,
    resumeBuilderInitialized,
    resumeBuilderLoading,
    resumeBuilderSession,
    resumeIntakeMode,
  ]);

  useEffect(() => {
    if (
      authStatus === "signed_in" &&
      resumeIntakeMode === "assistant" &&
      !resumeBuilderSession
    ) {
      setResumeBuilderInitialized(false);
    }
  }, [authStatus, resumeBuilderSession, resumeIntakeMode]);

  useEffect(() => {
    if (!resumeBuilderSession) return;

    setResumeBuilderDraftForm({
      full_name: resumeBuilderSession.draft_profile.full_name || "",
      location: resumeBuilderSession.draft_profile.location || "",
      contact_lines: resumeBuilderSession.draft_profile.contact_lines.join("\n"),
      target_role: resumeBuilderSession.draft_profile.target_role || "",
      professional_summary:
        resumeBuilderSession.draft_profile.professional_summary || "",
      experience_notes:
        resumeBuilderSession.draft_profile.experience_notes || "",
      education_notes: resumeBuilderSession.draft_profile.education_notes || "",
      skills: resumeBuilderSession.draft_profile.skills.join(", "),
      certifications:
        resumeBuilderSession.draft_profile.certifications.join(", "),
      // Optional fields default to empty string when the backend
      // omits them — keeps backwards compatibility with sessions
      // saved before these slots existed.
      projects_notes:
        resumeBuilderSession.draft_profile.projects_notes || "",
      publications: (
        resumeBuilderSession.draft_profile.publications || []
      ).join("\n"),
    });
  }, [resumeBuilderSession]);

  // Live themed preview of the builder's generated base resume.
  // Re-fetches whenever a resume exists and the picked theme changes;
  // LLM-free + signature-cached server-side, so a theme switch only
  // re-renders (no token cost) and is cheap to refetch eagerly. The
  // `cancelled` guard drops a stale theme's slow response so rapid
  // switching always settles on the latest pick. Cleared when there's
  // no generated resume — pre-generate, after a reset, or after a
  // draft-save that invalidated the prior render (Q3).
  useEffect(() => {
    const sessionId = resumeBuilderSession?.session_id;
    const generatedMarkdown =
      resumeBuilderSession?.generated_resume_markdown ?? "";
    if (!sessionId || !generatedMarkdown) {
      setResumeBuilderPreviewHtml(null);
      setResumeBuilderPreviewLoading(false);
      return;
    }
    let cancelled = false;
    setResumeBuilderPreviewLoading(true);
    void previewResumeBuilderArtifact(sessionId, resumeBuilderExportTheme)
      .then((response) => {
        if (!cancelled) setResumeBuilderPreviewHtml(response.html);
      })
      .catch(() => {
        // Preview is non-critical chrome — the plain-text markdown
        // fallback and the download buttons still work. Drop to null
        // rather than surfacing an alarming notice.
        if (!cancelled) setResumeBuilderPreviewHtml(null);
      })
      .finally(() => {
        if (!cancelled) setResumeBuilderPreviewLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [
    resumeBuilderSession?.session_id,
    resumeBuilderSession?.generated_resume_markdown,
    resumeBuilderExportTheme,
  ]);

  // ⌘K / Ctrl+K toggles the command palette globally. Escape-to-close is
  // owned by useAccessibleDialog inside CommandPalette (A11Y-1), so it is
  // intentionally not handled here — one Escape owner, no double-close.
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((current) => !current);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  // The assistant is no longer gated on having run an analysis. Users
  // can ask product-help questions ("how do I use this?", "where do I
  // upload my resume?") before they have any workspace at all — the
  // backend's AssistantService.answer_product_help path handles these
  // when the workspace snapshot is null. We still pass a
  // `hasWorkspaceContext` boolean down so the panel can adapt its
  // empty-state and header copy (grounded vs general).
  const hasWorkspaceContext = Boolean(analysisState);
  const assistantCanSubmit =
    !assistantSending && Boolean(assistantQuestion.trim());

  // ── Handlers ────────────────────────────────────────────────────

  // Core search runner — offset 0, REPLACE results. Shared by the
  // explicit Search submit and the auto-apply-on-filter-change effect.
  // Filters/sort are read from live state; query + location are passed
  // in so the effect can re-run the *executed* query (not whatever is
  // half-typed in the box) while the form handler passes the box value.
  async function runSearch(queryText: string, locationText: string) {
    const trimmedQuery = queryText.trim();
    if (!trimmedQuery) {
      return;
    }

    const seq = ++searchSeqRef.current;
    setSearching(true);

    try {
      const response = await searchJobs({
        query: trimmedQuery,
        location: locationText.trim(),
        // Empty source_filters = "any provider" — let the cache RPC
        // search across everything we've indexed. The user's explicit
        // picks (if any) narrow it to that set.
        source_filters: sourceFilters,
        // remote_only kept as a derived signal for back-compat with the
        // cache RPC's existing flag — it composes additively with the
        // dropdown's `remote` pick (either route returns the same rows).
        remote_only: workModes.length === 1 && workModes[0] === "remote",
        posted_within_days: postedWithinDays ? Number(postedWithinDays) : null,
        // Short initial page; "Load more" (handleLoadMore) pulls the
        // next SEARCH_PAGE_SIZE window and appends instead of replacing.
        page_size: SEARCH_PAGE_SIZE,
        offset: 0,
        work_modes: workModes,
        employment_types: employmentTypes,
        sort_by: sortBy,
      });
      // A newer search superseded this one mid-flight — drop the stale
      // response so it can't clobber fresher results.
      if (searchSeqRef.current !== seq) {
        return;
      }
      setSearchResults(response);
      setSearchNotice({
        level: response.results.length ? "success" : "info",
        message: response.results.length
          ? `Found ${response.results.length} matching jobs for the current search.`
          : "No roles matched this search yet.",
      });
    } catch (error) {
      if (searchSeqRef.current !== seq) {
        return;
      }
      setSearchNotice({
        level: "warning",
        message: humanizeApiError(
          error,
          "Something went wrong while searching for roles.",
        ),
      });
    } finally {
      // Only the latest search owns the busy flag — a superseded one
      // clearing it would hide the spinner while the live one runs.
      if (searchSeqRef.current === seq) {
        setSearching(false);
      }
    }
  }

  async function handleSearch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMainTab("jobs");

    if (!searchQuery.trim()) {
      setSearchNotice({
        level: "warning",
        message: "Enter a search query to look for roles.",
      });
      return;
    }

    setSearchNotice({
      level: "info",
      message: "Searching live job sources...",
    });
    await runSearch(searchQuery, searchLocation);
  }

  // Auto-apply filters / sort / posted-within — the job-board pattern
  // where changing a dropdown re-runs the search instead of needing a
  // second Search click. Only fires once a search is already on screen
  // (nothing to filter before the first search); re-runs the EXECUTED
  // query (searchResults.query) with the new filter state, debounced so
  // a burst of multi-select toggles collapses into one request.
  useEffect(() => {
    if (!searchResults) {
      return;
    }
    const executedQuery = searchResults.query.query;
    const executedLocation = searchResults.query.location ?? "";
    const handle = window.setTimeout(() => {
      setSearchNotice({ level: "info", message: "Updating results…" });
      void runSearch(executedQuery, executedLocation);
    }, FILTER_APPLY_DEBOUNCE_MS);
    return () => window.clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentionally keyed ONLY on the filter/sort inputs. Depending on searchResults would loop (runSearch sets it) and depending on runSearch would re-fire every render; the executed query is read fresh from the searchResults closure at fire time, which is correct since a filter change shouldn't change which query is active.
  }, [sourceFilters, workModes, employmentTypes, sortBy, postedWithinDays]);

  // "Load more" — paginate the *current* result set. Reuses the query
  // the backend echoed back (searchResults.query) rather than the live
  // form state, so editing the search box after a search doesn't make
  // the next page paginate a different query. Offset = how many rows
  // we already hold; the backend windows [offset, offset+page_size).
  // Results are appended (deduped by id, defensive against corpus
  // shifts between requests) instead of replacing.
  async function handleLoadMore() {
    if (
      !searchResults ||
      !searchResults.has_more ||
      loadingMore ||
      searching
    ) {
      return;
    }

    const nextOffset = searchResults.results.length;
    // Capture (don't bump) the current search token: this page belongs
    // to the search that's on screen now. If a filter/sort change fires
    // runSearch while this is in flight, that bumps the token and the
    // guard below drops this page — appending old-filter rows onto the
    // new filtered set would be wrong.
    const seq = searchSeqRef.current;
    setLoadingMore(true);
    try {
      const response = await searchJobs({
        ...searchResults.query,
        offset: nextOffset,
      });
      if (searchSeqRef.current !== seq) {
        return;
      }
      setSearchResults((prev) => {
        if (!prev) {
          return response;
        }
        const seen = new Set(prev.results.map((job) => job.id));
        const appended = response.results.filter(
          (job) => !seen.has(job.id),
        );
        const mergedResults = [...prev.results, ...appended];
        return {
          ...response,
          // Preserve the original echoed query (its offset is 0; the
          // freshest page's query carries the bumped offset which we
          // don't want surfaced as the "current search").
          query: prev.query,
          results: mergedResults,
          // Page total_results is per-page on the backend; show the
          // running count of what's actually on screen instead.
          total_results: mergedResults.length,
        };
      });
      setSearchNotice({
        level: "success",
        message: response.results.length
          ? `Loaded ${response.results.length} more — showing ${
              nextOffset + response.results.length
            }.`
          : "No more roles to load for this search.",
      });
    } catch (error) {
      // Don't surface a stale "load more failed" if a newer filtered
      // search already took over.
      if (searchSeqRef.current === seq) {
        setSearchNotice({
          level: "warning",
          message: humanizeApiError(
            error,
            "Something went wrong while loading more roles.",
          ),
        });
      }
    } finally {
      setLoadingMore(false);
    }
  }

  async function handleResolveJob(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!jobUrl.trim()) {
      setWorkspaceNotice({
        level: "warning",
        message: "Paste a supported Greenhouse or Lever job URL to import it.",
      });
      return;
    }

    setImporting(true);
    setWorkspaceNotice({
      level: "info",
      message:
        "Checking that job posting and loading it into your workspace...",
    });

    try {
      const response: JobResolveResponse = await resolveJobUrl(jobUrl.trim());
      if (response.status !== "ok" || !response.job_posting) {
        throw new Error(
          response.error_message ||
            "That URL could not be turned into a supported job posting.",
        );
      }
      setActiveJob(response.job_posting);
      setMainTab("jd");
      setWorkspaceNotice({
        level: "success",
        message: `Imported ${response.job_posting.title} and loaded it into the workspace review lane.`,
      });
    } catch (error) {
      setWorkspaceNotice({
        level: "warning",
        message: humanizeApiError(
          error,
          "The job URL import failed unexpectedly.",
        ),
      });
    } finally {
      setImporting(false);
    }
  }

  function handleLoadSavedJob(job: JobPosting) {
    setActiveJob(job);
    setMainTab("jd");
    setWorkspaceNotice({
      level: "success",
      message: `Loaded ${job.title} from your shortlist into the workspace review lane.`,
    });
  }

  async function handleResumeUpload(file: File | null = selectedResumeFile) {
    if (!file) {
      setResumeNotice({
        level: "warning",
        message: "Choose a PDF, DOCX, or TXT resume before uploading.",
      });
      return;
    }

    setResumeUploading(true);
    setResumeNotice({
      level: "info",
      message: `Parsing ${file.name} through the workspace API...`,
    });

    try {
      const response = await uploadResumeFile(file);
      setResumeState(response);
      setResumeIntakeMode("upload");
      if (response.service_notice?.unavailable) {
        // Parse silently fell back to the basic parser because OpenAI
        // was down — say so (outage is the headline) instead of a
        // false "ready" success, so the user can re-upload once it
        // clears rather than trusting a quietly worse extraction.
        setResumeNotice({
          level: "warning",
          message: response.service_notice.message,
        });
      } else {
        setResumeNotice({
          level: "success",
          message: `${response.candidate_profile.full_name || response.resume_document.filetype} is ready in the workspace.`,
        });
      }
      setSelectedResumeFile(null);
    } catch (error) {
      setResumeNotice({
        level: "warning",
        message: humanizeApiError(error, "Resume upload failed unexpectedly."),
      });
    } finally {
      setResumeUploading(false);
    }
  }

  async function handleJobDescriptionUpload(
    file: File | null = selectedJobFile,
  ) {
    if (!file) {
      setJobFileNotice({
        level: "warning",
        message: "Choose a PDF, DOCX, or TXT job description before uploading.",
      });
      return;
    }

    setJobFileUploading(true);
    setJobFileNotice({
      level: "info",
      message: `Parsing ${file.name} through the workspace API...`,
    });

    try {
      const response = await uploadJobDescriptionFile(file);
      // Discrete file upload — auto-collapse the input on success (M24).
      jobFileSourceRef.current = "discrete";
      setJobFileState(response);
      setManualJobText(response.job_description_text);
      setActiveJob(null);
      setMainTab("jd");
      setJobFileNotice({
        level: "success",
        message: `${response.job_description.title} is now loaded into the manual JD lane.`,
      });
      setSelectedJobFile(null);
    } catch (error) {
      setJobFileNotice({
        level: "warning",
        message: humanizeApiError(
          error,
          "Job-description upload failed unexpectedly.",
        ),
      });
    } finally {
      setJobFileUploading(false);
    }
  }

  function handleClearUploadedResumeProfile() {
    setResumeState(null);
    setSelectedResumeFile(null);
    setResumeNotice(null);
    setResumeBuilderNotice({
      level: "info",
      message:
        "Uploaded resume cleared. You can build a fresh base resume with the assistant now.",
    });
  }

  function handleClearLoadedJobDescription() {
    setActiveJob(null);
    setJobFileState(null);
    setSelectedJobFile(null);
    setManualJobText("");
    // Reset the auto-parse cache and cancel any pending/in-flight parse so
    // a clear-then-repaste of the SAME text re-fires the LLM parse instead
    // of being short-circuited by the unchanged-text guard (M9). Without
    // this, lastParsedTextRef still holds the prior text and an identical
    // repaste silently falls back to the inferior regex read.
    lastParsedTextRef.current = "";
    if (parseDebounceRef.current !== null) {
      window.clearTimeout(parseDebounceRef.current);
      parseDebounceRef.current = null;
    }
    if (parseAbortRef.current) {
      parseAbortRef.current.abort();
      parseAbortRef.current = null;
    }
    setJobFileNotice({
      level: "info",
      message:
        "Job description cleared. You can upload a new file, paste a JD, or load another role.",
    });
    setJobInputCollapsed(false);
  }

  function applySavedWorkspaceSnapshot(response: LoadSavedWorkspaceResponse) {
    const snapshot = response.workspace_snapshot;
    if (!snapshot) return;

    // Résumé-only snapshot: a parsed résumé persisted BEFORE any
    // analysis ran (see the résumé-autosave effect). A real analysis
    // snapshot always carries a job_description with raw_text; a
    // résumé-only one has job_description:{}. Restore JUST the résumé
    // and bail — calling setAnalysisState(snapshot) here would light
    // up an empty/broken "analysis" view, and snapshot.job_description
    // has no raw_text to read.
    const jd = snapshot.job_description as { raw_text?: string } | undefined;
    if (!jd || !jd.raw_text) {
      setResumeState({
        resume_document: snapshot.resume_document,
        candidate_profile: snapshot.candidate_profile,
      });
      setSelectedResumeFile(null);
      setResumeIntakeMode("upload");
      setMainTab("resume");
      return;
    }

    setResumeState({
      resume_document: snapshot.resume_document,
      candidate_profile: snapshot.candidate_profile,
    });
    // Discrete snapshot restore — collapse the input as for any discrete load (M24).
    jobFileSourceRef.current = "discrete";
    setJobFileState({
      job_description_text: snapshot.job_description.raw_text,
      job_description: snapshot.job_description,
      jd_summary_view: snapshot.jd_summary_view,
    });
    setAnalysisState(snapshot);
    setActiveJob(snapshot.imported_job_posting ?? null);
    setManualJobText(snapshot.job_description.raw_text);
    setSelectedResumeFile(null);
    setSelectedJobFile(null);
    setArtifactTab("resume");
    resetArtifacts();
    setAssistantTurns([]);
    setResumeIntakeMode("upload");
    setResumeBuilderSession(null);
    setResumeBuilderInitialized(false);
    setResumeBuilderChatLog([]);
    setResumeBuilderAnswer("");
    setResumeBuilderNotice(null);
    setMainTab("analysis");
  }

  async function handleStartResumeBuilder() {
    setResumeBuilderLoading(true);
    setResumeBuilderNotice({
      level: "info",
      message: "Starting the guided resume builder...",
    });

    try {
      const response = await startResumeBuilderSession();
      setResumeBuilderSession(response);
      setResumeBuilderInitialized(true);
      setResumeBuilderChatLog(
        response.assistant_message
          ? [{ role: "assistant", content: response.assistant_message }]
          : [],
      );
      setResumeBuilderNotice({
        level: "success",
        message:
          "The guided resume builder is ready. Answer each prompt and we will build your base resume together.",
      });
    } catch (error) {
      setResumeBuilderNotice({
        level: "warning",
        message: humanizeApiError(
          error,
          "The guided resume builder could not be started.",
        ),
      });
    } finally {
      setResumeBuilderLoading(false);
    }
  }

  async function handleLoadOrStartResumeBuilder() {
    const isSignedIn = authStatus === "signed_in";
    setResumeBuilderLoading(true);
    setResumeBuilderNotice({
      level: "info",
      message: isSignedIn
        ? "Checking for your latest resume-builder draft..."
        : "Starting the guided resume builder...",
    });

    try {
      if (isSignedIn) {
        try {
          const latest = await loadLatestResumeBuilderSession();
          if (latest.session) {
            setResumeBuilderSession(latest.session);
            // Restoring a saved session: we don't have the full prior
            // conversation locally, so the chat log starts with just
            // the latest assistant turn. The user can continue
            // chatting and the rest of the thread will accrue from
            // here.
            setResumeBuilderChatLog(
              latest.session.assistant_message
                ? [
                    {
                      role: "assistant",
                      content: latest.session.assistant_message,
                    },
                  ]
                : [],
            );
            setResumeBuilderNotice({
              level: "success",
              message: "Your latest resume-builder draft is ready to continue.",
            });
            return;
          }
        } catch (error) {
          const message =
            error instanceof Error ? error.message.toLowerCase() : "";
          if (!message.includes("not found")) {
            throw error;
          }
        }
      }

      const response = await startResumeBuilderSession();
      setResumeBuilderSession(response);
      setResumeBuilderChatLog(
        response.assistant_message
          ? [{ role: "assistant", content: response.assistant_message }]
          : [],
      );
      setResumeBuilderNotice({
        level: "success",
        message:
          "The guided resume builder is ready. Answer each prompt and we will build your base resume together.",
      });
    } catch (error) {
      setResumeBuilderNotice({
        level: "warning",
        message: humanizeApiError(
          error,
          "The guided resume builder could not be started.",
        ),
      });
    } finally {
      setResumeBuilderInitialized(true);
      setResumeBuilderLoading(false);
    }
  }

  async function handleResumeBuilderAnswer(overrideText?: string) {
    if (!resumeBuilderSession) {
      await handleStartResumeBuilder();
      return;
    }

    // Slice 1B: the proactive_offer chip submits the offer text
    // directly, bypassing the textarea state — this is the
    // override path. Plain Continue clicks use the textarea state.
    const rawText = overrideText ?? resumeBuilderAnswer;
    if (!rawText.trim()) {
      setResumeBuilderNotice({
        level: "warning",
        message: "Add an answer before continuing.",
      });
      return;
    }

    setResumeBuilderLoading(true);
    setResumeBuilderNotice({
      level: "info",
      message: "Saving your answer and moving to the next step...",
    });

    const userMessage = rawText.trim();
    try {
      const response = await sendResumeBuilderMessage(
        resumeBuilderSession.session_id,
        userMessage,
      );
      setResumeBuilderSession(response);
      setResumeBuilderAnswer("");
      // Append the user's message + the assistant's reply to the
      // chat log so the conversation reads as a real thread instead
      // of a 1-line "current prompt".
      setResumeBuilderChatLog((prior) => [
        ...prior,
        { role: "user", content: userMessage },
        ...(response.assistant_message
          ? [
              {
                role: "assistant" as const,
                content: response.assistant_message,
              },
            ]
          : []),
      ]);
      // The next step's `assistant_message` already renders as the
      // intake-card body copy. Showing it again as a success notice
      // duplicated the same sentence twice on every screen — clear
      // the transient notice instead.
      setResumeBuilderNotice(null);
    } catch (error) {
      setResumeBuilderNotice({
        level: "warning",
        message: humanizeApiError(error, "That answer could not be saved."),
      });
    } finally {
      setResumeBuilderLoading(false);
    }
  }

  async function handleResumeBuilderGenerate() {
    if (!resumeBuilderSession) {
      setResumeBuilderNotice({
        level: "warning",
        message:
          "Start the guided resume builder before generating a base resume.",
      });
      return;
    }

    setResumeBuilderGenerating(true);
    setResumeBuilderNotice({
      level: "info",
      message: "Generating your baseline resume draft...",
    });

    try {
      const response = await generateResumeBuilderResume(
        resumeBuilderSession.session_id,
      );
      setResumeBuilderSession(response);
      setResumeBuilderNotice({
        level: "success",
        message:
          "Your base resume draft is ready. Review it, then use this profile to continue into the workspace.",
      });
    } catch (error) {
      setResumeBuilderNotice({
        level: "warning",
        message: humanizeApiError(
          error,
          "The base resume draft could not be generated.",
        ),
      });
    } finally {
      setResumeBuilderGenerating(false);
    }
  }

  // "Start over" — clears the current builder session back to the
  // fresh assistant-chat state. The backend reuses the same
  // session_id so no new resume_builder_sessions quota credit is
  // charged (important: Free tier has a lifetime cap of 1).
  async function handleResumeBuilderReset() {
    if (!resumeBuilderSession) return;

    setResumeBuilderLoading(true);
    setResumeBuilderNotice({
      level: "info",
      message: "Clearing your resume draft…",
    });

    try {
      const response = await resetResumeBuilderSession(
        resumeBuilderSession.session_id,
      );
      setResumeBuilderSession(response);
      setResumeBuilderAnswer("");
      setResumeBuilderChatLog(
        response.assistant_message
          ? [{ role: "assistant", content: response.assistant_message }]
          : [],
      );
      setResumeBuilderNotice({
        level: "success",
        message:
          "Cleared — you're back at the start. Chat with the assistant to build a fresh resume.",
      });
    } catch (error) {
      setResumeBuilderNotice({
        level: "warning",
        message: humanizeApiError(
          error,
          "The resume builder could not be cleared.",
        ),
      });
    } finally {
      setResumeBuilderLoading(false);
    }
  }

  async function handleResumeBuilderDraftSave() {
    if (!resumeBuilderSession) return;

    setResumeBuilderEditing(true);
    setResumeBuilderNotice({
      level: "info",
      message: "Saving your edits to the draft profile...",
    });

    try {
      const response = await updateResumeBuilderDraft(
        resumeBuilderSession.session_id,
        {
          full_name: resumeBuilderDraftForm.full_name,
          location: resumeBuilderDraftForm.location,
          contact_lines: resumeBuilderDraftForm.contact_lines
            .split("\n")
            .map((item) => item.trim())
            .filter(Boolean),
          target_role: resumeBuilderDraftForm.target_role,
          professional_summary: resumeBuilderDraftForm.professional_summary,
          experience_notes: resumeBuilderDraftForm.experience_notes,
          education_notes: resumeBuilderDraftForm.education_notes,
          skills: resumeBuilderDraftForm.skills
            .split(",")
            .map((item) => item.trim())
            .filter(Boolean),
          certifications: resumeBuilderDraftForm.certifications
            .split(",")
            .map((item) => item.trim())
            .filter(Boolean),
          // Optional fields — same shape contract as their required
          // siblings (string for prose, list[string] for citations).
          projects_notes: resumeBuilderDraftForm.projects_notes,
          publications: resumeBuilderDraftForm.publications
            .split("\n")
            .map((item) => item.trim())
            .filter(Boolean),
        },
      );
      setResumeBuilderSession(response);
      setResumeBuilderNotice({
        level: "success",
        message:
          "Draft updated. You can keep refining it or generate the base resume.",
      });
    } catch (error) {
      setResumeBuilderNotice({
        level: "warning",
        message: humanizeApiError(error, "Those draft edits could not be saved."),
      });
    } finally {
      setResumeBuilderEditing(false);
    }
  }

  async function handleResumeBuilderCommit() {
    if (!resumeBuilderSession) {
      setResumeBuilderNotice({
        level: "warning",
        message: "Generate a base resume before using it in the workspace.",
      });
      return;
    }

    setResumeBuilderCommitting(true);
    setResumeBuilderNotice({
      level: "info",
      message: "Moving this base resume into your workspace profile...",
    });

    try {
      const response = await commitResumeBuilderResume(
        resumeBuilderSession.session_id,
      );
      setResumeState({
        resume_document: response.resume_document,
        candidate_profile: response.candidate_profile,
      });
      setResumeNotice({
        level: "success",
        message: `${response.candidate_profile.full_name || "Your new resume"} is ready in the workspace.`,
      });
      setResumeBuilderNotice({
        level: "success",
        message:
          "Your base resume is now the active profile for the rest of the workflow.",
      });
      setSelectedResumeFile(null);
      setResumeBuilderSession(null);
      setResumeBuilderInitialized(false);
      setResumeBuilderAnswer("");
      // Flip the intake mode back to "upload" so when the user later
      // returns to the Resume tab they see the parsed-profile hero
      // for their newly committed resume — not a fresh assistant
      // session that auto-spins up because mode was still "assistant".
      setResumeIntakeMode("upload");
      setMainTab("jobs");
    } catch (error) {
      setResumeBuilderNotice({
        level: "warning",
        message: humanizeApiError(
          error,
          "This base resume could not be moved into the workspace.",
        ),
      });
    } finally {
      setResumeBuilderCommitting(false);
    }
  }

  async function handleResumeBuilderExport(
    exportFormat: WorkspaceArtifactExportFormat,
  ) {
    if (!resumeBuilderSession) {
      setResumeBuilderNotice({
        level: "warning",
        message:
          "Generate the base resume before downloading it.",
      });
      return;
    }
    if (!resumeBuilderSession.generated_resume_markdown) {
      setResumeBuilderNotice({
        level: "warning",
        message:
          "Generate the base resume first — there's nothing to download yet.",
      });
      return;
    }

    setResumeBuilderExporting(exportFormat);
    setResumeBuilderNotice({
      level: "info",
      message: `Preparing your ${exportFormat.toUpperCase()} download…`,
    });

    try {
      const response = await exportResumeBuilderArtifact({
        session_id: resumeBuilderSession.session_id,
        export_format: exportFormat,
        theme: resumeBuilderExportTheme,
      });
      downloadBase64File(
        response.file_name,
        response.content_base64,
        response.mime_type,
      );
      setResumeBuilderNotice({
        level: "success",
        message: `Downloaded ${response.file_name}.`,
      });
    } catch (error) {
      setResumeBuilderNotice({
        level: "warning",
        message: humanizeApiError(error, "The download could not be prepared."),
      });
    } finally {
      setResumeBuilderExporting(null);
    }
  }

  // Sign-out wraps the hook's auth-only `signOutAuth` with cross-slice
  // resets (saved jobs, resume builder fields) that the hook can't
  // reach into.
  async function handleSignOut() {
    await signOutAuth();
    resetSavedJobs();
    setResumeBuilderSession(null);
    setResumeBuilderInitialized(false);
    setResumeBuilderChatLog([]);
    setResumeBuilderAnswer("");
    setResumeBuilderNotice(null);
    // Defense in depth (M10): also reset the workspace CONTENT slices so
    // the next user on a shared device can never see the previous user's
    // parsed résumé / analysis / JD. Today isolation relies SOLELY on the
    // signed_out redirect being a hard navigation that wipes memory — a
    // single point of failure for a data-isolation property.
    setResumeState(null);
    setAnalysisState(null);
    setActiveJob(null);
    setManualJobText("");
    setJobFileState(null);
    setJobFileNotice(null);
    setAssistantTurns([]);
    useAssistantStreamingStore.getState().setStreamingTurn(null);
    resetArtifacts();
    resetAnalysis();
    setMainTab("resume");
  }

  // Open the Lemon Squeezy customer portal for the signed-in user.
  // The backend mints a one-time signed URL (the LS customer
  // resource's urls.customer_portal field) and returns it; we
  // window.location.assign so the back button still works.
  //
  // The button rendering this is gated on quota.tier !== "free", so
  // a 404 (no subscription record) shouldn't normally happen. We
  // still surface a notice for the 503 (LS not configured), 401
  // (session expired), and any other path defensively.
  const [managingSubscription, setManagingSubscription] = useState(false);
  async function handleManageSubscription() {
    if (managingSubscription) return;
    setManagingSubscription(true);
    try {
      const result = await getCustomerPortalUrl();
      // Validate the backend-returned portal URL before navigating (M7).
      if (result.url && isAllowedRedirect(result.url)) {
        window.location.assign(result.url);
        return;
      }
      setWorkspaceNotice({
        level: "warning",
        message: "Could not load the subscription portal. Please try again.",
      });
    } catch (error) {
      setWorkspaceNotice({
        level: "warning",
        message: humanizeApiError(
          error,
          "Could not open the subscription portal.",
        ),
      });
    } finally {
      setManagingSubscription(false);
    }
  }

  // Reload-saved-workspace wraps the hook's `reloadSavedWorkspace` to
  // apply the returned snapshot across the shell's other slices and
  // surface the success notice.
  async function handleReloadSavedWorkspace() {
    const result = await reloadSavedWorkspace();
    if (result.kind !== "snapshot") return;
    applySavedWorkspaceSnapshot(result.response);
    setWorkspaceNotice({
      level: "success",
      message: `Saved workspace reloaded. Expires ${formatUtcTimestamp(result.response.saved_workspace?.expires_at ?? "")} UTC.`,
    });
  }

  async function submitAssistantQuestion(questionText: string) {
    const normalizedQuestion = questionText.trim();

    if (!normalizedQuestion) {
      setWorkspaceNotice({
        level: "warning",
        message: "Ask a question before sending it to the assistant.",
      });
      return;
    }

    // Note: previously this also hard-returned when `analysisState` was
    // null with a "Run the AI analysis first…" notice. The gate was
    // lifted so users can ask product-help questions before they have
    // any workspace at all — the backend's
    // AssistantService.answer_product_help path handles a null
    // workspace_snapshot gracefully.

    // Abort any previous stream still in flight before starting a new one —
    // double-submits should never produce overlapping streamingTurn updates.
    assistantStreamAbortRef.current?.abort();
    const abortController = new AbortController();
    assistantStreamAbortRef.current = abortController;

    // Non-reactive store setters: writing through getState() means these
    // per-token updates re-render ONLY AssistantPanel (which subscribes),
    // never the shell tree (PERF-1).
    const { setStreamingTurn, updateStreamingTurn } =
      useAssistantStreamingStore.getState();

    setAssistantSending(true);
    setStreamingTurn({
      question: normalizedQuestion,
      partialAnswer: "",
      sources: [],
      isStreaming: true,
      error: null,
    });

    let accumulatedAnswer = "";
    let collectedSources: string[] = [];
    let streamErrorDetail: string | null = null;

    try {
      // Compact state projection — gives the LLM enough to answer
      // pre-analysis questions ("what should I do next?", "is my
      // resume parsed?") without sending the full resume_text or JD
      // body on every turn. The full `workspace_snapshot` still rides
      // separately when an analysis has run.
      const workspaceStateContext = {
        current_step: mainTab,
        has_resume: Boolean(currentProfile),
        resume_summary: currentProfile
          ? {
              name: currentProfile.full_name || "",
              location: currentProfile.location || "",
              skills_count: currentProfile.skills?.length ?? 0,
              // Count of *entries* (jobs held), not years.
              experience_entries_count:
                currentProfile.experience?.length ?? 0,
              has_certifications:
                (currentProfile.certifications?.length ?? 0) > 0,
            }
          : null,
        has_jd: Boolean(review),
        // Title + location come from the JobPosting metadata (when
        // the user picked a job from search). Skill counts come from
        // the JobReview's parsed-text breakdown. They live on
        // different objects on purpose: review.{hardSkills,softSkills,
        // mustHaves} is the local heuristic parse of the JD body,
        // whereas activeJob.{title,location} is the structured
        // metadata from the ATS source. activeJob is null on a
        // manually-pasted JD, in which case title/location simply
        // come up empty — the LLM still gets the skill counts.
        jd_summary: review
          ? {
              title: activeJob?.title ?? "",
              location: activeJob?.location ?? null,
              hard_skills_count: review.hardSkills?.length ?? 0,
              soft_skills_count: review.softSkills?.length ?? 0,
              must_haves_count: review.mustHaves?.length ?? 0,
            }
          : null,
        has_analysis: Boolean(analysisState),
        saved_jobs_count: savedJobs?.length ?? 0,
        last_search_query: searchQuery.trim() ? searchQuery.trim() : null,
      };

      await streamWorkspaceAssistantAnswer(
        {
          question: normalizedQuestion,
          current_page: "Workspace",
          workspace_state: workspaceStateContext,
          workspace_snapshot: analysisState,
          history: buildAssistantHistoryPayload(assistantTurns),
        },
        (event) => {
          switch (event.type) {
            case "meta":
              collectedSources = event.sources;
              updateStreamingTurn((current) => ({
                ...current,
                sources: event.sources,
              }));
              break;
            case "delta":
              accumulatedAnswer += event.text;
              updateStreamingTurn((current) => ({
                ...current,
                partialAnswer: accumulatedAnswer,
              }));
              break;
            case "error":
              streamErrorDetail = event.detail;
              break;
            case "done":
              break;
          }
        },
        abortController.signal,
      );

      if (streamErrorDetail) {
        updateStreamingTurn((current) => ({
          ...current,
          isStreaming: false,
          error: streamErrorDetail,
        }));
        setWorkspaceNotice({
          level: "warning",
          message: streamErrorDetail,
        });
        return;
      }

      setAssistantTurns((current) => [
        ...current,
        {
          question: normalizedQuestion,
          response: {
            answer: accumulatedAnswer,
            sources: collectedSources,
            suggested_follow_ups: [],
          },
        },
      ]);
      setStreamingTurn(null);
      setAssistantQuestion("");
    } catch (error) {
      const isAbort =
        error instanceof DOMException && error.name === "AbortError";
      if (isAbort) {
        setStreamingTurn(null);
        return;
      }
      const message = humanizeApiError(
        error,
        "Assistant request failed unexpectedly.",
      );
      setWorkspaceNotice({ level: "warning", message });
      updateStreamingTurn((current) => ({
        ...current,
        isStreaming: false,
        error: message,
      }));
    } finally {
      setAssistantSending(false);
      if (assistantStreamAbortRef.current === abortController) {
        assistantStreamAbortRef.current = null;
      }
    }
  }

  async function handleAssistantSubmit(
    event: React.FormEvent<HTMLFormElement>,
  ) {
    event.preventDefault();
    await submitAssistantQuestion(assistantQuestion);
  }

  function handleClearAssistantConversation() {
    assistantStreamAbortRef.current?.abort();
    assistantStreamAbortRef.current = null;
    useAssistantStreamingStore.getState().setStreamingTurn(null);
    setAssistantTurns([]);
    setAssistantQuestion("");
    setWorkspaceNotice({
      level: "info",
      message: analysisState
        ? `Cleared the assistant thread for ${analysisState.job_description.title || "the current workspace"}.`
        : "Cleared the assistant thread.",
    });
  }

  function clearWorkspaceRole() {
    setActiveJob(null);
    setJobFileState(null);
    setManualJobText("");
    setAnalysisState(null);
    resetAnalysis();
    resetArtifacts();
    setWorkspaceNotice({
      level: "info",
      message:
        "Cleared the active role context. Load another role or paste a new JD.",
    });
  }

  // Persist a parsed résumé as soon as it exists — even before any
  // analysis runs — so a tab reload / "Reload saved workspace"
  // restores it (parity with the resume-builder, which already
  // autosaves every turn). Deliberately calls saveWorkspaceSnapshot
  // DIRECTLY, NOT persistLatestWorkspace: the latter sets
  // workspaceSaveMeta, which would gate-block the post-analysis
  // autosave effect below. This effect never touches workspaceSaveMeta,
  // so the analysis path is wholly unaffected; the single-row upsert
  // means a later analysis save cleanly supersedes this provisional
  // row. Ref-guarded by résumé identity → fires once per distinct
  // parsed résumé, never on every render.
  const resumeAutoSavedRef = useRef<string | null>(null);
  useEffect(() => {
    if (
      authStatus !== "signed_in" ||
      !authSession?.features.saved_workspace_enabled ||
      analysisState ||
      !resumeState?.candidate_profile
    ) {
      return;
    }
    const identity = `${resumeState.candidate_profile.full_name || ""}|${
      resumeState.resume_document?.filetype || ""
    }`;
    if (resumeAutoSavedRef.current === identity) return;
    resumeAutoSavedRef.current = identity;
    // Minimal snapshot: real résumé sections + the other
    // _validate_workspace_snapshot-required keys as {} (empty dicts
    // pass its isinstance(dict) check). Cast because this is an
    // intentionally-partial WorkspaceAnalysisResponse; the backend
    // accepts any snapshot dict and only validates the 5 keys.
    const snapshot = {
      resume_document: resumeState.resume_document,
      candidate_profile: resumeState.candidate_profile,
      job_description: {},
      jd_summary_view: {},
      fit_analysis: {},
      tailored_draft: {},
      agent_result: null,
      artifacts: {},
      workflow: {},
    } as unknown as WorkspaceAnalysisResponse;
    void saveWorkspaceSnapshot(snapshot).catch(() => {
      // Best-effort: a failed provisional save must not disrupt the
      // workspace (the résumé is still in client state, and running
      // the analysis will persist the full snapshot anyway). Clear
      // the guard so a later change can retry.
      resumeAutoSavedRef.current = null;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- fires once per distinct parsed résumé while signed-in with no analysis yet; the deps below fully describe that fire condition.
  }, [
    resumeState,
    analysisState,
    authStatus,
    authSession?.features.saved_workspace_enabled,
  ]);

  useEffect(() => {
    if (
      authStatus !== "signed_in" ||
      !authSession?.features.saved_workspace_enabled ||
      !analysisState ||
      workspaceSaveMeta ||
      autoSaving
    ) {
      return;
    }

    void persistLatestWorkspace(analysisState);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- persistLatestWorkspace comes from useWorkspaceSession and is re-bound each render; the gate above + these deps fully describe the fire condition (one save per analysisState transition while save-meta is empty).
  }, [
    analysisState,
    authSession?.features.saved_workspace_enabled,
    authStatus,
    autoSaving,
    workspaceSaveMeta,
  ]);

  // Outside-click closes the account popover. Escape + focus management
  // are owned by useAccessibleDialog above (M14), so they are not
  // duplicated here — one Escape owner, no double-close.
  useEffect(() => {
    if (!accountMenuOpen) return;

    function handlePointerDown(event: MouseEvent) {
      if (!accountMenuRef.current?.contains(event.target as Node)) {
        setAccountMenuOpen(false);
      }
    }

    window.addEventListener("mousedown", handlePointerDown);
    return () => {
      window.removeEventListener("mousedown", handlePointerDown);
    };
  }, [accountMenuOpen]);

  // Recent assistant questions for the command palette.
  const recentAssistantQuestions = useMemo(
    () => assistantTurns.slice(-5).map((turn) => turn.question).reverse(),
    [assistantTurns],
  );

  // ── Auth gate ───────────────────────────────────────────────────
  // The AI workspace requires login (token-meter migration, T5): every
  // LLM operation has to be attributable to a user_id for the weekly
  // token meter, so an anonymous session has nothing to meter and is
  // an un-capped abuse vector. The backend independently 401s every
  // LLM route (defence in depth); this gate is the matching UX, so an
  // anonymous visitor sees one clear sign-in prompt instead of hitting
  // a 401 the moment they try anything. Placed after all hooks above
  // so the early return never changes hook order.
  if (authStatus !== "signed_in") {
    return (
      <div className="b-shell">
        <div className="b-auth-gate">
          {authStatus === "restoring" ? (
            <div className="b-auth-gate-card">
              <p className="b-auth-gate-text">Restoring your session…</p>
            </div>
          ) : (
            <div className="b-auth-gate-card">
              <div className="b-section-label">AI Workspace</div>
              <h1 className="b-auth-gate-title">Sign in to continue</h1>
              <p className="b-auth-gate-text">
                The AI workspace — résumé builder, JD tailoring, and the
                assistant — runs on your account, so your drafts and your
                weekly AI usage stay tied to you. Sign in with Google to
                get started.
              </p>
              <button
                className="rd-btn rd-btn-primary"
                disabled={authActionLoading}
                onClick={() => void handleGoogleSignIn()}
                type="button"
              >
                {authActionLoading
                  ? "Redirecting…"
                  : "Sign in with Google"}
              </button>
            </div>
          )}
        </div>
      </div>
    );
  }

  // ── Render ──────────────────────────────────────────────────────
  return (
    <div className="b-shell">
      <div className="b-topbar">
        <div className="b-brand">
          <span className="b-brand-mark">
            <Image
              alt="Job Application Copilot"
              height={30}
              priority
              src="/brand/job-copilot-logo.png"
              width={30}
            />
          </span>
          <span className="b-brand-name">Job Application Copilot</span>
        </div>

        <div className="b-topbar-actions">
          <button
            aria-label="Open command palette"
            className="b-cmd-trigger"
            onClick={() => setPaletteOpen(true)}
            type="button"
          >
            <span className="b-cmd-trigger-icon">
              <SearchIcon />
            </span>
            <span className="b-cmd-trigger-text">
              Search or run command…
            </span>
            <span className="b-cmd-trigger-keys">
              <span className="b-cmd-key">⌘</span>
              <span className="b-cmd-key">K</span>
            </span>
          </button>

          {authStatus === "signed_in" ? (
            <div
              ref={accountMenuRef}
              style={{ position: "relative", display: "inline-flex" }}
            >
              <button
                ref={accountTriggerRef}
                aria-expanded={accountMenuOpen}
                className="b-account"
                onClick={() => setAccountMenuOpen((open) => !open)}
                type="button"
              >
                <span className="b-account-avatar">{accountInitial}</span>
                <span className="b-account-name">
                  {accountDisplayName.split(" ")[0] || accountDisplayName}
                </span>
                <svg
                  aria-hidden="true"
                  fill="none"
                  height="10"
                  stroke="currentColor"
                  strokeLinecap="round"
                  strokeWidth="1.6"
                  viewBox="0 0 10 10"
                  width="10"
                >
                  <path d="m2.5 4 2.5 2.5L7.5 4" />
                </svg>
              </button>
              {accountMenuOpen ? (
                <div
                  ref={accountPopoverRef}
                  aria-label="Account menu"
                  className="b-account-popover"
                  onClick={(event) => event.stopPropagation()}
                >
                  <div className="b-account-pop-head">
                    <span
                      className="b-account-avatar"
                      style={{ width: 32, height: 32, fontSize: 13 }}
                    >
                      {accountInitial}
                    </span>
                    <div>
                      <div className="b-account-pop-name">
                        {accountDisplayName}
                      </div>
                      <div className="b-account-pop-email">
                        {authSession?.app_user.email || "Account session live"}
                      </div>
                    </div>
                  </div>
                  <dl className="b-account-pop-stats">
                    <div>
                      <dt>Plan</dt>
                      <dd>{formatTier(authSession?.app_user.plan_tier)}</dd>
                    </div>
                    <div>
                      <dt>Runs left</dt>
                      <dd>{formatRemainingCalls(dailyQuota)}</dd>
                    </div>
                    {workspaceSaveMeta ? (
                      <div>
                        <dt>Saved until</dt>
                        <dd>
                          {formatUtcTimestamp(workspaceSaveMeta.expires_at)}{" "}
                          UTC
                        </dd>
                      </div>
                    ) : autoSaving ? (
                      <div>
                        <dt>Status</dt>
                        <dd>Saving latest…</dd>
                      </div>
                    ) : null}
                  </dl>
                  {/* Weekly LLM token meter — the primary AI-usage
                      gate. Rendered from the live /workspace/quota
                      snapshot so it reflects spend the moment a run
                      finishes. */}
                  {workspaceQuota ? (
                    <TokenUsageMeter
                      counter={workspaceQuota.counters.llm_tokens}
                      resetAt={workspaceQuota.llm_tokens_reset_at}
                    />
                  ) : null}
                  {authError ? (
                    <div className="b-notice b-notice-warning">{authError}</div>
                  ) : null}
                  <div className="b-account-pop-actions">
                    {authSession?.features.saved_workspace_enabled ? (
                      <button
                        className="rd-btn rd-btn-primary rd-btn-sm"
                        disabled={authActionLoading || workspaceReloading}
                        onClick={() => void handleReloadSavedWorkspace()}
                        type="button"
                      >
                        {workspaceReloading
                          ? "Reloading…"
                          : "Reload saved workspace"}
                      </button>
                    ) : null}
                    {/* "Manage subscription" surfaces the LS customer
                        portal for paid users. Gated on
                        workspaceQuota.tier !== "free" so Free users
                        don't see a button that would 404 on the
                        backend (no subscription row exists). The
                        loading state mirrors the other rd-btn-sm
                        controls in this popover. */}
                    {workspaceQuota && workspaceQuota.tier !== "free" ? (
                      <button
                        className="rd-btn rd-btn-ghost rd-btn-sm"
                        disabled={managingSubscription || authActionLoading}
                        onClick={() => void handleManageSubscription()}
                        type="button"
                      >
                        {managingSubscription
                          ? "Opening…"
                          : "Manage subscription"}
                      </button>
                    ) : null}
                    <button
                      className="rd-btn rd-btn-ghost rd-btn-sm"
                      disabled={authActionLoading}
                      onClick={() => void handleSignOut()}
                      type="button"
                    >
                      {authActionLoading ? "Signing out…" : "Sign out"}
                    </button>
                  </div>
                </div>
              ) : null}
            </div>
          ) : (
            <button
              className="b-topbar-signin"
              disabled={authActionLoading || authStatus === "restoring"}
              onClick={() => void handleGoogleSignIn()}
              type="button"
            >
              {authStatus === "restoring"
                ? "Restoring…"
                : authActionLoading
                  ? "Redirecting…"
                  : "Sign in with Google"}
            </button>
          )}
        </div>
      </div>

      <div className="b-rail-row">
        {(() => {
          // Connector-line progress: how far the workflow has gotten,
          // 0..1. Counts each done step + a half-credit for the
          // currently-active step so the line visibly reaches the
          // chip the user is on.
          const doneCount = STEP_ORDER.filter(
            (step) => stepDone[step] && step !== mainTab,
          ).length;
          const activeContribution = STEP_ORDER.indexOf(mainTab) >= 0 ? 0.5 : 0;
          const railProgress =
            (doneCount + activeContribution) /
            Math.max(1, STEP_ORDER.length - 1);
          // First ready, not-active, not-done step → next nudge target.
          const nextStep = STEP_ORDER.find(
            (step) => step !== mainTab && stepReady[step] && !stepDone[step],
          );
          // Honest tooltip per step state — locked steps explain WHY.
          // Resume / Job Search / Job Detail are independently
          // accessible (see stepReady above). Only Analysis is gated.
          const lockReason: Record<WorkspaceMainTab, string> = {
            resume: "",
            jobs: "",
            jd: "",
            analysis: "Need a parsed resume + job description first.",
          };
          // When the user clicks a locked rail step we don't want a
          // silent no-op — the UI was confusing as "is this broken?".
          // Compute the first missing prerequisite for each gated step
          // so the click handler can jump them there and surface a
          // helpful notice. Today only Analysis is gated; keeping the
          // shape per-step so future locks plug in the same way.
          const lockedPrereqStep: Record<WorkspaceMainTab, WorkspaceMainTab | null> = {
            resume: null,
            jobs: null,
            jd: null,
            analysis: !resumeText.trim()
              ? "resume"
              : !manualJobText.trim()
                ? "jd"
                : null,
          };
          const lockedPrereqMessage: Record<WorkspaceMainTab, string> = {
            resume: "",
            jobs: "",
            jd: "",
            analysis: !resumeText.trim()
              ? "Upload a résumé in Step 01 to unlock Analysis."
              : !manualJobText.trim()
                ? "Paste a job description in Step 03 to unlock Analysis."
                : "Both inputs are loaded — Analysis is ready to run.",
          };
          return (
            <div
              className="b-rail"
              role="tablist"
              style={
                {
                  ["--b-rail-progress" as string]: Math.min(
                    1,
                    Math.max(0, railProgress),
                  ),
                } as React.CSSProperties
              }
            >
              {STEP_ORDER.map((step) => {
                const meta = STEP_LABELS[step];
                const ready = stepReady[step];
                const done = stepDone[step] && step !== mainTab;
                const active = mainTab === step;
                const isNext = step === nextStep;
                const tooltip = !ready
                  ? lockReason[step]
                  : active
                    ? `${meta.label} · current step`
                    : done
                      ? `${meta.label} · complete · click to revisit`
                      : `${meta.label} · click to open`;
                return (
                  <button
                    aria-disabled={!ready || undefined}
                    aria-label={meta.label}
                    aria-selected={active}
                    className="b-rail-step"
                    data-done={done || undefined}
                    data-locked={!ready || undefined}
                    data-next={isNext || undefined}
                    key={step}
                    onClick={() => {
                      if (ready) {
                        setMainTab(step);
                        return;
                      }
                      // Locked-step click handling: instead of a
                      // silent no-op (the old behavior with `disabled`),
                      // route the user to the missing prerequisite and
                      // surface a helpful inline notice. Falls back to
                      // a plain notice if no specific prereq is known.
                      const prereq = lockedPrereqStep[step];
                      const message = lockedPrereqMessage[step] || lockReason[step];
                      if (message) {
                        setWorkspaceNotice({ level: "warning", message });
                      }
                      if (prereq) {
                        setMainTab(prereq);
                      }
                    }}
                    role="tab"
                    title={tooltip}
                    type="button"
                  >
                    <span className="b-rail-num">
                      {done ? <CheckIcon /> : meta.number}
                    </span>
                    {/* Two label spans, one shown on desktop and one on
                        mobile. `aria-hidden` on both keeps screen
                        readers from seeing the duplication; the
                        button's aria-label is the source of truth. */}
                    <span className="b-rail-label-full" aria-hidden="true">
                      {meta.label}
                    </span>
                    <span className="b-rail-label-short" aria-hidden="true">
                      {meta.shortLabel}
                    </span>
                  </button>
                );
              })}
            </div>
          );
        })()}
      </div>

      <div className="b-hero">
        <div>
          <div className="b-hero-title">{activeTabMeta.title}</div>
          <div className="b-hero-sub">{activeTabMeta.sub}</div>
        </div>
        <div className="b-hero-stats">
          <span className="b-hero-stat">
            <strong>Resume</strong> · {heroResumeLine}
          </span>
          <span className="b-hero-stat">
            <strong>Role</strong> · {heroJobLine}
          </span>
          <span className={`b-hero-stat ${pipToneClass(activeTabMeta.tone)}`}>
            {activeTabMeta.statusLabel}
          </span>
        </div>
      </div>

      <div className="b-canvas">
        {workspaceNotice ? (
          <div className={noticeClassName(workspaceNotice.level)}>
            <span className="b-notice-message">
              {workspaceNotice.message}
            </span>
            {workspaceNotice.action ? (
              <a
                className="b-notice-action"
                href={workspaceNotice.action.href}
                rel="noopener noreferrer"
                target="_blank"
              >
                {workspaceNotice.action.label}
              </a>
            ) : null}
          </div>
        ) : null}

        {mainTab === "resume" ? (
          <ResumeIntake
            authSignedIn={authStatus === "signed_in"}
            builderAnswer={resumeBuilderAnswer}
            builderChatLog={resumeBuilderChatLog}
            builderCollapsed={resumeBuilderCollapsed}
            builderCommitting={resumeBuilderCommitting}
            builderDraftForm={resumeBuilderDraftForm}
            builderEditing={resumeBuilderEditing}
            builderExporting={resumeBuilderExporting}
            builderExportTheme={resumeBuilderExportTheme}
            builderGenerating={resumeBuilderGenerating}
            builderLoading={resumeBuilderLoading}
            builderNotice={resumeBuilderNotice}
            builderPreviewHtml={resumeBuilderPreviewHtml}
            builderPreviewLoading={resumeBuilderPreviewLoading}
            builderSession={resumeBuilderSession}
            currentProfile={currentProfile}
            mode={resumeIntakeMode}
            onBuilderAnswerChange={setResumeBuilderAnswer}
            onBuilderAnswerSubmit={() => void handleResumeBuilderAnswer()}
            onBuilderProactiveOfferAccept={(offer) =>
              void handleResumeBuilderAnswer(offer)
            }
            onBuilderCommit={() => void handleResumeBuilderCommit()}
            onBuilderDraftSave={() => void handleResumeBuilderDraftSave()}
            onBuilderExport={(format) =>
              void handleResumeBuilderExport(format)
            }
            onBuilderExportThemeChange={setResumeBuilderExportTheme}
            onBuilderGenerate={() => void handleResumeBuilderGenerate()}
            onBuilderReset={() => void handleResumeBuilderReset()}
            onBuilderVoiceError={(message) =>
              setResumeBuilderNotice({ level: "warning", message })
            }
            onClearUploadedResumeProfile={handleClearUploadedResumeProfile}
            onModeChange={setResumeIntakeMode}
            onResetBuilderInitialized={() =>
              setResumeBuilderInitialized(false)
            }
            onResumeUpload={(file) => void handleResumeUpload(file)}
            onSelectedResumeFileChange={setSelectedResumeFile}
            onToggleBuilderCollapsed={() =>
              setResumeBuilderCollapsed((current) => !current)
            }
            resumeNotice={resumeNotice}
            resumeState={resumeState}
            resumeUploading={resumeUploading}
            selectedResumeFile={selectedResumeFile}
            setBuilderDraftForm={setResumeBuilderDraftForm}
          />
        ) : null}

        {mainTab === "jobs" ? (
          <JobSearch
            activeJob={activeJob}
            authSignedIn={authStatus === "signed_in"}
            employmentTypes={employmentTypes}
            importing={importing}
            jobUrl={jobUrl}
            latestSavedJobAt={latestSavedJobAt}
            loadingMore={loadingMore}
            onEmploymentTypesChange={setEmploymentTypes}
            onImportSubmit={handleResolveJob}
            onJobUrlChange={setJobUrl}
            onLoadMore={() => void handleLoadMore()}
            onLoadSavedJob={handleLoadSavedJob}
            onPostedWithinDaysChange={setPostedWithinDays}
            onRemoveSavedJob={(job) => void handleRemoveSavedJob(job)}
            onReviewRole={(job) => {
              setActiveJob(job);
              setMainTab("jd");
            }}
            onSaveJob={(job) => void handleSaveJob(job)}
            onSearchLocationChange={setSearchLocation}
            onSearchQueryChange={setSearchQuery}
            onSearchSubmit={handleSearch}
            onSortByChange={setSortBy}
            onSourceFiltersChange={setSourceFilters}
            onWorkModesChange={setWorkModes}
            postedWithinDays={postedWithinDays}
            savedJobActionId={savedJobActionId}
            savedJobIds={savedJobIds}
            savedJobs={savedJobs}
            savedJobsEnabled={savedJobsEnabled}
            savedJobsLoading={savedJobsLoading}
            savedJobsNotice={savedJobsNotice}
            searching={searching}
            searchLocation={searchLocation}
            searchNotice={searchNotice}
            searchQuery={searchQuery}
            searchResults={searchResults}
            sortBy={sortBy}
            sourceFilters={sourceFilters}
            workModes={workModes}
          />
        ) : null}

        {mainTab === "jd" ? (
          <JDReview
            activeJob={activeJob}
            analysisIsStale={analysisIsStale}
            analysisState={analysisState}
            jobFileNotice={jobFileNotice}
            jobFileState={jobFileState}
            jobFileUploading={jobFileUploading}
            jobInputCollapsed={jobInputCollapsed}
            manualJobText={manualJobText}
            onClearLoadedJobDescription={handleClearLoadedJobDescription}
            onJobDescriptionUpload={(file) =>
              void handleJobDescriptionUpload(file)
            }
            onManualJobTextChange={setManualJobText}
            onSelectedJobFileChange={setSelectedJobFile}
            onToggleJobInputCollapsed={() =>
              setJobInputCollapsed((current) => !current)
            }
            review={review}
            selectedJobFile={selectedJobFile}
          />
        ) : null}

        {mainTab === "analysis" ? (
          <>
            <AnalysisRunner
              analysisIsStale={analysisIsStale}
              analysisJobState={analysisJobState}
              analysisLoading={analysisLoading}
              analysisState={analysisState}
              analysisCancelling={analysisCancelling}
              currentWorkflowStage={currentWorkflowStage}
              onCancelAnalysis={() => void handleCancelAnalysis()}
              onClearRole={clearWorkspaceRole}
              onPremiumChange={setPremium}
              onPremiumLockedUpgrade={() =>
                setWorkspaceNotice({
                  level: "info",
                  message:
                    "Premium AI (GPT-5.5) is a Pro feature. Upgrade your plan to run premium tailoring.",
                  action: {
                    label: "Upgrade",
                    href: workspaceQuota?.upgrade_url || "/#pricing",
                  },
                })
              }
              onRunAnalysis={() => void handleRunAnalysis()}
              premium={premium}
              quota={workspaceQuota}
              ready={stepReady.analysis}
            />

            <ArtifactViewer
              activeTheme={
                artifactTab === "resume" ? resumeTheme : coverLetterTheme
              }
              artifact={currentArtifact}
              exporting={artifactExporting}
              hasAnalysis={Boolean(analysisState)}
              onExport={(kind, format) =>
                void handleArtifactExport(kind, format)
              }
              onTabChange={setArtifactTab}
              onThemeChange={
                artifactTab === "resume"
                  ? setResumeTheme
                  : setCoverLetterTheme
              }
              previewHtml={artifactPreviewHtml}
              previewLoading={artifactPreviewLoading}
              previewTitle={artifactPreviewTitle}
              tab={artifactTab}
            />
          </>
        ) : null}
      </div>

      <AssistantPanel
        canSubmit={assistantCanSubmit}
        forceOpen={forceAssistantOpen}
        hasWorkspaceContext={hasWorkspaceContext}
        onClearConversation={handleClearAssistantConversation}
        onForceOpenHandled={() => setForceAssistantOpen(false)}
        onQuestionChange={setAssistantQuestion}
        onSubmit={handleAssistantSubmit}
        question={assistantQuestion}
        sending={assistantSending}
        turns={assistantTurns}
      />

      <CommandPalette
        analysisReady={stepReady.analysis}
        navigation={stepReady}
        onAskAssistant={(question) => {
          setAssistantQuestion(question);
          setForceAssistantOpen(true);
          void submitAssistantQuestion(question);
        }}
        onClearWorkspace={clearWorkspaceRole}
        onClose={() => setPaletteOpen(false)}
        onLoadSavedJob={handleLoadSavedJob}
        onNavigate={setMainTab}
        onReuploadResume={() => {
          setMainTab("resume");
          setResumeIntakeMode("upload");
        }}
        onRunAnalysis={() => void handleRunAnalysis()}
        open={paletteOpen}
        recentAssistantQuestions={recentAssistantQuestions}
        savedJobs={savedJobs}
      />
    </div>
  );
}

