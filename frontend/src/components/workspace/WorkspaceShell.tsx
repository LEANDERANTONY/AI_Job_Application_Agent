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
  generateResumeBuilderResume,
  loadLatestResumeBuilderSession,
  resolveJobUrl,
  searchJobs,
  sendResumeBuilderMessage,
  startResumeBuilderSession,
  streamWorkspaceAssistantAnswer,
  updateResumeBuilderDraft,
  uploadJobDescriptionFile,
  uploadResumeFile,
} from "@/lib/api";
import type {
  CandidateProfile,
  DailyQuotaStatus,
  JobPosting,
  JobResolveResponse,
  JobSearchResponse,
  LoadSavedWorkspaceResponse,
  ResumeBuilderSessionResponse,
  WorkspaceAnalysisResponse,
  WorkspaceJobDescriptionUploadResponse,
  WorkspaceResumeUploadResponse,
} from "@/lib/api-types";
import { buildJobReview } from "@/lib/job-workspace";
import { CheckIcon, SearchIcon } from "@/components/workspace/icons";
import {
  AssistantPanel,
  type AssistantStreamingTurn,
} from "@/components/workspace/AssistantPanel";
import { CommandPalette } from "@/components/workspace/CommandPalette";
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
import { useWorkspaceSession } from "@/hooks/useWorkspaceSession";

type Notice = {
  level: "info" | "success" | "warning";
  message: string;
} | null;

type WorkspaceMainTab = "resume" | "jobs" | "jd" | "analysis";

const STEP_LABELS: Record<WorkspaceMainTab, { number: string; label: string }> = {
  resume: { number: "01", label: "Resume" },
  jobs: { number: "02", label: "Job Search" },
  jd: { number: "03", label: "Job Detail" },
  analysis: { number: "04", label: "Analysis" },
};

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
    return "Unlimited";
  }
  return `${dailyQuota.remaining_calls}/${dailyQuota.max_calls}`;
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

  const [searchQuery, setSearchQuery] = useState("machine learning engineer");
  const [searchLocation, setSearchLocation] = useState("");
  const [remoteOnly, setRemoteOnly] = useState(false);
  const [postedWithinDays, setPostedWithinDays] = useState("");
  const [searching, setSearching] = useState(false);
  const [searchResults, setSearchResults] = useState<JobSearchResponse | null>(
    null,
  );
  const [searchNotice, setSearchNotice] = useState<Notice>(null);

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
  });

  const [selectedJobFile, setSelectedJobFile] = useState<File | null>(null);
  const [jobFileUploading, setJobFileUploading] = useState(false);
  const [jobFileNotice, setJobFileNotice] = useState<Notice>(null);
  const [jobFileState, setJobFileState] =
    useState<WorkspaceJobDescriptionUploadResponse | null>(null);
  const [jobInputCollapsed, setJobInputCollapsed] = useState(false);

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
  const [assistantStreamingTurn, setAssistantStreamingTurn] =
    useState<AssistantStreamingTurn | null>(null);
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
    if (activeJob || jobFileState) {
      setJobInputCollapsed(true);
    }
  }, [activeJob, jobFileState]);

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
  const review = manualJobText.trim()
    ? buildJobReview(manualJobText, activeJob)
    : null;

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
    resetAnalysis,
  } = useAnalysisJob({
    resumeText,
    jobDescriptionText: manualJobText,
    resumeFiletype: activeResumeState?.resume_document.filetype,
    resumeSource: activeResumeState?.resume_document.source,
    importedJobPosting: activeJob,
    authStatus,
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
  const stepReady = useMemo(
    () => ({
      resume: true,
      jobs: Boolean(currentProfile),
      jd: Boolean(currentProfile) || Boolean(activeJob),
      analysis: Boolean(resumeText.trim() && manualJobText.trim()),
    }),
    [activeJob, currentProfile, manualJobText, resumeText],
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
  const accountDisplayName =
    authSession?.app_user.display_name ||
    authSession?.app_user.email ||
    "Signed in";
  const accountInitial = accountDisplayName.slice(0, 1).toUpperCase();

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
    });
  }, [resumeBuilderSession]);

  // ⌘K / Ctrl+K toggles the command palette globally.
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen((current) => !current);
      } else if (event.key === "Escape" && paletteOpen) {
        setPaletteOpen(false);
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [paletteOpen]);

  const assistantRequiresWorkspaceRun = !analysisState;
  const assistantCanSubmit =
    !assistantRequiresWorkspaceRun &&
    !assistantSending &&
    Boolean(assistantQuestion.trim());

  // ── Handlers (unchanged) ────────────────────────────────────────
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

    setSearching(true);
    setSearchNotice({
      level: "info",
      message: "Searching live job sources...",
    });

    try {
      const response = await searchJobs({
        query: searchQuery.trim(),
        location: searchLocation.trim(),
        source_filters: ["greenhouse", "lever"],
        remote_only: remoteOnly,
        posted_within_days: postedWithinDays ? Number(postedWithinDays) : null,
        page_size: 12,
      });
      setSearchResults(response);
      setSearchNotice({
        level: response.results.length ? "success" : "info",
        message: response.results.length
          ? `Found ${response.results.length} matching jobs for the current search.`
          : "No roles matched this search yet.",
      });
    } catch (error) {
      setSearchNotice({
        level: "warning",
        message:
          error instanceof Error
            ? error.message
            : "Something went wrong while searching for roles.",
      });
    } finally {
      setSearching(false);
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
        message:
          error instanceof Error
            ? error.message
            : "The job URL import failed unexpectedly.",
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
      setResumeNotice({
        level: "success",
        message: `${response.candidate_profile.full_name || response.resume_document.filetype} is ready in the workspace.`,
      });
      setSelectedResumeFile(null);
    } catch (error) {
      setResumeNotice({
        level: "warning",
        message:
          error instanceof Error
            ? error.message
            : "Resume upload failed unexpectedly.",
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
        message:
          error instanceof Error
            ? error.message
            : "Job-description upload failed unexpectedly.",
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

    setResumeState({
      resume_document: snapshot.resume_document,
      candidate_profile: snapshot.candidate_profile,
    });
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
        message:
          error instanceof Error
            ? error.message
            : "The guided resume builder could not be started.",
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
        message:
          error instanceof Error
            ? error.message
            : "The guided resume builder could not be started.",
      });
    } finally {
      setResumeBuilderInitialized(true);
      setResumeBuilderLoading(false);
    }
  }

  async function handleResumeBuilderAnswer() {
    if (!resumeBuilderSession) {
      await handleStartResumeBuilder();
      return;
    }

    if (!resumeBuilderAnswer.trim()) {
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

    const userMessage = resumeBuilderAnswer.trim();
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
        message:
          error instanceof Error
            ? error.message
            : "That answer could not be saved.",
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
        message:
          error instanceof Error
            ? error.message
            : "The base resume draft could not be generated.",
      });
    } finally {
      setResumeBuilderGenerating(false);
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
        message:
          error instanceof Error
            ? error.message
            : "Those draft edits could not be saved.",
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
        message:
          error instanceof Error
            ? error.message
            : "This base resume could not be moved into the workspace.",
      });
    } finally {
      setResumeBuilderCommitting(false);
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

    if (!analysisState) {
      setWorkspaceNotice({
        level: "warning",
        message:
          "Run the AI analysis first so the assistant has grounded context to use.",
      });
      return;
    }

    // Abort any previous stream still in flight before starting a new one —
    // double-submits should never produce overlapping streamingTurn updates.
    assistantStreamAbortRef.current?.abort();
    const abortController = new AbortController();
    assistantStreamAbortRef.current = abortController;

    setAssistantSending(true);
    setAssistantStreamingTurn({
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
      await streamWorkspaceAssistantAnswer(
        {
          question: normalizedQuestion,
          current_page: "Workspace",
          workspace_snapshot: analysisState,
          history: buildAssistantHistoryPayload(assistantTurns),
        },
        (event) => {
          switch (event.type) {
            case "meta":
              collectedSources = event.sources;
              setAssistantStreamingTurn((current) =>
                current ? { ...current, sources: event.sources } : current,
              );
              break;
            case "delta":
              accumulatedAnswer += event.text;
              setAssistantStreamingTurn((current) =>
                current
                  ? { ...current, partialAnswer: accumulatedAnswer }
                  : current,
              );
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
        setAssistantStreamingTurn((current) =>
          current
            ? { ...current, isStreaming: false, error: streamErrorDetail }
            : current,
        );
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
      setAssistantStreamingTurn(null);
      setAssistantQuestion("");
    } catch (error) {
      const isAbort =
        error instanceof DOMException && error.name === "AbortError";
      if (isAbort) {
        setAssistantStreamingTurn(null);
        return;
      }
      setWorkspaceNotice({
        level: "warning",
        message:
          error instanceof Error
            ? error.message
            : "Assistant request failed unexpectedly.",
      });
      setAssistantStreamingTurn((current) =>
        current
          ? {
              ...current,
              isStreaming: false,
              error:
                error instanceof Error
                  ? error.message
                  : "Assistant request failed unexpectedly.",
            }
          : current,
      );
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
    setAssistantStreamingTurn(null);
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

  // Outside-click + Escape close the account popover.
  useEffect(() => {
    if (!accountMenuOpen) return;

    function handlePointerDown(event: MouseEvent) {
      if (!accountMenuRef.current?.contains(event.target as Node)) {
        setAccountMenuOpen(false);
      }
    }
    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setAccountMenuOpen(false);
      }
    }

    window.addEventListener("mousedown", handlePointerDown);
    window.addEventListener("keydown", handleEscape);
    return () => {
      window.removeEventListener("mousedown", handlePointerDown);
      window.removeEventListener("keydown", handleEscape);
    };
  }, [accountMenuOpen]);

  // Recent assistant questions for the command palette.
  const recentAssistantQuestions = useMemo(
    () => assistantTurns.slice(-5).map((turn) => turn.question).reverse(),
    [assistantTurns],
  );

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
                aria-expanded={accountMenuOpen}
                aria-haspopup="menu"
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
                  className="b-account-popover"
                  onClick={(event) => event.stopPropagation()}
                  role="menu"
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
                      <dd>{authSession?.app_user.plan_tier || "free"}</dd>
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
          const lockReason: Record<WorkspaceMainTab, string> = {
            resume: "",
            jobs: "Upload a resume to unlock.",
            jd: "Upload a resume to unlock.",
            analysis: "Need a parsed resume + job description first.",
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
                    aria-selected={active}
                    className="b-rail-step"
                    data-done={done || undefined}
                    data-next={isNext || undefined}
                    disabled={!ready}
                    key={step}
                    onClick={() => {
                      if (ready) setMainTab(step);
                    }}
                    role="tab"
                    title={tooltip}
                    type="button"
                  >
                    <span className="b-rail-num">
                      {done ? <CheckIcon /> : meta.number}
                    </span>
                    {meta.label}
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
            {workspaceNotice.message}
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
            builderGenerating={resumeBuilderGenerating}
            builderLoading={resumeBuilderLoading}
            builderNotice={resumeBuilderNotice}
            builderSession={resumeBuilderSession}
            currentProfile={currentProfile}
            mode={resumeIntakeMode}
            onBuilderAnswerChange={setResumeBuilderAnswer}
            onBuilderAnswerSubmit={() => void handleResumeBuilderAnswer()}
            onBuilderCommit={() => void handleResumeBuilderCommit()}
            onBuilderDraftSave={() => void handleResumeBuilderDraftSave()}
            onBuilderGenerate={() => void handleResumeBuilderGenerate()}
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
            importing={importing}
            jobUrl={jobUrl}
            latestSavedJobAt={latestSavedJobAt}
            onImportSubmit={handleResolveJob}
            onJobUrlChange={setJobUrl}
            onLoadSavedJob={handleLoadSavedJob}
            onPostedWithinDaysChange={setPostedWithinDays}
            onRemoteOnlyChange={setRemoteOnly}
            onRemoveSavedJob={(job) => void handleRemoveSavedJob(job)}
            onReviewRole={(job) => {
              setActiveJob(job);
              setMainTab("jd");
            }}
            onSaveJob={(job) => void handleSaveJob(job)}
            onSearchLocationChange={setSearchLocation}
            onSearchQueryChange={setSearchQuery}
            onSearchSubmit={handleSearch}
            postedWithinDays={postedWithinDays}
            remoteOnly={remoteOnly}
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
              currentWorkflowStage={currentWorkflowStage}
              onClearRole={clearWorkspaceRole}
              onRunAnalysis={() => void handleRunAnalysis()}
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
        onClearConversation={handleClearAssistantConversation}
        onForceOpenHandled={() => setForceAssistantOpen(false)}
        onQuestionChange={setAssistantQuestion}
        onSubmit={handleAssistantSubmit}
        question={assistantQuestion}
        requiresWorkspaceRun={assistantRequiresWorkspaceRun}
        sending={assistantSending}
        streamingTurn={assistantStreamingTurn}
        turns={assistantTurns}
      />

      <CommandPalette
        analysisReady={stepReady.analysis}
        assistantUnlocked={!assistantRequiresWorkspaceRun}
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

