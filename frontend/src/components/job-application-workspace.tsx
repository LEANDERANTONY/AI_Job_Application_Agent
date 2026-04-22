"use client";

import { useEffect, useMemo, useState } from "react";

import {
  askWorkspaceAssistant,
  exchangeGoogleCode,
  exportWorkspaceArtifact,
  getBackendHealth,
  loadSavedJobs,
  loadSavedWorkspace,
  previewWorkspaceArtifact,
  removeSavedJob,
  resolveJobUrl,
  restoreAuthSession,
  runWorkspaceAnalysis,
  saveSavedJob,
  saveWorkspaceSnapshot,
  searchJobs,
  signOutAuthSession,
  startGoogleSignIn,
  uploadJobDescriptionFile,
  uploadResumeFile,
} from "@/lib/api";
import type {
  AuthSessionResponse,
  AuthTokens,
  BackendHealth,
  CandidateProfile,
  DailyQuotaStatus,
  JobPosting,
  JobResolveResponse,
  JobSearchResponse,
  LoadSavedWorkspaceResponse,
  SavedWorkspaceMeta,
  WorkspaceAnalysisResponse,
  WorkspaceArtifactKind,
  WorkspaceAssistantResponse,
  WorkspaceJobDescriptionUploadResponse,
  WorkspaceResumeUploadResponse,
} from "@/lib/api-types";
import {
  buildJobResultBadges,
  buildJobReview,
  buildSourceCoverage,
} from "@/lib/job-workspace";

type Notice = {
  level: "info" | "success" | "warning";
  message: string;
} | null;

type ArtifactTab = "resume" | "cover-letter" | "report";
type WorkspaceMainTab = "resume" | "jobs" | "jd" | "analysis";

type HealthState =
  | { status: "loading"; payload: null; error: null }
  | { status: "ready"; payload: BackendHealth; error: null }
  | { status: "error"; payload: null; error: string };

type AssistantTurn = {
  question: string;
  response: WorkspaceAssistantResponse;
};

type AuthStatus = "loading" | "restoring" | "signed_out" | "signed_in";

type ResumeTheme = "classic_ats" | "modern_professional";
type WorkflowRunMode = "preview" | "agentic";
type WorkflowStage = {
  title: string;
  detail: string;
  value: number;
};

const AUTH_SESSION_STORAGE_KEY = "workspace-auth-session-v1";
const ASSISTANT_HISTORY_STORAGE_KEY = "workspace-assistant-history-v1";
const MAX_PERSISTED_ASSISTANT_TURNS = 8;
const RESUME_THEME_OPTIONS: Record<
  ResumeTheme,
  { label: string; tagline: string }
> = {
  classic_ats: {
    label: "Classic ATS",
    tagline: "Single-column, ATS-safe, recruiter-readable structure.",
  },
  modern_professional: {
    label: "Modern Professional",
    tagline: "Cleaner hierarchy with a slightly more polished visual rhythm.",
  },
};

const PREVIEW_WORKFLOW_STAGES: WorkflowStage[] = [
  {
    title: "Workflow crew",
    detail: "Opening your application brief and lining up the deterministic workspace checks.",
    value: 8,
  },
  {
    title: "Matchmaker agent",
    detail: "Comparing the resume and JD to score overlap, strengths, and the biggest missing signals.",
    value: 38,
  },
  {
    title: "Forge agent",
    detail: "Drafting the recruiter-facing resume guidance and assembling the first artifact set.",
    value: 72,
  },
  {
    title: "Builder agent",
    detail: "Packaging the preview outputs so the workspace can render the report, resume, and cover letter.",
    value: 96,
  },
];

const AGENTIC_WORKFLOW_STAGES: WorkflowStage[] = [
  {
    title: "Workflow crew",
    detail: "Opening your application brief and assigning the first agent.",
    value: 3,
  },
  {
    title: "Matchmaker agent",
    detail: "Comparing both sides, scoring overlap, and flagging the real gaps.",
    value: 23,
  },
  {
    title: "Forge agent",
    detail: "Rewriting the draft so it speaks directly to this role.",
    value: 41,
  },
  {
    title: "Navigator agent",
    detail: "Shaping the recruiter story so the pitch lands cleanly.",
    value: 59,
  },
  {
    title: "Gatekeeper agent",
    detail: "Reviewing the drafted outputs and applying grounded corrections.",
    value: 77,
  },
  {
    title: "Builder agent",
    detail: "Packaging the final tailored resume and lining up the finish.",
    value: 90,
  },
  {
    title: "Cover letter agent",
    detail: "Turning the approved story into a role-specific cover letter that is ready to send.",
    value: 97,
  },
];

function noticeClassName(level: NonNullable<Notice>["level"]) {
  if (level === "success") {
    return "notice-panel notice-success";
  }
  if (level === "warning") {
    return "notice-panel notice-warning";
  }
  return "notice-panel notice-info";
}

function resultPreview(job: JobPosting) {
  if (job.summary.trim()) {
    return job.summary.trim();
  }
  if (job.description_text.trim()) {
    const text = job.description_text.replace(/\s+/g, " ").trim();
    return text.length > 220 ? `${text.slice(0, 217)}...` : text;
  }
  return "Open the role in the workspace to inspect the normalized JD review.";
}

function toneForStage(active: boolean, ready = false) {
  if (active) {
    return "live";
  }
  if (ready) {
    return "ready";
  }
  return "next";
}

function workflowProgressTone(title: string) {
  if (title === "Workflow crew") {
    return "crew";
  }
  if (title === "Backup workflow") {
    return "backup";
  }
  if (title === "Matchmaker agent") {
    return "matchmaker";
  }
  if (title === "Forge agent") {
    return "forge";
  }
  if (title === "Navigator agent") {
    return "navigator";
  }
  if (title === "Gatekeeper agent") {
    return "gatekeeper";
  }
  if (title === "Builder agent") {
    return "builder";
  }
  if (title === "Cover letter agent") {
    return "coverletter";
  }
  return "crew";
}

function buildAssistantHistoryPayload(turns: AssistantTurn[]) {
  return turns.map((turn) => ({
    question: turn.question,
    answer: turn.response.answer,
  }));
}

function hashString(value: string) {
  let hash = 5381;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 33) ^ value.charCodeAt(index);
  }
  return (hash >>> 0).toString(36);
}

function buildAssistantWorkspaceSignature(
  workspaceSnapshot: WorkspaceAnalysisResponse | null,
) {
  if (!workspaceSnapshot) {
    return null;
  }

  const signaturePayload = {
    resume_text: workspaceSnapshot.resume_document.text,
    job_text: workspaceSnapshot.job_description.raw_text,
    workflow_mode: workspaceSnapshot.workflow.mode,
    fit_score: workspaceSnapshot.fit_analysis.overall_score,
    readiness_label: workspaceSnapshot.fit_analysis.readiness_label,
    resume_summary: workspaceSnapshot.artifacts.tailored_resume.summary,
    cover_letter_summary: workspaceSnapshot.artifacts.cover_letter.summary,
    report_summary: workspaceSnapshot.artifacts.report.summary,
    imported_job_id: workspaceSnapshot.imported_job_posting?.id ?? "",
  };

  return hashString(JSON.stringify(signaturePayload));
}

function readStoredAssistantTurns(storageKey: string) {
  if (typeof window === "undefined") {
    return [] as AssistantTurn[];
  }

  try {
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) {
      return [] as AssistantTurn[];
    }
    const payload = JSON.parse(raw);
    if (!Array.isArray(payload)) {
      return [] as AssistantTurn[];
    }
    return payload
      .flatMap((item) => {
        const question =
          typeof item?.question === "string" ? item.question.trim() : "";
        const answer =
          typeof item?.response?.answer === "string"
            ? item.response.answer.trim()
            : "";
        const sources = Array.isArray(item?.response?.sources)
          ? item.response.sources
              .map((source: unknown) =>
                typeof source === "string" ? source.trim() : "",
              )
              .filter(Boolean)
          : [];
        const suggestedFollowUps = Array.isArray(
          item?.response?.suggested_follow_ups,
        )
          ? item.response.suggested_follow_ups
              .map((followUp: unknown) =>
                typeof followUp === "string" ? followUp.trim() : "",
              )
              .filter(Boolean)
          : [];
        if (!question || !answer) {
          return [];
        }
        return [
          {
            question,
            response: {
              answer,
              sources,
              suggested_follow_ups: suggestedFollowUps,
            },
          } satisfies AssistantTurn,
        ];
      })
      .slice(-MAX_PERSISTED_ASSISTANT_TURNS);
  } catch {
    return [] as AssistantTurn[];
  }
}

function persistAssistantTurns(storageKey: string, turns: AssistantTurn[]) {
  if (typeof window === "undefined") {
    return;
  }

  if (!turns.length) {
    window.localStorage.removeItem(storageKey);
    return;
  }

  const serializableTurns = turns.slice(-MAX_PERSISTED_ASSISTANT_TURNS).map((turn) => ({
    question: turn.question,
    response: {
      answer: turn.response.answer,
      sources: turn.response.sources,
      suggested_follow_ups: turn.response.suggested_follow_ups,
    },
  }));
  window.localStorage.setItem(storageKey, JSON.stringify(serializableTurns));
}

function downloadBase64File(filename: string, contentBase64: string, mimeType: string) {
  const binary = atob(contentBase64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  const blob = new Blob([bytes], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function latestRole(profile: CandidateProfile | null) {
  const entry = profile?.experience?.[0];
  if (!entry) {
    return "No parsed role yet";
  }
  if (entry.title && entry.organization) {
    return `${entry.title} at ${entry.organization}`;
  }
  return entry.title || entry.organization || "No parsed role yet";
}

function renderArtifactTitle(tab: ArtifactTab) {
  if (tab === "resume") {
    return "Tailored Resume";
  }
  if (tab === "cover-letter") {
    return "Cover Letter";
  }
  return "Application Report";
}

function artifactKindFromTab(tab: ArtifactTab): Exclude<WorkspaceArtifactKind, "bundle"> {
  if (tab === "resume") {
    return "tailored_resume";
  }
  if (tab === "cover-letter") {
    return "cover_letter";
  }
  return "report";
}

function readStoredAuthTokens(): AuthTokens | null {
  if (typeof window === "undefined") {
    return null;
  }

  try {
    const raw = window.localStorage.getItem(AUTH_SESSION_STORAGE_KEY);
    if (!raw) {
      return null;
    }
    const payload = JSON.parse(raw);
    if (
      typeof payload?.access_token === "string" &&
      typeof payload?.refresh_token === "string" &&
      payload.access_token.trim() &&
      payload.refresh_token.trim()
    ) {
      return {
        access_token: payload.access_token,
        refresh_token: payload.refresh_token,
      };
    }
  } catch {
    return null;
  }

  return null;
}

function persistAuthTokens(tokens: AuthTokens) {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(AUTH_SESSION_STORAGE_KEY, JSON.stringify(tokens));
}

function clearStoredAuthTokens() {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.removeItem(AUTH_SESSION_STORAGE_KEY);
}

function buildWorkspaceRedirectUrl() {
  if (typeof window === "undefined") {
    return "";
  }
  return `${window.location.origin}/workspace`;
}

function clearAuthQueryParams() {
  if (typeof window === "undefined") {
    return;
  }
  const url = new URL(window.location.href);
  url.searchParams.delete("code");
  url.searchParams.delete("auth_flow");
  url.searchParams.delete("error");
  url.searchParams.delete("error_description");
  window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
}

function formatUtcTimestamp(value: string) {
  if (!value) {
    return "";
  }
  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime())) {
    return value;
  }
  return timestamp.toLocaleString(undefined, {
    timeZone: "UTC",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatRemainingCalls(dailyQuota: DailyQuotaStatus | null) {
  if (!dailyQuota) {
    return "Unavailable";
  }
  if (dailyQuota.remaining_calls === null || dailyQuota.max_calls === null) {
    return "Unlimited";
  }
  return `${dailyQuota.remaining_calls}/${dailyQuota.max_calls}`;
}

function formatSavedLabel(value: string) {
  return value ? `Saved ${value.slice(0, 10)}` : "Saved";
}

function sortSavedJobs(jobs: JobPosting[]) {
  return [...jobs].sort((left, right) => {
    const leftSaved = left.saved_at ?? "";
    const rightSaved = right.saved_at ?? "";
    if (leftSaved !== rightSaved) {
      return rightSaved.localeCompare(leftSaved);
    }
    const leftPosted = left.posted_at ?? "";
    const rightPosted = right.posted_at ?? "";
    if (leftPosted !== rightPosted) {
      return rightPosted.localeCompare(leftPosted);
    }
    return left.title.localeCompare(right.title);
  });
}

function getInitialSidebarCollapsed() {
  if (typeof window === "undefined") {
    return false;
  }

  const drawerParam = new URLSearchParams(window.location.search).get("drawer");
  if (drawerParam === "closed") {
    return true;
  }
  if (drawerParam === "open") {
    return false;
  }

  return false;
}

export function JobApplicationWorkspace() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(getInitialSidebarCollapsed);
  const [mainTab, setMainTab] = useState<WorkspaceMainTab>("resume");
  const [health, setHealth] = useState<HealthState>({
    status: "loading",
    payload: null,
    error: null,
  });
  const [authStatus, setAuthStatus] = useState<AuthStatus>("loading");
  const [authSession, setAuthSession] = useState<AuthSessionResponse | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [authActionLoading, setAuthActionLoading] = useState(false);
  const [workspaceReloading, setWorkspaceReloading] = useState(false);
  const [workspaceSaveMeta, setWorkspaceSaveMeta] =
    useState<SavedWorkspaceMeta | null>(null);
  const [autoSaving, setAutoSaving] = useState(false);

  const [searchQuery, setSearchQuery] = useState("machine learning engineer");
  const [searchLocation, setSearchLocation] = useState("");
  const [remoteOnly, setRemoteOnly] = useState(false);
  const [postedWithinDays, setPostedWithinDays] = useState("");
  const [searching, setSearching] = useState(false);
  const [searchResults, setSearchResults] = useState<JobSearchResponse | null>(
    null,
  );
  const [searchNotice, setSearchNotice] = useState<Notice>(null);
  const [savedJobs, setSavedJobs] = useState<JobPosting[]>([]);
  const [savedJobsLoading, setSavedJobsLoading] = useState(false);
  const [savedJobsNotice, setSavedJobsNotice] = useState<Notice>(null);
  const [savedJobActionId, setSavedJobActionId] = useState<string | null>(null);

  const [jobUrl, setJobUrl] = useState("");
  const [importing, setImporting] = useState(false);
  const [workspaceNotice, setWorkspaceNotice] = useState<Notice>(null);
  const [activeJob, setActiveJob] = useState<JobPosting | null>(null);

  const [selectedResumeFile, setSelectedResumeFile] = useState<File | null>(null);
  const [resumeUploading, setResumeUploading] = useState(false);
  const [resumeNotice, setResumeNotice] = useState<Notice>(null);
  const [resumeState, setResumeState] =
    useState<WorkspaceResumeUploadResponse | null>(null);

  const [selectedJobFile, setSelectedJobFile] = useState<File | null>(null);
  const [jobFileUploading, setJobFileUploading] = useState(false);
  const [jobFileNotice, setJobFileNotice] = useState<Notice>(null);
  const [jobFileState, setJobFileState] =
    useState<WorkspaceJobDescriptionUploadResponse | null>(null);

  const [manualJobText, setManualJobText] = useState("");
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisRunMode, setAnalysisRunMode] = useState<WorkflowRunMode | null>(null);
  const [analysisProgressIndex, setAnalysisProgressIndex] = useState(0);
  const [analysisState, setAnalysisState] =
    useState<WorkspaceAnalysisResponse | null>(null);
  const [artifactTab, setArtifactTab] = useState<ArtifactTab>("resume");
  const [resumeTheme, setResumeTheme] = useState<ResumeTheme>("classic_ats");
  const [artifactExporting, setArtifactExporting] = useState<string | null>(null);
  const [artifactPreviewHtml, setArtifactPreviewHtml] = useState<string | null>(null);
  const [artifactPreviewTitle, setArtifactPreviewTitle] = useState<string | null>(null);
  const [artifactPreviewLoading, setArtifactPreviewLoading] = useState(false);

  const [assistantQuestion, setAssistantQuestion] = useState("");
  const [assistantSending, setAssistantSending] = useState(false);
  const [assistantTurns, setAssistantTurns] = useState<AssistantTurn[]>([]);

  useEffect(() => {
    let cancelled = false;

    async function loadHealth() {
      try {
        const payload = await getBackendHealth();
        if (!cancelled) {
          setHealth({ status: "ready", payload, error: null });
        }
      } catch (error) {
        if (!cancelled) {
          setHealth({
            status: "error",
            payload: null,
            error:
              error instanceof Error
                ? error.message
                : "Backend health check failed.",
          });
        }
      }
    }

    void loadHealth();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function bootstrapAuth() {
      if (typeof window === "undefined") {
        return;
      }

      const params = new URLSearchParams(window.location.search);
      const authCode = params.get("code");
      const authFlow = params.get("auth_flow") ?? "";
      const authErrorDescription =
        params.get("error_description") ?? params.get("error");

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
            buildWorkspaceRedirectUrl(),
          );
          if (!cancelled) {
            persistAuthTokens(response.session);
            setAuthSession(response);
            setAuthStatus("signed_in");
            setWorkspaceNotice({
              level: "success",
              message: `Signed in as ${response.app_user.display_name || response.app_user.email || "your account"}.`,
            });
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

    void bootstrapAuth();

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (activeJob?.description_text) {
      setManualJobText(activeJob.description_text);
      setJobFileState(null);
    }
  }, [activeJob]);

  const authTokens = authSession?.session ?? null;
  const dailyQuota = authSession?.daily_quota ?? null;
  const savedJobsEnabled = Boolean(authSession?.features.saved_jobs_enabled);

  useEffect(() => {
    const sessionTokens = authTokens;
    if (
      authStatus !== "signed_in" ||
      !sessionTokens ||
      !authSession?.features.saved_jobs_enabled
    ) {
      setSavedJobs([]);
      setSavedJobsLoading(false);
      return;
    }
    const resolvedAuthTokens: AuthTokens = sessionTokens;

    let cancelled = false;

    async function hydrateSavedJobs() {
      setSavedJobsLoading(true);
      try {
        const response = await loadSavedJobs(resolvedAuthTokens);
        if (!cancelled) {
          setSavedJobs(sortSavedJobs(response.saved_jobs));
        }
      } catch (error) {
        if (!cancelled) {
          setSavedJobsNotice({
            level: "warning",
            message:
              error instanceof Error
                ? error.message
                : "Saved jobs could not be loaded right now.",
          });
          setSavedJobs([]);
        }
      } finally {
        if (!cancelled) {
          setSavedJobsLoading(false);
        }
      }
    }

    void hydrateSavedJobs();

    return () => {
      cancelled = true;
    };
  }, [authSession?.features.saved_jobs_enabled, authStatus, authTokens]);

  const savedJobIds = useMemo(
    () =>
      new Set(
        savedJobs
          .map((job) => job.id.trim())
          .filter(Boolean),
      ),
    [savedJobs],
  );
  const latestSavedJobAt = useMemo(
    () =>
      savedJobs.reduce((latest, job) => {
        const savedAt = job.saved_at ?? "";
        return savedAt > latest ? savedAt : latest;
      }, ""),
    [savedJobs],
  );
  const activeResumeState = resumeState ?? analysisState;
  const resumeText = activeResumeState?.resume_document.text ?? "";
  const currentProfile = activeResumeState?.candidate_profile ?? null;
  const review = manualJobText.trim()
    ? buildJobReview(manualJobText, activeJob)
    : null;
  const sourceCoverage = buildSourceCoverage(searchResults?.source_status ?? {});

  const analysisIsStale = Boolean(
    analysisState &&
      (analysisState.resume_document.text !== resumeText ||
        analysisState.job_description.raw_text !== manualJobText.trim()),
  );

  const currentArtifact = useMemo(() => {
    if (!analysisState) {
      return null;
    }
    if (artifactTab === "resume") {
      const themeMeta = RESUME_THEME_OPTIONS[resumeTheme];
      return {
        ...analysisState.artifacts.tailored_resume,
        theme: resumeTheme,
        summary: `Tailored resume draft for ${
          analysisState.job_description.title || "the target role"
        } using the ${themeMeta.label} template.`,
      };
    }
    if (artifactTab === "cover-letter") {
      return analysisState.artifacts.cover_letter;
    }
    return analysisState.artifacts.report;
  }, [analysisState, artifactTab, resumeTheme]);
  const currentArtifactKind = artifactKindFromTab(artifactTab);
  const workflowStages = useMemo(() => {
    if (analysisRunMode === "agentic") {
      return AGENTIC_WORKFLOW_STAGES;
    }
    if (analysisRunMode === "preview") {
      return PREVIEW_WORKFLOW_STAGES;
    }
    return [] as WorkflowStage[];
  }, [analysisRunMode]);
  const currentWorkflowStage =
    workflowStages[Math.min(analysisProgressIndex, Math.max(workflowStages.length - 1, 0))] ??
    null;
  const workspaceTabs = useMemo(
    () => [
      {
        id: "resume" as const,
        label: "Resume",
        title: "Load your candidate profile",
        copy:
          "Upload and parse your resume so the rest of the workspace can reuse the candidate snapshot.",
        status: currentProfile ? "Ready" : "Start here",
        tone: currentProfile ? "live" : "ready",
      },
      {
        id: "jobs" as const,
        label: "Job Search",
        title: "Search boards or import a role",
        copy:
          "Search the live boards, import a direct URL, or pull from your saved shortlist.",
        status: activeJob
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
      {
        id: "jd" as const,
        label: "Job Details",
        title: "Review the JD in one place",
        copy:
          "Combine JD upload, pasted text, and the parsed review panel into one focused lane.",
        status: review ? "JD ready" : manualJobText.trim() ? "Drafting" : "Add a JD",
        tone: review ? "live" : manualJobText.trim() ? "ready" : "idle",
      },
      {
        id: "analysis" as const,
        label: "Analysis & Outputs",
        title: "Run the workflow and inspect artifacts",
        copy:
          "Trigger the preview or agentic workflow, then review the outputs and export the package.",
        status: analysisState
          ? "Outputs ready"
          : resumeText.trim() && manualJobText.trim()
            ? "Ready to run"
            : "Waiting",
        tone: analysisState
          ? "live"
          : resumeText.trim() && manualJobText.trim()
            ? "ready"
            : "idle",
      },
    ],
    [activeJob, analysisState, currentProfile, manualJobText, resumeText, review, searchResults],
  );
  const activeMainTabMeta =
    workspaceTabs.find((tab) => tab.id === mainTab) ?? workspaceTabs[0];

  useEffect(() => {
    if (!analysisLoading || !analysisRunMode || !workflowStages.length) {
      return;
    }

    const interval = window.setInterval(() => {
      setAnalysisProgressIndex((currentIndex) => {
        if (currentIndex >= workflowStages.length - 1) {
          return currentIndex;
        }
        return currentIndex + 1;
      });
    }, analysisRunMode === "agentic" ? 3200 : 2200);

    return () => {
      window.clearInterval(interval);
    };
  }, [analysisLoading, analysisRunMode, workflowStages]);

  const assistantWorkspaceSignature = useMemo(
    () => buildAssistantWorkspaceSignature(analysisState),
    [analysisState],
  );
  const assistantStorageKey = useMemo(() => {
    if (!assistantWorkspaceSignature) {
      return null;
    }
    const userScope = authSession?.app_user.id || "anonymous";
    return `${ASSISTANT_HISTORY_STORAGE_KEY}:${userScope}:${assistantWorkspaceSignature}`;
  }, [assistantWorkspaceSignature, authSession?.app_user.id]);
  const latestAssistantTurn = assistantTurns[assistantTurns.length - 1] ?? null;
  const assistantRequiresWorkspaceRun = !analysisState;
  const assistantCanSubmit =
    !assistantRequiresWorkspaceRun &&
    !assistantSending &&
    Boolean(assistantQuestion.trim());
  const assistantStatusLabel = analysisState
    ? assistantTurns.length
      ? "Memory active"
      : "Fresh thread"
    : "Waiting for run";
  const assistantStatusCopy = analysisState
    ? assistantTurns.length
      ? `This chat is scoped to ${analysisState.job_description.title || "the current workspace"} and restores on reload.`
      : `Start a fresh grounded thread for ${analysisState.job_description.title || "the current workspace"}.`
    : "Unlocks after your first workspace preview or AI analysis run.";

  useEffect(() => {
    if (!assistantStorageKey) {
      setAssistantTurns([]);
      return;
    }
    setAssistantTurns(readStoredAssistantTurns(assistantStorageKey));
  }, [assistantStorageKey]);

  useEffect(() => {
    if (!assistantStorageKey) {
      return;
    }
    persistAssistantTurns(assistantStorageKey, assistantTurns);
  }, [assistantStorageKey, assistantTurns]);

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
      message: "Checking that job posting and loading it into your workspace...",
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

  async function handleSaveJob(job: JobPosting) {
    if (!authTokens) {
      setSavedJobsNotice({
        level: "warning",
        message: "Sign in with Google before saving jobs to your shortlist.",
      });
      return;
    }

    setSavedJobActionId(job.id);
    try {
      const response = await saveSavedJob(job, authTokens);
      setSavedJobs((current) =>
        sortSavedJobs([
          response.saved_job,
          ...current.filter((item) => item.id !== response.saved_job.id),
        ]),
      );
      setSavedJobsNotice({
        level: "success",
        message: response.message,
      });
    } catch (error) {
      setSavedJobsNotice({
        level: "warning",
        message:
          error instanceof Error
            ? error.message
            : "This role could not be saved to your shortlist.",
      });
    } finally {
      setSavedJobActionId(null);
    }
  }

  async function handleRemoveSavedJob(job: JobPosting) {
    if (!authTokens) {
      setSavedJobsNotice({
        level: "warning",
        message: "Sign in with Google before editing your shortlist.",
      });
      return;
    }

    setSavedJobActionId(job.id);
    try {
      await removeSavedJob(job.id, authTokens);
      setSavedJobs((current) => current.filter((item) => item.id !== job.id));
      setSavedJobsNotice({
        level: "success",
        message: `Removed ${job.title || "this role"} from your shortlist.`,
      });
    } catch (error) {
      setSavedJobsNotice({
        level: "warning",
        message:
          error instanceof Error
            ? error.message
            : "This role could not be removed from your shortlist.",
      });
    } finally {
      setSavedJobActionId(null);
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
      const response = await uploadResumeFile(file, authTokens);
      setResumeState(response);
      setMainTab("jobs");
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

  async function handleJobDescriptionUpload(file: File | null = selectedJobFile) {
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
      const response = await uploadJobDescriptionFile(file, authTokens);
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

  function applySavedWorkspaceSnapshot(response: LoadSavedWorkspaceResponse) {
    const snapshot = response.workspace_snapshot;
    if (!snapshot) {
      return;
    }

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
    setResumeTheme(
      (snapshot.artifacts.tailored_resume.theme as ResumeTheme | undefined) ??
        "classic_ats",
    );
    setArtifactPreviewHtml(null);
    setArtifactPreviewTitle(null);
    setAssistantTurns([]);
    setMainTab("analysis");
  }

  async function handleGoogleSignIn() {
    setAuthActionLoading(true);
    setAuthError(null);
    try {
      const response = await startGoogleSignIn(buildWorkspaceRedirectUrl());
      window.location.href = response.url;
    } catch (error) {
      setAuthError(
        error instanceof Error
          ? error.message
          : "Google sign-in could not be started.",
      );
      setWorkspaceNotice({
        level: "warning",
        message:
          error instanceof Error
            ? error.message
            : "Google sign-in could not be started.",
      });
      setAuthActionLoading(false);
    }
  }

  async function handleSignOut() {
    if (!authTokens) {
      return;
    }

    setAuthActionLoading(true);
    try {
      await signOutAuthSession(authTokens);
    } catch {
      // Clearing local state is still the right fallback if server sign-out fails.
    } finally {
      clearStoredAuthTokens();
      setAuthSession(null);
      setAuthStatus("signed_out");
      setAuthError(null);
      setWorkspaceSaveMeta(null);
      setSavedJobs([]);
      setSavedJobsNotice(null);
      setAuthActionLoading(false);
      setWorkspaceNotice({
        level: "info",
        message: "Signed out. Local account session and saved-state access were cleared.",
      });
    }
  }

  async function handleReloadSavedWorkspace() {
    if (!authTokens) {
      setWorkspaceNotice({
        level: "warning",
        message: "Sign in with Google before reloading a saved workspace.",
      });
      return;
    }

    setWorkspaceReloading(true);
    try {
      const response = await loadSavedWorkspace(authTokens);
      if (response.status !== "available" || !response.workspace_snapshot) {
        setWorkspaceNotice({
          level: response.status === "expired" ? "warning" : "info",
          message:
            response.status === "expired"
              ? "Your saved workspace expired after 24 hours. Run the flow again to save a fresh one."
              : "No saved workspace is available to reload yet.",
        });
        return;
      }

      applySavedWorkspaceSnapshot(response);
      setWorkspaceSaveMeta(response.saved_workspace ?? null);
      setWorkspaceNotice({
        level: "success",
        message: `Saved workspace reloaded. Expires ${formatUtcTimestamp(response.saved_workspace?.expires_at ?? "")} UTC.`,
      });
    } catch (error) {
      setWorkspaceNotice({
        level: "warning",
        message:
          error instanceof Error
            ? error.message
            : "Saved workspace reload failed unexpectedly.",
      });
    } finally {
      setWorkspaceReloading(false);
    }
  }

  async function persistLatestWorkspace(snapshot: WorkspaceAnalysisResponse) {
    if (!authTokens || !authSession?.features.saved_workspace_enabled) {
      return null;
    }

    setAutoSaving(true);
    try {
      const response = await saveWorkspaceSnapshot(snapshot, authTokens);
      setWorkspaceSaveMeta(response.saved_workspace);
      return response.saved_workspace;
    } catch (error) {
      setWorkspaceNotice({
        level: "warning",
        message:
          error instanceof Error
            ? error.message
            : "The latest workspace could not be saved.",
      });
      return null;
    } finally {
      setAutoSaving(false);
    }
  }

  async function handleRunAnalysis(runAssisted: boolean) {
    if (!resumeText.trim()) {
      setWorkspaceNotice({
        level: "warning",
        message: "Upload and parse a resume before running the workspace flow.",
      });
      return;
    }

    if (!manualJobText.trim()) {
      setWorkspaceNotice({
        level: "warning",
        message: "Load or paste a job description before running the workspace flow.",
      });
      return;
    }

    if (runAssisted && !authTokens) {
      setWorkspaceNotice({
        level: "warning",
        message: "Sign in with Google before running the AI-assisted workflow.",
      });
      return;
    }

    setAnalysisRunMode(runAssisted ? "agentic" : "preview");
    setAnalysisProgressIndex(0);
    setAnalysisLoading(true);
    setWorkspaceNotice({
      level: "info",
      message: runAssisted
        ? "Running the agentic workflow through the backend. The workspace crew will keep you posted as each stage moves."
        : "Building the deterministic workspace preview through the backend.",
    });

    try {
      const response = await runWorkspaceAnalysis({
        resume_text: resumeText,
        resume_filetype: activeResumeState?.resume_document.filetype ?? "TXT",
        resume_source: activeResumeState?.resume_document.source ?? "workspace",
        job_description_text: manualJobText.trim(),
        imported_job_posting: activeJob,
        run_assisted: runAssisted,
      }, authTokens);
      setAnalysisState(response);
      setArtifactTab("resume");
      setResumeTheme(
        (response.artifacts.tailored_resume.theme as ResumeTheme | undefined) ??
          "classic_ats",
      );
      setMainTab("analysis");
      setArtifactPreviewHtml(null);
      setArtifactPreviewTitle(null);
      const savedWorkspace = await persistLatestWorkspace(response);
        setWorkspaceNotice({
          level: "success",
          message: runAssisted
          ? savedWorkspace
            ? `Workflow finished in ${response.workflow.mode} mode and saved workspace refreshes until ${formatUtcTimestamp(savedWorkspace.expires_at)} UTC.`
            : `Workflow finished in ${response.workflow.mode} mode.`
          : savedWorkspace
            ? `Deterministic workspace preview is ready and saved workspace refreshes until ${formatUtcTimestamp(savedWorkspace.expires_at)} UTC.`
              : "Deterministic workspace preview is ready.",
        });
      } catch (error) {
        const errorMessage =
          error instanceof Error
            ? error.message
            : "Workspace analysis failed unexpectedly.";
        const looksLikeGatewayFailure =
          runAssisted &&
          /(502|bad gateway|gateway|proxy)/i.test(errorMessage);
        setWorkspaceNotice({
          level: "warning",
          message: looksLikeGatewayFailure
            ? "The agentic run was interrupted by the gateway before the backend finished responding. The new run panel shows stage progress, but we still need to move the assisted workflow to a background job to make proxied runs fully reliable."
            : errorMessage,
        });
      } finally {
        setAnalysisLoading(false);
        setAnalysisRunMode(null);
        setAnalysisProgressIndex(0);
      }
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
        message: "Run the workspace preview first so the assistant has grounded context to use.",
      });
      return;
    }

    setAssistantSending(true);

    try {
      const response = await askWorkspaceAssistant({
        question: normalizedQuestion,
        current_page: "Workspace",
        workspace_snapshot: analysisState,
        history: buildAssistantHistoryPayload(assistantTurns),
      }, authTokens);
      setAssistantTurns((current) => [
        ...current,
        { question: normalizedQuestion, response },
      ]);
      setAssistantQuestion("");
    } catch (error) {
      setWorkspaceNotice({
        level: "warning",
        message:
          error instanceof Error
            ? error.message
            : "Assistant request failed unexpectedly.",
      });
    } finally {
      setAssistantSending(false);
    }
  }

  async function handleAssistantSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    await submitAssistantQuestion(assistantQuestion);
  }

  async function handleAssistantFollowUp(question: string) {
    setAssistantQuestion(question);
    await submitAssistantQuestion(question);
  }

  function handleClearAssistantConversation() {
    setAssistantTurns([]);
    setAssistantQuestion("");
    setWorkspaceNotice({
      level: "info",
      message: analysisState
        ? `Cleared the assistant thread for ${analysisState.job_description.title || "the current workspace"}.`
        : "Cleared the assistant thread.",
    });
  }

  async function handleArtifactExport(
    artifactKind: WorkspaceArtifactKind,
    exportFormat: "markdown" | "pdf" | "zip",
  ) {
    if (!analysisState) {
      setWorkspaceNotice({
        level: "warning",
        message: "Run the workspace flow before exporting artifacts.",
      });
      return;
    }

    const exportKey = `${artifactKind}:${exportFormat}`;
    setArtifactExporting(exportKey);
    try {
      const response = await exportWorkspaceArtifact({
        workspace_snapshot: analysisState,
        artifact_kind: artifactKind,
        export_format: exportFormat,
        resume_theme: resumeTheme,
      });
      downloadBase64File(
        response.file_name,
        response.content_base64,
        response.mime_type,
      );
      setWorkspaceNotice({
        level: "success",
        message:
          artifactKind === "bundle"
            ? `Prepared the full application package as ${response.file_name}.`
            : `Prepared ${response.artifact_title} as ${response.file_name}.`,
      });
    } catch (error) {
      setWorkspaceNotice({
        level: "warning",
        message:
          error instanceof Error
            ? error.message
            : "Artifact export failed unexpectedly.",
      });
    } finally {
      setArtifactExporting(null);
    }
  }

  useEffect(() => {
    const workspaceSnapshot = analysisState;
    if (!workspaceSnapshot) {
      setArtifactPreviewHtml(null);
      setArtifactPreviewTitle(null);
      setArtifactPreviewLoading(false);
      return;
    }
    const resolvedWorkspaceSnapshot: WorkspaceAnalysisResponse = workspaceSnapshot;

    let cancelled = false;

    async function loadArtifactPreview() {
      setArtifactPreviewLoading(true);
      try {
        const response = await previewWorkspaceArtifact({
          workspace_snapshot: resolvedWorkspaceSnapshot,
          artifact_kind: currentArtifactKind,
          resume_theme: resumeTheme,
        });
        if (!cancelled) {
          setArtifactPreviewHtml(response.html);
          setArtifactPreviewTitle(response.artifact_title);
        }
      } catch (error) {
        if (!cancelled) {
          setArtifactPreviewHtml(null);
          setArtifactPreviewTitle(null);
          setWorkspaceNotice({
            level: "warning",
            message:
              error instanceof Error
                ? error.message
                : "Artifact preview could not be generated.",
          });
        }
      } finally {
        if (!cancelled) {
          setArtifactPreviewLoading(false);
        }
      }
    }

    void loadArtifactPreview();

    return () => {
      cancelled = true;
    };
  }, [analysisState, currentArtifactKind, resumeTheme]);

  function clearWorkspaceRole() {
    setActiveJob(null);
    setJobFileState(null);
    setManualJobText("");
    setAnalysisState(null);
    setResumeTheme("classic_ats");
    setArtifactExporting(null);
    setArtifactPreviewHtml(null);
    setArtifactPreviewTitle(null);
    setArtifactPreviewLoading(false);
    setWorkspaceNotice({
      level: "info",
      message: "Cleared the active role context. Load another role or paste a new JD.",
    });
  }

  useEffect(() => {
    if (
      authStatus !== "signed_in" ||
      !authTokens ||
      !authSession?.features.saved_workspace_enabled ||
      !analysisState ||
      workspaceSaveMeta ||
      autoSaving
    ) {
      return;
    }

    void persistLatestWorkspace(analysisState);
  }, [
    analysisState,
    authSession?.features.saved_workspace_enabled,
    authStatus,
    authTokens,
    autoSaving,
    workspaceSaveMeta,
  ]);

  return (
    <div className="workspace-layout">
      {sidebarCollapsed ? (
        <button
          aria-expanded={!sidebarCollapsed}
          aria-label="Open workspace drawer"
          className="workspace-drawer-toggle"
          onClick={() => setSidebarCollapsed(false)}
          type="button"
        >
          <span />
          <span />
          <span />
        </button>
      ) : null}

      {!sidebarCollapsed ? (
        <button
          aria-label="Close workspace drawer"
          className="workspace-drawer-backdrop"
          onClick={() => setSidebarCollapsed(true)}
          type="button"
        />
      ) : null}

      <aside
        className={
          sidebarCollapsed
            ? "workspace-sidebar workspace-sidebar-closed"
            : "workspace-sidebar workspace-sidebar-open"
        }
        aria-hidden={sidebarCollapsed}
      >
        <div className="workspace-sidebar-shell">
          <div className="workspace-sidebar-head">
            <div className="workspace-brand-lockup">
              <span className="workspace-brand-mark">AJ</span>
              <div>
                <p className="workspace-brand-title">Job Application Agent</p>
              </div>
            </div>

            <button
              aria-label="Close workspace drawer"
              className="workspace-sidebar-toggle workspace-sidebar-close"
              onClick={() => setSidebarCollapsed(true)}
              type="button"
            >
              <span />
              <span />
            </button>
          </div>

          <div className="workspace-sidebar-card">
                <h2 className="workspace-sidebar-title">
                  {authStatus === "signed_in" ? "Signed in to Google" : "Sign in with Google"}
                </h2>
                <div className="workspace-auth-panel">
                  <div className="workspace-auth-avatar">
                    {(authSession?.app_user.display_name || authSession?.app_user.email || "U")
                      .slice(0, 1)
                      .toUpperCase()}
                  </div>
                  <div>
                    <p className="workspace-auth-title">
                      {authStatus === "signed_in"
                        ? authSession?.app_user.display_name ||
                          authSession?.app_user.email ||
                          "Signed in"
                        : authStatus === "restoring"
                          ? "Restoring account session"
                          : "Signed out"}
                    </p>
                    <p className="workspace-auth-copy">
                      {authStatus === "signed_in"
                        ? `${authSession?.app_user.email || "Account session live"}${dailyQuota ? ` • ${formatRemainingCalls(dailyQuota)} runs left today` : ""}`
                        : authStatus === "restoring"
                          ? "Checking the last saved account session from this browser."
                          : ""}
                    </p>
                  </div>
                </div>
                {authError ? (
                  <div className="notice-panel notice-warning">{authError}</div>
                ) : null}
                {authStatus === "signed_in" ? (
                  <div className="workspace-sidebar-inline-metrics">
                    <span className="workspace-meta-chip">
                      Plan: {authSession?.app_user.plan_tier || "free"}
                    </span>
                    <span className="workspace-meta-chip">
                      Runs left: {formatRemainingCalls(dailyQuota)}
                    </span>
                    {workspaceSaveMeta ? (
                      <span className="workspace-meta-chip">
                        Saved until {formatUtcTimestamp(workspaceSaveMeta.expires_at)} UTC
                      </span>
                    ) : autoSaving ? (
                      <span className="workspace-meta-chip">Saving latest workspace...</span>
                    ) : null}
                  </div>
                ) : null}
                <div className="workspace-sidebar-actions">
                  {authStatus === "signed_in" ? (
                    <>
                      <button
                        className="primary-button workspace-button workspace-button-full"
                        disabled={
                          authActionLoading ||
                          workspaceReloading ||
                          !authSession?.features.saved_workspace_enabled
                        }
                        onClick={() => void handleReloadSavedWorkspace()}
                        type="button"
                      >
                        {workspaceReloading ? "Reloading..." : "Reload saved workspace"}
                      </button>
                      <button
                        className="secondary-button workspace-button workspace-button-full"
                        disabled={authActionLoading}
                        onClick={() => void handleSignOut()}
                        type="button"
                      >
                        {authActionLoading ? "Signing out..." : "Sign out"}
                      </button>
                    </>
                  ) : (
                    <button
                      className="primary-button workspace-button workspace-button-full"
                      disabled={authActionLoading || authStatus === "restoring"}
                      onClick={() => void handleGoogleSignIn()}
                      type="button"
                    >
                      {authStatus === "restoring"
                        ? "Restoring session..."
                        : authActionLoading
                          ? "Redirecting..."
                        : "Continue with Google"}
                    </button>
                  )}
                </div>
          </div>

          <div className="workspace-sidebar-card">
                <p className="eyebrow">Assistant</p>
                <h2 className="workspace-sidebar-title">
                  Ask your questions
                </h2>
                <div className="workspace-assistant-status">
                  <span className="workspace-assistant-status-label">Context</span>
                  <strong>{assistantStatusLabel}</strong>
                  <small>{assistantStatusCopy}</small>
                </div>

                {assistantTurns.length ? (
                  <div className="workspace-chat-history">
                    {assistantTurns.map((turn, index) => (
                      <div className="workspace-chat-turn" key={`${index}-${turn.question.slice(0, 18)}`}>
                        <div className="workspace-chat-bubble workspace-chat-user">
                          {turn.question}
                        </div>
                        <div className="workspace-chat-bubble workspace-chat-assistant">
                          {turn.response.answer}
                          {turn.response.sources.length ? (
                            <div className="workspace-chat-sources">
                              {turn.response.sources.map((source) => (
                                <span className="workspace-meta-chip" key={`${index}-${source}`}>
                                  {source}
                                </span>
                              ))}
                            </div>
                          ) : null}
                          {turn.response.suggested_follow_ups.length ? (
                            <div className="workspace-chat-followups">
                              {turn.response.suggested_follow_ups.map((followUp) => (
                                <button
                                  className="workspace-chat-followup"
                                  disabled={assistantSending}
                                  key={`${index}-${followUp}`}
                                  onClick={() => void handleAssistantFollowUp(followUp)}
                                  type="button"
                                >
                                  {followUp}
                                </button>
                              ))}
                            </div>
                          ) : null}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : !assistantRequiresWorkspaceRun ? (
                  <div className="workspace-empty-state workspace-empty-state-compact">
                    Ask about your fit, tailored resume, cover letter, report,
                    or the current package.
                  </div>
                ) : null}

                <form className="workspace-assistant-form" onSubmit={handleAssistantSubmit}>
                  <textarea
                    className="workspace-assistant-textarea"
                    disabled={assistantRequiresWorkspaceRun || assistantSending}
                    onChange={(event) => setAssistantQuestion(event.target.value)}
                    placeholder={
                      assistantRequiresWorkspaceRun
                        ? "Assistant unlocks after your first workspace run."
                        : "Ask about your fit, package, gaps, or the current outputs..."
                    }
                    value={assistantQuestion}
                  />
                  <div className="workspace-sidebar-actions">
                    <button
                      className="primary-button workspace-button workspace-button-full"
                      disabled={!assistantCanSubmit}
                      type="submit"
                    >
                      {assistantSending
                        ? "Sending..."
                        : assistantRequiresWorkspaceRun
                          ? "Awaiting workspace run"
                          : "Send to assistant"}
                    </button>
                    <button
                      className="secondary-button workspace-button workspace-button-full"
                      disabled={!assistantTurns.length}
                      onClick={handleClearAssistantConversation}
                      type="button"
                    >
                      Clear chat
                    </button>
                  </div>
                </form>
                {latestAssistantTurn?.response.suggested_follow_ups.length ? (
                  <div className="workspace-assistant-followup-panel">
                    <p className="workspace-label">Suggested next questions</p>
                    <div className="workspace-chat-followups">
                      {latestAssistantTurn.response.suggested_follow_ups.map((followUp) => (
                        <button
                          className="workspace-chat-followup"
                          disabled={assistantSending}
                          key={`latest-${followUp}`}
                          onClick={() => void handleAssistantFollowUp(followUp)}
                          type="button"
                        >
                          {followUp}
                        </button>
                      ))}
                    </div>
                  </div>
                ) : null}
          </div>

        </div>
      </aside>

      <div className="workspace-main">
        <section className="surface-card surface-card-neutral job-hero-panel">
          <div className="job-hero-grid">
            <div>
              <p className="eyebrow">Workspace</p>
              <h1 className="workspace-hero-title">
                Job Application Agent workspace
              </h1>
              <p className="workspace-hero-copy">
                Upload your resume, review job descriptions, run tailored
                application analysis, and generate ready-to-use resume, cover
                letter, and report outputs from one place.
              </p>
            </div>
          </div>

          <div className="workspace-hero-metrics workspace-hero-metrics-below">
            <div className="metric-tile workspace-hero-metric-tile">
              <span>Resume State</span>
              <strong>{currentProfile?.full_name || "Waiting for upload"}</strong>
              <small>{latestRole(currentProfile)}</small>
            </div>
            <div className="metric-tile workspace-hero-metric-tile">
              <span>Workflow Mode</span>
              <strong>{analysisState?.workflow.mode || "Not run yet"}</strong>
              <small>
                {analysisState
                  ? analysisState.workflow.assisted_requested
                    ? "AI-assisted analysis is ready to continue."
                    : "Preview results are ready to review."
                  : "Run preview or analysis after loading both inputs."}
              </small>
            </div>
            <div className="metric-tile workspace-hero-metric-tile">
              <span>Artifacts</span>
              <strong>{analysisState ? "Resume, cover letter, report" : "Pending"}</strong>
              <small>
                {analysisState
                  ? "Outputs are ready to review and export."
                  : "Artifacts appear after the workspace run finishes."}
              </small>
            </div>
          </div>
        </section>
        <section className="surface-card surface-card-neutral workspace-main-nav">
          <div className="workspace-main-nav-head">
            <div>
              <p className="eyebrow">Workspace flow</p>
              <h2 className="workspace-main-nav-title">{activeMainTabMeta.title}</h2>
              <p className="workspace-main-nav-copy">{activeMainTabMeta.copy}</p>
            </div>
            <span
              className={`workspace-main-tab-status workspace-main-tab-status-${activeMainTabMeta.tone}`}
            >
              {activeMainTabMeta.status}
            </span>
          </div>

          <div className="workspace-main-tabs" role="tablist" aria-label="Workspace steps">
            {workspaceTabs.map((tab) => (
              <button
                aria-selected={mainTab === tab.id}
                className={
                  mainTab === tab.id
                    ? "workspace-main-tab workspace-main-tab-active"
                    : "workspace-main-tab"
                }
                key={tab.id}
                onClick={() => setMainTab(tab.id)}
                role="tab"
                type="button"
              >
                <div className="workspace-main-tab-top">
                  <span className="workspace-main-tab-label">{tab.label}</span>
                  <span
                    className={`workspace-main-tab-status workspace-main-tab-status-${tab.tone}`}
                  >
                    {tab.status}
                  </span>
                </div>
                <p className="workspace-main-tab-note">{tab.copy}</p>
              </button>
            ))}
          </div>
        </section>

        {workspaceNotice ? (
          <div className={noticeClassName(workspaceNotice.level)}>
            {workspaceNotice.message}
          </div>
        ) : null}

        {mainTab === "resume" ? (
          <section className="workspace-section-stack">
            <article className="surface-card surface-card-neutral">
              <div className="section-head">
                <div>
                  <p className="eyebrow">Step 1</p>
                  <h2 className="section-title">Resume intake</h2>
                </div>
                <span className="status-chip">
                  {resumeState ? "Parsed" : "Waiting for upload"}
                </span>
              </div>
              <p className="section-copy">
                Upload your resume and let the backend parse it into a candidate
                snapshot that the rest of the workspace can reuse.
              </p>

              <div className="workspace-uploader">
                <label className="secondary-button workspace-button" htmlFor="resume-upload">
                  Choose resume file
                </label>
                <input
                  accept=".pdf,.docx,.txt"
                  className="workspace-hidden-input"
                  id="resume-upload"
                  onChange={(event) => {
                    const file = event.target.files?.[0] ?? null;
                    setSelectedResumeFile(file);
                    void handleResumeUpload(file);
                    event.target.value = "";
                  }}
                  type="file"
                />
                <span className="workspace-file-name">
                  {selectedResumeFile?.name ||
                    resumeState?.resume_document.filetype ||
                    "No resume selected"}
                </span>
                {resumeUploading ? (
                  <span className="workspace-file-status">Parsing resume...</span>
                ) : null}
              </div>

              {resumeNotice ? (
                <div className={noticeClassName(resumeNotice.level)}>
                  {resumeNotice.message}
                </div>
              ) : null}

              {currentProfile ? (
                <>
                  <div className="workspace-summary-grid">
                    <div className="metric-tile">
                      <span>Candidate</span>
                      <strong>{currentProfile.full_name || "Name not inferred"}</strong>
                      <small>{currentProfile.location || "Location not inferred"}</small>
                    </div>
                    <div className="metric-tile">
                      <span>Skills</span>
                      <strong>{currentProfile.skills.length}</strong>
                      <small>Matched skill signals from the parsed resume.</small>
                    </div>
                    <div className="metric-tile">
                      <span>Experience Entries</span>
                      <strong>{currentProfile.experience.length}</strong>
                      <small>Structured roles or project entries available for reuse.</small>
                    </div>
                  </div>

                  <div className="workspace-review-columns">
                    <div className="soft-panel">
                      <span className="soft-panel-label">Top skills</span>
                      <div className="workspace-chip-grid">
                        {currentProfile.skills.slice(0, 10).map((skill) => (
                          <span className="workspace-meta-chip" key={skill}>
                            {skill}
                          </span>
                        ))}
                      </div>
                    </div>
                    <div className="soft-panel">
                      <span className="soft-panel-label">Resume signals</span>
                      <ul className="workspace-feature-list workspace-feature-list-compact">
                        {currentProfile.source_signals.slice(0, 4).map((signal) => (
                          <li key={signal}>{signal}</li>
                        ))}
                      </ul>
                    </div>
                  </div>
                </>
              ) : (
                <div className="workspace-empty-state">
                  Your parsed candidate snapshot will appear here after the upload finishes.
                </div>
              )}
            </article>
          </section>
        ) : null}

        {mainTab === "jobs" ? (
          <>
            <section className="workspace-section-stack">
              <article className="surface-card surface-card-neutral">
                <div className="section-head">
                  <div>
                    <p className="eyebrow">Step 2</p>
                    <h2 className="section-title">Search roles, import postings, and build your shortlist</h2>
                  </div>
                  <span className="status-chip">Live search</span>
                </div>

                <form className="workspace-form-stack" onSubmit={handleSearch}>
                  <div className="workspace-field-grid workspace-field-grid-search">
                    <label className="workspace-field">
                      <span className="workspace-label">Search query</span>
                      <input
                        className="workspace-input"
                        onChange={(event) => setSearchQuery(event.target.value)}
                        placeholder="Machine learning engineer, product designer, data analyst..."
                        value={searchQuery}
                      />
                    </label>
                    <label className="workspace-field">
                      <span className="workspace-label">Preferred location</span>
                      <input
                        className="workspace-input"
                        onChange={(event) => setSearchLocation(event.target.value)}
                        placeholder="Bengaluru, Chennai, Remote..."
                        value={searchLocation}
                      />
                    </label>
                  </div>

                  <div className="workspace-search-toolbar">
                    <div className="workspace-search-filters">
                      <div className="workspace-search-filter-group">
                        <label className="workspace-toggle">
                          <input
                            checked={remoteOnly}
                            onChange={(event) => setRemoteOnly(event.target.checked)}
                            type="checkbox"
                          />
                          <span>Remote only</span>
                        </label>

                        <label className="workspace-select-field workspace-select-field-inline">
                          <span className="workspace-label workspace-label-inline">Posted within</span>
                          <select
                            className="workspace-select"
                            onChange={(event) => setPostedWithinDays(event.target.value)}
                            value={postedWithinDays}
                          >
                            <option value="">Any time</option>
                            <option value="3">Last 3 days</option>
                            <option value="7">Last 7 days</option>
                            <option value="14">Last 14 days</option>
                            <option value="30">Last 30 days</option>
                          </select>
                        </label>
                      </div>
                      <button
                        className="primary-button workspace-button"
                        disabled={searching}
                        type="submit"
                      >
                        {searching ? "Searching..." : "Search jobs"}
                      </button>
                    </div>
                  </div>
                </form>

                <form className="workspace-inline-import workspace-inline-import-split" onSubmit={handleResolveJob}>
                  <label className="workspace-field workspace-field-wide">
                    <span className="workspace-label">Import a job posting link</span>
                    <input
                      className="workspace-input"
                      onChange={(event) => setJobUrl(event.target.value)}
                      placeholder="Paste a Greenhouse or Lever job posting URL"
                      value={jobUrl}
                    />
                  </label>
                  <button
                    className="secondary-button workspace-button"
                    disabled={importing}
                    type="submit"
                  >
                    {importing ? "Importing..." : "Load into workspace"}
                  </button>
                </form>

                {searchNotice ? (
                  <div className={noticeClassName(searchNotice.level)}>
                    {searchNotice.message}
                  </div>
                ) : null}

                <div className="workspace-results-head">
                  <div>
                    <p className="workspace-label">Matching roles</p>
                  </div>
                  {searchResults ? (
                    <span className="status-chip">
                      {searchResults.total_results} result
                      {searchResults.total_results === 1 ? "" : "s"}
                    </span>
                  ) : null}
                </div>

                {searchResults?.results.length ? (
                  <div className="workspace-results-list">
                    {searchResults.results.map((job) => {
                      const isActive = activeJob?.id === job.id;
                      const isSaved = savedJobIds.has(job.id);
                      const isSaving = savedJobActionId === job.id;
                      return (
                        <article
                          className={isActive ? "job-result-card job-result-card-active" : "job-result-card"}
                          key={job.id}
                        >
                          <div className="job-result-head">
                            <div>
                              <h3>{job.title}</h3>
                              <p className="job-result-company">
                                {job.company} - {job.source}
                              </p>
                            </div>
                            {isSaved ? (
                              <span className="status-chip status-chip-live">Saved</span>
                            ) : null}
                          </div>

                          <div className="job-result-badges">
                            {buildJobResultBadges(job).map((badge) => (
                              <span className="workspace-meta-chip" key={`${job.id}-${badge}`}>
                                {badge}
                              </span>
                            ))}
                          </div>

                          <p className="job-result-summary">{resultPreview(job)}</p>

                          <div className="job-result-actions">
                            <button
                              className="secondary-button workspace-button workspace-button-small"
                              onClick={() => {
                                setActiveJob(job);
                                setMainTab("jd");
                              }}
                              type="button"
                            >
                              {isActive ? "Loaded" : "Review role"}
                            </button>
                            {job.url ? (
                              <a
                                className="secondary-button workspace-button workspace-button-small"
                                href={job.url}
                                rel="noreferrer"
                                target="_blank"
                              >
                                Open posting
                              </a>
                            ) : null}
                            {authStatus === "signed_in" && savedJobsEnabled ? (
                              <button
                                className="primary-button workspace-button workspace-button-small"
                                disabled={isSaving || isSaved}
                                onClick={() => void handleSaveJob(job)}
                                type="button"
                              >
                                {isSaving ? "Saving..." : isSaved ? "Saved" : "Save job"}
                              </button>
                            ) : null}
                          </div>
                        </article>
                      );
                    })}
                  </div>
                ) : (
                  <div className="workspace-empty-state">
                    Search for roles to load one into your workspace.
                  </div>
                )}

                <div className="workspace-saved-jobs-panel">
                  <div className="workspace-results-head">
                    <div>
                      <p className="workspace-label">Saved jobs</p>
                    </div>
                    {authStatus === "signed_in" && savedJobsEnabled ? (
                      <span className="status-chip">
                        {savedJobs.length} saved
                      </span>
                    ) : null}
                  </div>

                  {savedJobsNotice ? (
                    <div className={noticeClassName(savedJobsNotice.level)}>
                      {savedJobsNotice.message}
                    </div>
                  ) : null}

                  {authStatus !== "signed_in" ? (
                    <div className="workspace-empty-state">
                      Sign in with Google to save roles for later.
                    </div>
                  ) : !savedJobsEnabled ? (
                    <div className="workspace-empty-state">
                      Saved jobs are not available for this session.
                    </div>
                  ) : savedJobsLoading ? (
                    <div className="workspace-empty-state">
                      Loading your shortlist...
                    </div>
                  ) : savedJobs.length ? (
                    <>
                      <div className="workspace-summary-grid workspace-summary-grid-tight">
                        <div className="metric-tile">
                          <span>Saved Jobs</span>
                          <strong>{savedJobs.length}</strong>
                          <small>Your current account-backed shortlist.</small>
                        </div>
                        <div className="metric-tile">
                          <span>Latest Save</span>
                          <strong>{formatSavedLabel(latestSavedJobAt)}</strong>
                          <small>Most recent shortlist update for this signed-in account.</small>
                        </div>
                        <div className="metric-tile">
                          <span>Workspace Role</span>
                          <strong>{activeJob?.title || "No shortlisted role loaded"}</strong>
                          <small>
                            Load any saved role here to send it back into the review and analysis lane.
                          </small>
                        </div>
                      </div>

                      <div className="workspace-results-list">
                        {savedJobs.map((job) => {
                          const isActive = activeJob?.id === job.id;
                          const isRemoving = savedJobActionId === job.id;
                          return (
                            <article
                              className={isActive ? "job-result-card job-result-card-active" : "job-result-card"}
                              key={`saved-${job.id}`}
                            >
                              <div className="job-result-head">
                                <div>
                                  <h3>{job.title}</h3>
                                  <p className="job-result-company">
                                    {job.company} - {job.source}
                                  </p>
                                </div>
                                <span className="status-chip status-chip-live">
                                  {formatSavedLabel(job.saved_at ?? "")}
                                </span>
                              </div>

                              <div className="job-result-badges">
                                {buildJobResultBadges(job).map((badge) => (
                                  <span className="workspace-meta-chip" key={`saved-${job.id}-${badge}`}>
                                    {badge}
                                  </span>
                                ))}
                              </div>

                              <p className="job-result-summary">{resultPreview(job)}</p>

                              <div className="job-result-actions">
                                <button
                                  className="secondary-button workspace-button workspace-button-small"
                                  onClick={() => handleLoadSavedJob(job)}
                                  type="button"
                                >
                                  {isActive ? "Loaded" : "Load into workspace"}
                                </button>
                                {job.url ? (
                                  <a
                                    className="secondary-button workspace-button workspace-button-small"
                                    href={job.url}
                                    rel="noreferrer"
                                    target="_blank"
                                  >
                                    Open posting
                                  </a>
                                ) : null}
                                <button
                                  className="primary-button workspace-button workspace-button-small"
                                  disabled={isRemoving}
                                  onClick={() => void handleRemoveSavedJob(job)}
                                  type="button"
                                >
                                  {isRemoving ? "Removing..." : "Remove"}
                                </button>
                              </div>
                            </article>
                          );
                        })}
                      </div>
                    </>
                  ) : (
                    <div className="workspace-empty-state">
                      Save roles from search to build your shortlist.
                    </div>
                  )}
                </div>
              </article>
            </section>

            <section className="workspace-section-stack">
              <article className="surface-card surface-card-neutral">
                <div className="section-head">
                  <div>
                    <p className="eyebrow">Search Status</p>
                    <h2 className="section-title">Search and workspace status</h2>
                  </div>
                  <span
                    className={
                      health.status === "ready"
                        ? "status-chip status-chip-live"
                        : health.status === "error"
                          ? "status-chip status-chip-warning"
                          : "status-chip"
                    }
                  >
                    {health.status === "ready"
                      ? "Ready"
                      : health.status === "error"
                        ? "Needs attention"
                        : "Checking"}
                  </span>
                </div>

                <div className="workspace-summary-grid">
                  <div className="metric-tile workspace-status-tile">
                    <span>Search access</span>
                    <strong>
                      {health.status === "ready"
                        ? "Connected"
                        : health.status === "error"
                          ? "Unavailable"
                          : "Checking"}
                    </strong>
                    <small>
                      {health.status === "ready"
                        ? "Live job search is available right now."
                        : health.status === "error"
                          ? health.error
                          : "Checking your search connection now."}
                    </small>
                  </div>
                  <div className="metric-tile workspace-status-tile">
                    <span>Available sources</span>
                    <strong>
                      {health.status === "ready"
                        ? `${health.payload.providers.greenhouse.board_count + health.payload.providers.lever.site_count} sources ready`
                        : "Waiting for source counts"}
                    </strong>
                    <small>
                      {health.status === "ready"
                        ? `${health.payload.providers.greenhouse.board_count} board feeds and ${health.payload.providers.lever.site_count} company feeds are ready for search.`
                        : "Source counts will appear once the connection is ready."}
                    </small>
                  </div>
                  <div className="metric-tile workspace-status-tile">
                    <span>Current role</span>
                    <strong>{activeJob?.title || jobFileState?.job_description.title || "No role loaded"}</strong>
                    <small>
                      {activeJob
                        ? `${activeJob.company} - ${activeJob.location || "Location not specified"}`
                        : jobFileState
                          ? "Loaded from a parsed JD file."
                          : "Paste a JD or import a role to continue."}
                    </small>
                  </div>
                </div>

                {sourceCoverage ? (
                  <div className="workspace-summary-grid workspace-summary-grid-tight">
                    <div className="metric-tile workspace-status-tile">
                      <span>Sources checked</span>
                      <strong>{sourceCoverage.searched}</strong>
                      <small>Sources checked for your current search.</small>
                    </div>
                    <div className="metric-tile workspace-status-tile">
                      <span>Sources with matches</span>
                      <strong>{sourceCoverage.matched}</strong>
                      <small>Sources that returned at least one matching role.</small>
                    </div>
                    <div className="metric-tile workspace-status-tile">
                      <span>Unavailable</span>
                      <strong>{sourceCoverage.unavailable}</strong>
                      <small>Sources that did not respond during this search.</small>
                    </div>
                  </div>
                ) : null}
              </article>
            </section>
          </>
        ) : null}

        {mainTab === "jd" ? (
          <section className="workspace-section-grid">
            <article className="surface-card surface-card-neutral">
              <div className="section-head">
                <div>
                  <p className="eyebrow">Steps 3 and 4</p>
                  <h2 className="section-title">JD upload, manual input, and review</h2>
                </div>
                <span className="status-chip">
                  {review ? "Ready" : "Waiting for JD text"}
                </span>
              </div>
              <p className="section-copy">
                Paste a JD directly, load one from search, or upload a JD file. All three paths meet here.
              </p>

              <div className="workspace-uploader">
                <label className="secondary-button workspace-button" htmlFor="job-description-upload">
                  Choose JD file
                </label>
                <input
                  accept=".pdf,.docx,.txt"
                  className="workspace-hidden-input"
                  id="job-description-upload"
                  onChange={(event) => {
                    const file = event.target.files?.[0] ?? null;
                    setSelectedJobFile(file);
                    void handleJobDescriptionUpload(file);
                    event.target.value = "";
                  }}
                  type="file"
                />
                <span className="workspace-file-name">
                  {selectedJobFile?.name || jobFileState?.job_description.title || "No JD file selected"}
                </span>
                {jobFileUploading ? (
                  <span className="workspace-file-status">Parsing JD...</span>
                ) : null}
              </div>

              {jobFileNotice ? (
                <div className={noticeClassName(jobFileNotice.level)}>
                  {jobFileNotice.message}
                </div>
              ) : null}

              <textarea
                className="workspace-textarea"
                onChange={(event) => setManualJobText(event.target.value)}
                placeholder="Paste a job description here, or load one from the backend search/import lane."
                value={manualJobText}
              />
            </article>

            <article className="surface-card surface-card-neutral">
              <div className="section-head">
                <div>
                  <p className="eyebrow">Review lane</p>
                  <h2 className="section-title">Parsed JD summary</h2>
                </div>
                <span className="status-chip">
                  {activeJob
                    ? `Imported from ${activeJob.source}`
                    : jobFileState
                      ? "Uploaded file"
                      : review
                        ? "Manual JD"
                        : "Waiting"}
                </span>
              </div>

              {review ? (
                <>
                  <div className="workspace-summary-grid">
                    {review.summaryCards.map((card) => (
                      <div className="metric-tile" key={card.label}>
                        <span>{card.label}</span>
                        <strong>{card.value}</strong>
                        <small>{card.note}</small>
                      </div>
                    ))}
                  </div>

                  <div className="workspace-review-columns">
                    <div className="soft-panel">
                      <span className="soft-panel-label">Hard skills</span>
                      <div className="workspace-chip-grid">
                        {review.hardSkills.length ? (
                          review.hardSkills.map((skill) => (
                            <span className="workspace-meta-chip" key={skill}>
                              {skill}
                            </span>
                          ))
                        ) : (
                          <p className="workspace-muted-copy">
                            No explicit hard skills detected yet in the current text.
                          </p>
                        )}
                      </div>
                    </div>

                    <div className="soft-panel">
                      <span className="soft-panel-label">Soft skills</span>
                      <div className="workspace-chip-grid">
                        {review.softSkills.length ? (
                          review.softSkills.map((skill) => (
                            <span className="workspace-meta-chip" key={skill}>
                              {skill}
                            </span>
                          ))
                        ) : (
                          <p className="workspace-muted-copy">
                            No explicit soft-skill signals detected yet in the current text.
                          </p>
                        )}
                      </div>
                    </div>
                  </div>

                  {analysisState && !analysisIsStale ? (
                    <div className="workspace-section-stack">
                      {analysisState.jd_summary_view.sections.map((section) => (
                        <div className="workspace-section-card" key={section.title}>
                          <h3>{section.title}</h3>
                          <ul>
                            {section.items.map((item) => (
                              <li key={item}>{item}</li>
                            ))}
                          </ul>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="workspace-section-stack">
                      {review.summarySections.map((section) => (
                        <div className="workspace-section-card" key={section.title}>
                          <h3>{section.title}</h3>
                          <ul>
                            {section.items.map((item) => (
                              <li key={item}>{item}</li>
                            ))}
                          </ul>
                        </div>
                      ))}
                    </div>
                  )}
                </>
              ) : (
                <div className="workspace-empty-state">
                  Once a job description is present, this panel mirrors the review lane with summary cards, skills, and structured sections.
                </div>
              )}
            </article>
          </section>
        ) : null}

        {mainTab === "analysis" ? (
          <>
            <section className="surface-card surface-card-neutral">
              <div className="section-head">
                <div>
                  <p className="eyebrow">Run</p>
                  <h2 className="section-title">Build the workspace package</h2>
                </div>
                <span className="status-chip">
                  {analysisState ? analysisState.workflow.mode : "Not run yet"}
                </span>
              </div>
              <p className="section-copy">
                Build the deterministic preview first or run the agentic workflow through the backend.
              </p>

              <div className="workspace-run-actions">
                <button
                  className="secondary-button workspace-button"
                  disabled={analysisLoading}
                  onClick={() => void handleRunAnalysis(false)}
                  type="button"
                >
                  {analysisLoading ? "Working..." : "Build preview"}
                </button>
                <button
                  className="primary-button workspace-button"
                  disabled={analysisLoading}
                  onClick={() => void handleRunAnalysis(true)}
                  type="button"
                >
                  {analysisLoading ? "Running..." : "Run agentic analysis"}
                </button>
                <button
                  className="secondary-button workspace-button"
                  onClick={clearWorkspaceRole}
                  type="button"
                >
                  Clear active role
                </button>
              </div>

              {analysisLoading && currentWorkflowStage ? (
                <div
                  className={`workspace-progress-card workspace-progress-tone-${workflowProgressTone(
                    currentWorkflowStage.title,
                  )}`}
                >
                  <div className="workspace-progress-head">
                    <span className="workspace-progress-tag">
                      {currentWorkflowStage.title}
                    </span>
                    <span className="workspace-progress-percent">
                      {currentWorkflowStage.value}%
                    </span>
                  </div>
                  <p className="workspace-progress-detail">
                    {currentWorkflowStage.detail}
                  </p>
                  <div
                    aria-hidden="true"
                    className="workspace-progress-bar"
                  >
                    <span
                      style={{ width: `${currentWorkflowStage.value}%` }}
                    />
                  </div>
                  <div className="workspace-progress-stage-list">
                    {workflowStages.map((stage, index) => {
                      const state = toneForStage(
                        index === analysisProgressIndex,
                        index < analysisProgressIndex,
                      );
                      return (
                        <div
                          className={`workspace-progress-stage workspace-progress-stage-${state}`}
                          key={`${stage.title}-${stage.value}`}
                        >
                          <span className="workspace-progress-stage-title">
                            {stage.title}
                          </span>
                          <small>{stage.detail}</small>
                        </div>
                      );
                    })}
                  </div>
                  <p className="workspace-muted-copy workspace-progress-note">
                    This mirrors the old workspace crew panel from Streamlit. The stage feed is client-side guidance for the in-flight run while the backend finishes the request.
                  </p>
                </div>
              ) : null}

              {analysisIsStale ? (
                <div className="notice-panel notice-warning">
                  The inputs changed after the last run. Re-run the preview or agentic analysis to refresh the workspace outputs.
                </div>
              ) : null}

              {analysisState ? (
                <>
                  <div className="workspace-summary-grid">
                    <div className="metric-tile">
                      <span>Fit score</span>
                      <strong>{analysisState.fit_analysis.overall_score}/100</strong>
                      <small>{analysisState.fit_analysis.readiness_label}</small>
                    </div>
                    <div className="metric-tile">
                      <span>Matched hard skills</span>
                      <strong>{analysisState.fit_analysis.matched_hard_skills.length}</strong>
                      <small>
                        {analysisState.fit_analysis.matched_hard_skills.slice(0, 4).join(", ") || "No strong hard-skill overlap yet"}
                      </small>
                    </div>
                    <div className="metric-tile">
                      <span>Review</span>
                      <strong>
                        {analysisState.workflow.review_approved
                          ? "Approved"
                          : analysisState.workflow.assisted_requested
                            ? "Needs review"
                            : "Preview only"}
                      </strong>
                      <small>
                        {analysisState.workflow.fallback_reason || "Artifacts below reflect the latest workspace run."}
                      </small>
                    </div>
                  </div>

                  <div className="workspace-review-columns">
                    <div className="soft-panel">
                      <span className="soft-panel-label">Strengths</span>
                      <ul className="workspace-feature-list workspace-feature-list-compact">
                        {analysisState.fit_analysis.strengths.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </div>
                    <div className="soft-panel">
                      <span className="soft-panel-label">Gaps</span>
                      <ul className="workspace-feature-list workspace-feature-list-compact">
                        {analysisState.fit_analysis.gaps.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </div>
                  </div>

                  {analysisState.agent_result ? (
                    <div className="workspace-section-card">
                      <h3>Agentic strategy highlights</h3>
                      <p className="workspace-muted-copy">
                        {analysisState.agent_result.fit.fit_summary ||
                          analysisState.artifacts.report.summary}
                      </p>
                      {analysisState.agent_result.strategy?.recruiter_positioning ? (
                        <p className="workspace-muted-copy">
                          {analysisState.agent_result.strategy.recruiter_positioning}
                        </p>
                      ) : null}
                    </div>
                  ) : (
                    <div className="workspace-section-card">
                      <h3>Deterministic draft guidance</h3>
                      <ul>
                        {analysisState.tailored_draft.gap_mitigation_steps.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </>
              ) : (
                <div className="workspace-empty-state">
                  The fit snapshot, draft guidance, and artifacts appear here after the first run.
                </div>
              )}
            </section>

            <section className="surface-card surface-card-neutral">
              <div className="section-head">
                <div>
                  <p className="eyebrow">Outputs</p>
                  <h2 className="section-title">Artifacts and exports</h2>
                </div>
                <span className="status-chip">
                  {analysisState ? "Ready to review" : "Waiting for run"}
                </span>
              </div>
              <p className="section-copy">
                Review the current artifact, switch the resume export theme, and download markdown, PDF, or the full package bundle from the backend.
              </p>

              {analysisState ? (
                <>
                  <div className="workspace-tab-row">
                    {(["resume", "cover-letter", "report"] as ArtifactTab[]).map((tab) => (
                      <button
                        className={artifactTab === tab ? "inspector-tab inspector-tab-active" : "inspector-tab"}
                        key={tab}
                        onClick={() => setArtifactTab(tab)}
                        type="button"
                      >
                        {renderArtifactTitle(tab)}
                      </button>
                    ))}
                  </div>

                  {currentArtifact ? (
                    <div className="workspace-artifact-panel">
                      <div className="workspace-artifact-head">
                        <div>
                          <p className="workspace-label">Current artifact</p>
                          <h3 className="workspace-role-title">{currentArtifact.title}</h3>
                          <p className="workspace-role-copy">{currentArtifact.summary}</p>
                        </div>
                        <div className="workspace-artifact-actions">
                          <button
                            className="secondary-button workspace-button workspace-button-small"
                            disabled={artifactExporting !== null}
                            onClick={() =>
                              void handleArtifactExport(currentArtifactKind, "markdown")
                            }
                            type="button"
                          >
                            {artifactExporting === `${currentArtifactKind}:markdown`
                              ? "Preparing..."
                              : "Download Markdown"}
                          </button>
                          <button
                            className="secondary-button workspace-button workspace-button-small"
                            disabled={artifactExporting !== null}
                            onClick={() =>
                              void handleArtifactExport(currentArtifactKind, "pdf")
                            }
                            type="button"
                          >
                            {artifactExporting === `${currentArtifactKind}:pdf`
                              ? "Preparing..."
                              : "Download PDF"}
                          </button>
                          <button
                            className="primary-button workspace-button workspace-button-small"
                            disabled={artifactExporting !== null}
                            onClick={() => void handleArtifactExport("bundle", "zip")}
                            type="button"
                          >
                            {artifactExporting === "bundle:zip"
                              ? "Preparing..."
                              : "Download Package (.zip)"}
                          </button>
                        </div>
                      </div>

                      {artifactTab === "resume" ? (
                        <>
                          <div className="workspace-section-card">
                            <h3>Resume theme</h3>
                            <p className="workspace-muted-copy">
                              Choose which export style you want the backend to package for the tailored resume.
                            </p>
                            <div className="workspace-tab-row">
                              {(Object.entries(RESUME_THEME_OPTIONS) as Array<
                                [ResumeTheme, { label: string; tagline: string }]
                              >).map(([themeKey, themeMeta]) => (
                                <button
                                  className={
                                    resumeTheme === themeKey
                                      ? "inspector-tab inspector-tab-active"
                                      : "inspector-tab"
                                  }
                                  key={themeKey}
                                  onClick={() => setResumeTheme(themeKey)}
                                  type="button"
                                >
                                  {themeMeta.label}
                                </button>
                              ))}
                            </div>
                            <p className="workspace-muted-copy">
                              {RESUME_THEME_OPTIONS[resumeTheme].tagline}
                            </p>
                          </div>

                          <div className="workspace-review-columns">
                            <div className="soft-panel">
                              <span className="soft-panel-label">Highlighted skills</span>
                              <div className="workspace-chip-grid">
                                {analysisState.artifacts.tailored_resume.highlighted_skills.map((skill) => (
                                  <span className="workspace-meta-chip" key={skill}>
                                    {skill}
                                  </span>
                                ))}
                              </div>
                            </div>
                            <div className="soft-panel">
                              <span className="soft-panel-label">Validation notes</span>
                              <ul className="workspace-feature-list workspace-feature-list-compact">
                                {analysisState.artifacts.tailored_resume.validation_notes.map((note) => (
                                  <li key={note}>{note}</li>
                                ))}
                              </ul>
                            </div>
                          </div>

                          <div className="soft-panel">
                            <span className="soft-panel-label">Change summary</span>
                            <ul className="workspace-feature-list workspace-feature-list-compact">
                              {analysisState.artifacts.tailored_resume.change_log.map((note) => (
                                <li key={note}>{note}</li>
                              ))}
                            </ul>
                          </div>
                        </>
                      ) : null}

                      <div className="workspace-section-card">
                        <h3>Artifact preview</h3>
                        <p className="workspace-muted-copy">
                          {artifactPreviewTitle
                            ? `Backend-rendered preview for ${artifactPreviewTitle}.`
                            : "The backend HTML preview will appear here once it is ready."}
                        </p>
                        {artifactPreviewLoading ? (
                          <div className="workspace-empty-state">
                            Preparing the artifact preview...
                          </div>
                        ) : artifactPreviewHtml ? (
                          <iframe
                            className="workspace-artifact-preview-frame"
                            srcDoc={artifactPreviewHtml}
                            title={`${renderArtifactTitle(artifactTab)} preview`}
                          />
                        ) : (
                          <div className="workspace-empty-state">
                            The artifact preview is temporarily unavailable, but the download actions still work.
                          </div>
                        )}
                      </div>

                      <pre className="workspace-artifact-copy">{currentArtifact.plain_text}</pre>
                    </div>
                  ) : null}
                </>
              ) : (
                <div className="workspace-empty-state">
                  The tailored resume, cover letter, and application report will appear here after the workspace run.
                </div>
              )}
            </section>
          </>
        ) : null}
      </div>
    </div>
  );
}
