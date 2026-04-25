"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import {
  askWorkspaceAssistant,
  commitResumeBuilderResume,
  exchangeGoogleCode,
  exportWorkspaceArtifact,
  generateResumeBuilderResume,
  getWorkspaceAnalysisJob,
  loadLatestResumeBuilderSession,
  loadSavedJobs,
  loadSavedWorkspace,
  previewWorkspaceArtifact,
  removeSavedJob,
  resolveJobUrl,
  restoreAuthSession,
  saveSavedJob,
  saveWorkspaceSnapshot,
  searchJobs,
  sendResumeBuilderMessage,
  signOutAuthSession,
  startWorkspaceAnalysisJob,
  startResumeBuilderSession,
  startGoogleSignIn,
  updateResumeBuilderDraft,
  uploadJobDescriptionFile,
  uploadResumeFile,
} from "@/lib/api";
import type {
  AuthSessionResponse,
  AuthTokens,
  CandidateProfile,
  DailyQuotaStatus,
  JobPosting,
  JobResolveResponse,
  JobSearchResponse,
  LoadSavedWorkspaceResponse,
  ResumeBuilderSessionResponse,
  SavedWorkspaceMeta,
  WorkspaceAnalysisJobStatusResponse,
  WorkspaceAnalysisResponse,
  WorkspaceArtifactKind,
  WorkspaceJobDescriptionUploadResponse,
  WorkspaceResumeUploadResponse,
} from "@/lib/api-types";
import {
  buildJobResultBadges,
  buildJobReview,
} from "@/lib/job-workspace";
import {
  buildAuthRedirectUrl,
  clearAuthQueryParams,
  clearStoredAuthTokens,
  persistAuthTokens,
  readStoredAuthTokens,
} from "@/lib/auth-session";
import {
  ArtifactMetricIcon,
  ResumeMetricIcon,
  WorkflowMetricIcon,
} from "@/components/workspace/icons";
import {
  AssistantPanel,
  type AssistantTurn,
} from "@/components/workspace/AssistantPanel";
import { Sidebar } from "@/components/workspace/Sidebar";

type Notice = {
  level: "info" | "success" | "warning";
  message: string;
} | null;

type ArtifactTab = "resume" | "cover-letter";
type WorkspaceMainTab = "resume" | "jobs" | "jd" | "analysis";
type ResumeIntakeMode = "upload" | "assistant";

type AuthStatus = "loading" | "restoring" | "signed_out" | "signed_in";

type WorkflowRunMode = "preview" | "agentic";
type WorkflowStage = {
  title: string;
  detail: string;
  value: number;
};

const ASSISTANT_HISTORY_STORAGE_KEY = "workspace-assistant-history-v1";
const MAX_PERSISTED_ASSISTANT_TURNS = 8;
const RESUME_BUILDER_STEP_LABELS: Record<string, string> = {
  basics: "Basics",
  role: "Target role",
  experience: "Experience",
  education: "Education",
  skills: "Skills",
  review: "Review",
};
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
    title: "Gatekeeper agent",
    detail: "Reviewing the drafted outputs and applying grounded corrections.",
    value: 63,
  },
  {
    title: "Builder agent",
    detail: "Packaging the final tailored resume and lining up the finish.",
    value: 84,
  },
  {
    title: "Cover letter agent",
    detail: "Turning the approved story into a role-specific cover letter that is ready to send.",
    value: 97,
  },
];

type AnalysisJobState = WorkspaceAnalysisJobStatusResponse | null;

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

function normalizeSectionSentence(value: string) {
  const cleaned = value.replace(/\s+/g, " ").replace(/^[\-\u2022•\s]+/, "").trim();
  if (!cleaned) {
    return "";
  }
  if (/^(key|listed above\.?)$/i.test(cleaned)) {
    return "";
  }
  if (!/[.!?]$/.test(cleaned) && cleaned.length > 18) {
    return `${cleaned}.`;
  }
  return cleaned;
}

function buildSectionParagraphs(items: string[]) {
  const sentences = items
    .flatMap((item) =>
      item
        .split(/(?<=[.!?])\s+/)
        .map(normalizeSectionSentence)
        .filter(Boolean),
    )
    .filter((sentence, index, all) => all.indexOf(sentence) === index);

  if (!sentences.length) {
    return [];
  }

  const paragraphs: string[] = [];
  let current = "";

  for (const sentence of sentences) {
    const next = current ? `${current} ${sentence}` : sentence;
    if (next.length > 420 && current) {
      paragraphs.push(current);
      current = sentence;
      continue;
    }
    current = next;
  }

  if (current) {
    paragraphs.push(current);
  }

  return paragraphs.slice(0, 4);
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
  return "Cover Letter";
}

function artifactKindFromTab(tab: ArtifactTab): Exclude<WorkspaceArtifactKind, "bundle" | "report"> {
  if (tab === "resume") {
    return "tailored_resume";
  }
  return "cover_letter";
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

function getInitialMainTab(): WorkspaceMainTab {
  if (typeof window === "undefined") {
    return "resume";
  }

  const tabParam = new URLSearchParams(window.location.search).get("tab");
  if (tabParam === "resume" || tabParam === "jobs" || tabParam === "jd" || tabParam === "analysis") {
    return tabParam;
  }

  const hashTab = window.location.hash.replace(/^#/, "");
  if (hashTab === "resume" || hashTab === "jobs" || hashTab === "jd" || hashTab === "analysis") {
    return hashTab;
  }

  return "resume";
}

export function JobApplicationWorkspace() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(getInitialSidebarCollapsed);
  const [mainTab, setMainTab] = useState<WorkspaceMainTab>(getInitialMainTab);
  const [authStatus, setAuthStatus] = useState<AuthStatus>("loading");
  const [authSession, setAuthSession] = useState<AuthSessionResponse | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [authActionLoading, setAuthActionLoading] = useState(false);
  const [accountMenuOpen, setAccountMenuOpen] = useState(false);
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
  const [searchResultsCollapsed, setSearchResultsCollapsed] = useState(false);
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
  const [resumeIntakeMode, setResumeIntakeMode] =
    useState<ResumeIntakeMode>("upload");
  const [resumeBuilderSession, setResumeBuilderSession] =
    useState<ResumeBuilderSessionResponse | null>(null);
  const [resumeBuilderAnswer, setResumeBuilderAnswer] = useState("");
  const [resumeBuilderLoading, setResumeBuilderLoading] = useState(false);
  const [resumeBuilderGenerating, setResumeBuilderGenerating] = useState(false);
  const [resumeBuilderCommitting, setResumeBuilderCommitting] = useState(false);
  const [resumeBuilderNotice, setResumeBuilderNotice] = useState<Notice>(null);
  const [resumeBuilderInitialized, setResumeBuilderInitialized] = useState(false);
  const [resumeBuilderEditing, setResumeBuilderEditing] = useState(false);
  const [resumeBuilderCollapsed, setResumeBuilderCollapsed] = useState(false);
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
  const [analysisLoading, setAnalysisLoading] = useState(false);
  const [analysisRunMode, setAnalysisRunMode] = useState<WorkflowRunMode | null>(null);
  const [analysisJobState, setAnalysisJobState] = useState<AnalysisJobState>(null);
  const [analysisState, setAnalysisState] =
    useState<WorkspaceAnalysisResponse | null>(null);
  const [artifactTab, setArtifactTab] = useState<ArtifactTab>("resume");
  const [artifactExporting, setArtifactExporting] = useState<string | null>(null);
  const [artifactPreviewHtml, setArtifactPreviewHtml] = useState<string | null>(null);
  const [artifactPreviewTitle, setArtifactPreviewTitle] = useState<string | null>(null);
  const [artifactPreviewLoading, setArtifactPreviewLoading] = useState(false);

  const [assistantQuestion, setAssistantQuestion] = useState("");
  const [assistantSending, setAssistantSending] = useState(false);
  const [assistantTurns, setAssistantTurns] = useState<AssistantTurn[]>([]);

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
            buildAuthRedirectUrl("/workspace"),
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

  useEffect(() => {
    if (activeJob || jobFileState) {
      setJobInputCollapsed(true);
    }
  }, [activeJob, jobFileState]);

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
  const resumeBuilderStepLabel = resumeBuilderSession
    ? RESUME_BUILDER_STEP_LABELS[resumeBuilderSession.current_step] ?? "Resume builder"
    : "Resume builder";
  const review = manualJobText.trim()
    ? buildJobReview(manualJobText, activeJob)
    : null;

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
      return {
        ...analysisState.artifacts.tailored_resume,
        theme: "classic_ats",
        summary: `Tailored resume draft for ${
          analysisState.job_description.title || "the target role"
        }, ready to review and export.`,
      };
    }
    return analysisState.artifacts.cover_letter;
  }, [analysisState, artifactTab]);
  const currentArtifactKind = artifactKindFromTab(artifactTab);
  const workflowStages = useMemo(() => {
    if (analysisRunMode === "agentic") {
      return AGENTIC_WORKFLOW_STAGES;
    }
    return [] as WorkflowStage[];
  }, [analysisRunMode]);
  const currentWorkflowStage = useMemo(() => {
    if (!analysisLoading || analysisRunMode !== "agentic") {
      return null;
    }
    if (!analysisJobState?.stage_title) {
      return workflowStages[0] ?? null;
    }
    return (
      workflowStages.find((stage) => stage.title === analysisJobState.stage_title) ?? {
        title: analysisJobState.stage_title,
        detail:
          analysisJobState.stage_detail ||
          "The workspace crew is moving through the run.",
        value: analysisJobState.progress_percent || 3,
      }
    );
  }, [analysisJobState, analysisLoading, analysisRunMode, workflowStages]);
  const workspaceTabs = useMemo(
    () => [
      {
        id: "resume" as const,
        label: "Resume",
        title: "Upload profile",
        copy:
          "Upload your resume or build one with the assistant so the app can use your background throughout the workflow.",
        status: currentProfile ? "Ready" : "Start here",
        tone: currentProfile ? "live" : "ready",
      },
      {
        id: "jobs" as const,
        label: "Job Search",
        title: "Search job",
        copy:
          "Find a job from the live listings, paste a job link, or open one from your saved jobs.",
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
        title: "Review the job description",
        copy:
          "Add the job description and review the key skills, requirements, and summary.",
        status: review ? "JD ready" : manualJobText.trim() ? "Drafting" : "Add a JD",
        tone: review ? "live" : manualJobText.trim() ? "ready" : "idle",
      },
      {
        id: "analysis" as const,
        label: "Analysis & Outputs",
        title: "Run the workflow",
        copy:
          "Trigger the agentic workflow, then review your tailored documents and export them.",
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
  const accountMenuRef = useRef<HTMLDivElement | null>(null);
  const accountDisplayName =
    authSession?.app_user.display_name || authSession?.app_user.email || "Signed in";
  const accountInitial = accountDisplayName.slice(0, 1).toUpperCase();

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
    if (!resumeBuilderSession) {
      return;
    }

    setResumeBuilderDraftForm({
      full_name: resumeBuilderSession.draft_profile.full_name || "",
      location: resumeBuilderSession.draft_profile.location || "",
      contact_lines: resumeBuilderSession.draft_profile.contact_lines.join("\n"),
      target_role: resumeBuilderSession.draft_profile.target_role || "",
      professional_summary:
        resumeBuilderSession.draft_profile.professional_summary || "",
      experience_notes: resumeBuilderSession.draft_profile.experience_notes || "",
      education_notes: resumeBuilderSession.draft_profile.education_notes || "",
      skills: resumeBuilderSession.draft_profile.skills.join(", "),
      certifications: resumeBuilderSession.draft_profile.certifications.join(", "),
    });
  }, [resumeBuilderSession]);

  useEffect(() => {
    if (
      !analysisLoading ||
      analysisRunMode !== "agentic" ||
      !analysisJobState?.job_id ||
      analysisJobState.status === "completed" ||
      analysisJobState.status === "failed"
    ) {
      return;
    }

    let cancelled = false;

    const timeout = window.setTimeout(async () => {
      try {
        const nextJobState = await getWorkspaceAnalysisJob(
          analysisJobState.job_id,
          authTokens,
        );
        if (cancelled) {
          return;
        }

        setAnalysisJobState(nextJobState);

        if (nextJobState.status === "completed" && nextJobState.result) {
          setAnalysisState(nextJobState.result);
          setArtifactTab("resume");
          setMainTab("analysis");
          setArtifactPreviewHtml(null);
          setArtifactPreviewTitle(null);
          const savedWorkspace = await persistLatestWorkspace(nextJobState.result);
          if (!cancelled) {
            setWorkspaceNotice({
              level: "success",
              message: savedWorkspace
                ? `Workflow finished in ${nextJobState.result.workflow.mode} mode and saved workspace refreshes until ${formatUtcTimestamp(savedWorkspace.expires_at)} UTC.`
                : `Workflow finished in ${nextJobState.result.workflow.mode} mode.`,
            });
            setAnalysisLoading(false);
            setAnalysisRunMode(null);
          }
          return;
        }

        if (nextJobState.status === "failed") {
          setWorkspaceNotice({
            level: "warning",
            message:
              nextJobState.error_message ||
              "The agentic workflow failed unexpectedly.",
          });
          setAnalysisLoading(false);
          setAnalysisRunMode(null);
          return;
        }
      } catch (error) {
        if (!cancelled) {
          setWorkspaceNotice({
            level: "warning",
            message:
              error instanceof Error
                ? error.message
                : "Workflow status polling failed unexpectedly.",
          });
          setAnalysisLoading(false);
          setAnalysisRunMode(null);
        }
      }
    }, 1200);

    return () => {
      cancelled = true;
      window.clearTimeout(timeout);
    };
  }, [analysisJobState, analysisLoading, analysisRunMode, authTokens]);

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
      setSearchResultsCollapsed(false);
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
      message: "Job description cleared. You can upload a new file, paste a JD, or load another role.",
    });
    setJobInputCollapsed(false);
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
    setArtifactPreviewHtml(null);
    setArtifactPreviewTitle(null);
    setAssistantTurns([]);
    setResumeIntakeMode("upload");
    setResumeBuilderSession(null);
    setResumeBuilderInitialized(false);
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
      const response = await startResumeBuilderSession(authTokens);
      setResumeBuilderSession(response);
      setResumeBuilderInitialized(true);
      setResumeBuilderNotice({
        level: "success",
        message: "The guided resume builder is ready. Answer each prompt and we will build your base resume together.",
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
    setResumeBuilderLoading(true);
    setResumeBuilderNotice({
      level: "info",
      message: authTokens
        ? "Checking for your latest resume-builder draft..."
        : "Starting the guided resume builder...",
    });

    try {
      if (authTokens) {
        try {
          const latest = await loadLatestResumeBuilderSession(authTokens);
          if (latest.session) {
            setResumeBuilderSession(latest.session);
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

      const response = await startResumeBuilderSession(authTokens);
      setResumeBuilderSession(response);
      setResumeBuilderNotice({
        level: "success",
        message: "The guided resume builder is ready. Answer each prompt and we will build your base resume together.",
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

    try {
      const response = await sendResumeBuilderMessage(
        resumeBuilderSession.session_id,
        resumeBuilderAnswer.trim(),
        authTokens,
      );
      setResumeBuilderSession(response);
      setResumeBuilderAnswer("");
      setResumeBuilderNotice({
        level: "success",
        message: response.assistant_message,
      });
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
        message: "Start the guided resume builder before generating a base resume.",
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
        authTokens,
      );
      setResumeBuilderSession(response);
      setResumeBuilderNotice({
        level: "success",
        message: "Your base resume draft is ready. Review it, then use this profile to continue into the workspace.",
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
    if (!resumeBuilderSession) {
      return;
    }

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
        authTokens,
      );
      setResumeBuilderSession(response);
      setResumeBuilderNotice({
        level: "success",
        message: "Draft updated. You can keep refining it or generate the base resume.",
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
        authTokens,
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
        message: "Your base resume is now the active profile for the rest of the workflow.",
      });
      setSelectedResumeFile(null);
      setResumeBuilderSession(null);
      setResumeBuilderInitialized(false);
      setResumeBuilderAnswer("");
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

  async function handleGoogleSignIn() {
    setAuthActionLoading(true);
    setAuthError(null);
    try {
      const response = await startGoogleSignIn(buildAuthRedirectUrl("/workspace"));
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
      setResumeBuilderSession(null);
      setResumeBuilderInitialized(false);
      setResumeBuilderAnswer("");
      setResumeBuilderNotice(null);
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

  async function handleRunAnalysis() {
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

    if (!authTokens) {
      setWorkspaceNotice({
        level: "warning",
        message: "Sign in with Google before running the AI-assisted workflow.",
      });
      return;
    }

    setAnalysisRunMode("agentic");
    setAnalysisJobState({
      job_id: "",
      status: "queued",
      stage_title: "Workflow crew",
      stage_detail: "Opening your application brief and preparing the first agent.",
      progress_percent: 3,
      result: null,
      error_message: null,
    });
    setAnalysisLoading(true);
    setWorkspaceNotice({
      level: "info",
      message:
        "Running the agentic workflow now. The workspace crew will keep you posted as each stage moves.",
    });

    try {
      const response = await startWorkspaceAnalysisJob({
        resume_text: resumeText,
        resume_filetype: activeResumeState?.resume_document.filetype ?? "TXT",
        resume_source: activeResumeState?.resume_document.source ?? "workspace",
        job_description_text: manualJobText.trim(),
        imported_job_posting: activeJob,
        run_assisted: true,
      }, authTokens);
      setAnalysisJobState({
        ...response,
        result: null,
        error_message: null,
      });
    } catch (error) {
      const errorMessage =
        error instanceof Error
          ? error.message
          : "Workspace analysis failed unexpectedly.";
      setWorkspaceNotice({
        level: "warning",
        message: errorMessage,
      });
      setAnalysisLoading(false);
      setAnalysisRunMode(null);
      setAnalysisJobState(null);
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
        message: "Run the AI analysis first so the assistant has grounded context to use.",
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
        resume_theme: "classic_ats",
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
          resume_theme: "classic_ats",
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
  }, [analysisState, currentArtifactKind]);

  function clearWorkspaceRole() {
    setActiveJob(null);
    setJobFileState(null);
    setManualJobText("");
    setAnalysisState(null);
    setAnalysisJobState(null);
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

  useEffect(() => {
    if (!accountMenuOpen) {
      return;
    }

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

  return (
    <div className="workspace-layout">
      <Sidebar collapsed={sidebarCollapsed} onCollapse={setSidebarCollapsed}>
        <AssistantPanel
          turns={assistantTurns}
          requiresWorkspaceRun={assistantRequiresWorkspaceRun}
          question={assistantQuestion}
          onQuestionChange={setAssistantQuestion}
          sending={assistantSending}
          canSubmit={assistantCanSubmit}
          onSubmit={handleAssistantSubmit}
          onClearConversation={handleClearAssistantConversation}
        />
      </Sidebar>

      <div className="workspace-main">
        <div className="workspace-main-topbar">
          <div className="workspace-main-topbar-actions">
            {authStatus === "signed_in" ? (
              <div className="workspace-account-menu" ref={accountMenuRef}>
                <button
                  aria-expanded={accountMenuOpen}
                  aria-haspopup="menu"
                  className="workspace-account-trigger"
                  onClick={() => setAccountMenuOpen((open) => !open)}
                  type="button"
                >
                  <span className="workspace-account-trigger-avatar">{accountInitial}</span>
                </button>
                {accountMenuOpen ? (
                  <div className="workspace-account-popover" role="menu">
                    <div className="workspace-auth-panel workspace-auth-panel-inline">
                      <div className="workspace-auth-avatar">{accountInitial}</div>
                      <div>
                        <p className="workspace-auth-title">{accountDisplayName}</p>
                        <p className="workspace-auth-copy">
                          {authSession?.app_user.email || "Account session live"}
                        </p>
                      </div>
                    </div>
                    <div className="workspace-sidebar-inline-metrics workspace-account-metrics">
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
                    {authError ? <div className="notice-panel notice-warning">{authError}</div> : null}
                    <div className="workspace-sidebar-actions workspace-account-actions">
                      {authSession?.features.saved_workspace_enabled ? (
                        <button
                          className="primary-button workspace-button workspace-button-full"
                          disabled={authActionLoading || workspaceReloading}
                          onClick={() => void handleReloadSavedWorkspace()}
                          type="button"
                        >
                          {workspaceReloading ? "Reloading..." : "Reload saved workspace"}
                        </button>
                      ) : null}
                      <button
                        className="secondary-button workspace-button workspace-button-full"
                        disabled={authActionLoading}
                        onClick={() => void handleSignOut()}
                        type="button"
                      >
                        {authActionLoading ? "Signing out..." : "Sign out"}
                      </button>
                    </div>
                  </div>
                ) : null}
              </div>
            ) : (
              <button
                className="secondary-button workspace-button workspace-topbar-button"
                disabled={authActionLoading || authStatus === "restoring"}
                onClick={() => void handleGoogleSignIn()}
                type="button"
              >
                {authStatus === "restoring"
                  ? "Restoring session..."
                  : authActionLoading
                    ? "Redirecting..."
                    : "Sign in with Google"}
              </button>
            )}
          </div>
        </div>

        <section className="surface-card surface-card-neutral job-hero-panel">
          <div className="job-hero-grid">
            <div>
              <p className="eyebrow">Workspace</p>
              <h1 className="workspace-hero-title">
                Job Application Copilot
              </h1>
              <p className="workspace-hero-copy">
                Upload your resume, review job descriptions, run tailored
                  application analysis, and generate ready-to-use resume, cover
                letter outputs from one place.
                </p>
              </div>
            </div>
        </section>

        <div className="workspace-hero-metrics workspace-hero-metrics-outside">
            <div className="metric-tile workspace-hero-metric-tile">
              <div className="workspace-hero-metric-head">
                <span className="workspace-hero-metric-icon" aria-hidden="true">
                  <ResumeMetricIcon />
                </span>
                <span>Resume State</span>
              </div>
              <strong>{currentProfile?.full_name || "Waiting for upload"}</strong>
              <small>{latestRole(currentProfile)}</small>
            </div>
            <div className="metric-tile workspace-hero-metric-tile">
              <div className="workspace-hero-metric-head">
                <span className="workspace-hero-metric-icon" aria-hidden="true">
                  <WorkflowMetricIcon />
                </span>
                <span>Workflow Mode</span>
              </div>
              <strong>{analysisState?.workflow.mode || "Not run yet"}</strong>
                <small>
                  {analysisState
                    ? analysisState.workflow.assisted_requested
                      ? "AI-assisted analysis is ready to continue."
                      : "Loaded from an older non-assisted run."
                    : "Run the AI analysis after loading both inputs."}
                </small>
              </div>
            <div className="metric-tile workspace-hero-metric-tile">
              <div className="workspace-hero-metric-head">
                <span className="workspace-hero-metric-icon" aria-hidden="true">
                  <ArtifactMetricIcon />
                </span>
                <span>Artifacts</span>
              </div>
                <strong>{analysisState ? "Resume and cover letter" : "Pending"}</strong>
                <small>
                  {analysisState
                    ? "Outputs are ready to review and export."
                  : "Artifacts appear after the workspace run finishes."}
              </small>
            </div>
        </div>
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
                  {resumeState ? "Ready" : "Start here"}
                </span>
              </div>
                <p className="section-copy">
                  Bring in an existing resume or build a base one with the assistant.
                </p>

              <div className="workspace-tab-row">
                {(["upload", "assistant"] as ResumeIntakeMode[]).map((mode) => (
                  <button
                    className={
                      resumeIntakeMode === mode
                        ? "inspector-tab inspector-tab-active"
                        : "inspector-tab"
                    }
                    key={mode}
                    onClick={() => {
                      setResumeIntakeMode(mode);
                      if (mode === "assistant") {
                        setResumeBuilderInitialized(false);
                      }
                    }}
                    type="button"
                  >
                    {mode === "upload" ? "Upload Resume" : "Build With Assistant"}
                  </button>
                ))}
              </div>

              {resumeIntakeMode === "upload" ? (
                <>
                  <div className="workspace-uploader">
                    <label className="primary-button workspace-button workspace-upload-trigger" htmlFor="resume-upload">
                      Upload resume
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
                    {currentProfile ? (
                      <button
                        className="danger-button workspace-button workspace-action-end"
                        onClick={handleClearUploadedResumeProfile}
                        type="button"
                      >
                        Clear uploaded resume
                      </button>
                    ) : null}
                  </div>

                  {resumeNotice ? (
                    <div className={noticeClassName(resumeNotice.level)}>
                      {resumeNotice.message}
                    </div>
                  ) : null}
                </>
              ) : (
                <>
                  <div className="workspace-builder-stack">
                    <div className="workspace-section-card">
                      <div className="section-head">
                        <div>
                          <span className="workspace-label">Resume builder assistant</span>
                          <h3>{resumeBuilderStepLabel}</h3>
                        </div>
                        <button
                          className="secondary-button workspace-button workspace-button-small"
                          onClick={() =>
                            setResumeBuilderCollapsed((current) => !current)
                          }
                          type="button"
                        >
                          {resumeBuilderCollapsed ? "Show builder" : "Hide builder"}
                        </button>
                      </div>

                      {!resumeBuilderCollapsed ? (
                        <>
                          <p className="workspace-role-copy">
                            {resumeBuilderSession?.assistant_message ||
                              "The guided assistant will ask a few focused questions and turn your answers into a base resume."}
                          </p>

                          {authStatus === "signed_in" ? (
                            <p className="workspace-muted-copy">
                              Your latest draft will reopen here automatically when available.
                            </p>
                          ) : null}

                          {resumeBuilderSession ? (
                            <div className="workspace-chip-grid">
                              {Object.entries(RESUME_BUILDER_STEP_LABELS).map(([key, label]) => {
                                const isActive = resumeBuilderSession.current_step === key;
                                const isComplete =
                                  key !== "review" &&
                                  resumeBuilderSession.completed_steps >
                                    Object.keys(RESUME_BUILDER_STEP_LABELS).indexOf(key);
                                return (
                                  <span
                                    className={isActive ? "workspace-meta-chip workspace-builder-chip-active" : "workspace-meta-chip"}
                                    key={key}
                                  >
                                    {label}
                                    {isComplete && !isActive ? " - Done" : ""}
                                  </span>
                                );
                              })}
                            </div>
                          ) : null}

                          {resumeBuilderNotice ? (
                            <div className={noticeClassName(resumeBuilderNotice.level)}>
                              {resumeBuilderNotice.message}
                            </div>
                          ) : null}

                          {!resumeBuilderSession && resumeBuilderLoading ? (
                            <div className="workspace-empty-state">
                              Starting the guided resume builder...
                            </div>
                          ) : null}

                          {resumeBuilderSession && !resumeBuilderSession.ready_to_generate ? (
                            <div className="workspace-form-stack">
                              <textarea
                                className="workspace-textarea workspace-builder-answer"
                                onChange={(event) => setResumeBuilderAnswer(event.target.value)}
                                placeholder="Type your answer here. Keep it natural - the assistant will structure it for you."
                                value={resumeBuilderAnswer}
                              />
                              <div className="workspace-run-actions">
                                <button
                                  className="primary-button workspace-button"
                                  disabled={resumeBuilderLoading}
                                  onClick={() => void handleResumeBuilderAnswer()}
                                  type="button"
                                >
                                  {resumeBuilderLoading ? "Saving..." : "Continue"}
                                </button>
                              </div>
                            </div>
                          ) : null}

                          {resumeBuilderSession?.ready_to_generate &&
                          !resumeBuilderSession.generated_resume_markdown ? (
                            <div className="workspace-run-actions">
                              <button
                                className="primary-button workspace-button"
                                disabled={resumeBuilderGenerating}
                                onClick={() => void handleResumeBuilderGenerate()}
                                type="button"
                              >
                                {resumeBuilderGenerating ? "Generating..." : "Generate Base Resume"}
                              </button>
                            </div>
                          ) : null}

                          {resumeBuilderSession?.generated_resume_markdown ? (
                            <div className="workspace-run-actions">
                              <button
                                className="primary-button workspace-button"
                                disabled={resumeBuilderCommitting}
                                onClick={() => void handleResumeBuilderCommit()}
                                type="button"
                              >
                                {resumeBuilderCommitting ? "Using profile..." : "Use This Profile"}
                              </button>
                            </div>
                          ) : null}
                        </>
                      ) : (
                        <p className="workspace-muted-copy workspace-builder-collapsed-copy">
                          The assistant is hidden for now. You can reopen it anytime to continue answering questions.
                        </p>
                      )}
                    </div>

                    <div className="workspace-section-card">
                      <span className="workspace-label">Draft profile</span>
                      <h3>
                        {resumeBuilderSession?.draft_profile.full_name ||
                          "Your base resume will build here"}
                      </h3>
                      <p className="workspace-role-copy">
                        {resumeBuilderSession?.generated_resume_markdown
                          ? "Review the generated base resume before moving it into the workspace."
                          : "As you answer each prompt, the assistant will collect the details needed to create a clean starting resume."}
                      </p>

                      {resumeBuilderSession ? (
                        <>
                          <div className="workspace-summary-grid">
                            <div className="metric-tile">
                              <span>Target role</span>
                              <strong>
                                {resumeBuilderSession.draft_profile.target_role || "Still collecting"}
                              </strong>
                              <small>The role direction you want this base resume to support.</small>
                            </div>
                            <div className="metric-tile">
                              <span>Skills</span>
                              <strong>{resumeBuilderSession.draft_profile.skills.length}</strong>
                              <small>Skills or tools confirmed so far.</small>
                            </div>
                            <div className="metric-tile">
                              <span>Progress</span>
                              <strong>{resumeBuilderSession.progress_percent}%</strong>
                              <small>{resumeBuilderSession.status === "ready" ? "Base resume generated." : "Guided intake in progress."}</small>
                            </div>
                          </div>

                          <div className="workspace-review-columns">
                            <div className="soft-panel">
                              <span className="soft-panel-label">Contact</span>
                              <ul className="workspace-feature-list workspace-feature-list-compact">
                                {resumeBuilderSession.draft_profile.contact_lines.length ? (
                                  resumeBuilderSession.draft_profile.contact_lines.map((line) => (
                                    <li key={line}>{line}</li>
                                  ))
                                ) : (
                                  <li>Add your email, phone, and links in the basics step.</li>
                                )}
                              </ul>
                            </div>
                            <div className="soft-panel">
                              <span className="soft-panel-label">Skills</span>
                              <div className="workspace-chip-grid">
                                {resumeBuilderSession.draft_profile.skills.length ? (
                                  resumeBuilderSession.draft_profile.skills.map((skill) => (
                                    <span className="workspace-meta-chip" key={skill}>
                                      {skill}
                                    </span>
                                  ))
                                ) : (
                                  <p className="workspace-muted-copy">
                                    Skills will appear here once you reach that step.
                                  </p>
                                )}
                              </div>
                            </div>
                          </div>

                          <div className="workspace-form-stack workspace-builder-edit-grid">
                            <label className="workspace-field">
                              <span className="workspace-label">Full name</span>
                              <input
                                className="workspace-input"
                                onChange={(event) =>
                                  setResumeBuilderDraftForm((current) => ({
                                    ...current,
                                    full_name: event.target.value,
                                  }))
                                }
                                value={resumeBuilderDraftForm.full_name}
                              />
                            </label>
                            <label className="workspace-field">
                              <span className="workspace-label">Location</span>
                              <input
                                className="workspace-input"
                                onChange={(event) =>
                                  setResumeBuilderDraftForm((current) => ({
                                    ...current,
                                    location: event.target.value,
                                  }))
                                }
                                value={resumeBuilderDraftForm.location}
                              />
                            </label>
                            <label className="workspace-field">
                              <span className="workspace-label">Target role</span>
                              <input
                                className="workspace-input"
                                onChange={(event) =>
                                  setResumeBuilderDraftForm((current) => ({
                                    ...current,
                                    target_role: event.target.value,
                                  }))
                                }
                                value={resumeBuilderDraftForm.target_role}
                              />
                            </label>
                            <label className="workspace-field workspace-builder-field-wide">
                              <span className="workspace-label">Contact lines</span>
                              <textarea
                                className="workspace-textarea workspace-builder-compact-textarea"
                                onChange={(event) =>
                                  setResumeBuilderDraftForm((current) => ({
                                    ...current,
                                    contact_lines: event.target.value,
                                  }))
                                }
                                placeholder="One line per item: email, phone, LinkedIn, GitHub..."
                                value={resumeBuilderDraftForm.contact_lines}
                              />
                            </label>
                            <label className="workspace-field workspace-builder-field-wide">
                              <span className="workspace-label">Summary</span>
                              <textarea
                                className="workspace-textarea workspace-builder-compact-textarea"
                                onChange={(event) =>
                                  setResumeBuilderDraftForm((current) => ({
                                    ...current,
                                    professional_summary: event.target.value,
                                  }))
                                }
                                value={resumeBuilderDraftForm.professional_summary}
                              />
                            </label>
                            <label className="workspace-field workspace-builder-field-wide">
                              <span className="workspace-label">Experience notes</span>
                              <textarea
                                className="workspace-textarea workspace-builder-compact-textarea"
                                onChange={(event) =>
                                  setResumeBuilderDraftForm((current) => ({
                                    ...current,
                                    experience_notes: event.target.value,
                                  }))
                                }
                                value={resumeBuilderDraftForm.experience_notes}
                              />
                            </label>
                            <label className="workspace-field workspace-builder-field-wide">
                              <span className="workspace-label">Education</span>
                              <textarea
                                className="workspace-textarea workspace-builder-compact-textarea"
                                onChange={(event) =>
                                  setResumeBuilderDraftForm((current) => ({
                                    ...current,
                                    education_notes: event.target.value,
                                  }))
                                }
                                value={resumeBuilderDraftForm.education_notes}
                              />
                            </label>
                            <label className="workspace-field">
                              <span className="workspace-label">Skills</span>
                              <input
                                className="workspace-input"
                                onChange={(event) =>
                                  setResumeBuilderDraftForm((current) => ({
                                    ...current,
                                    skills: event.target.value,
                                  }))
                                }
                                placeholder="Python, FastAPI, Docker, SQL"
                                value={resumeBuilderDraftForm.skills}
                              />
                            </label>
                            <label className="workspace-field">
                              <span className="workspace-label">Certifications</span>
                              <input
                                className="workspace-input"
                                onChange={(event) =>
                                  setResumeBuilderDraftForm((current) => ({
                                    ...current,
                                    certifications: event.target.value,
                                  }))
                                }
                                placeholder="Optional"
                                value={resumeBuilderDraftForm.certifications}
                              />
                            </label>
                          </div>

                          <div className="workspace-run-actions">
                            <button
                              className="secondary-button workspace-button"
                              disabled={resumeBuilderEditing}
                              onClick={() => void handleResumeBuilderDraftSave()}
                              type="button"
                            >
                              {resumeBuilderEditing ? "Saving edits..." : "Save Draft Edits"}
                            </button>
                          </div>

                          {resumeBuilderSession.generated_resume_markdown ? (
                            <div className="workspace-section-card workspace-builder-preview-card">
                              <span className="workspace-label">Base resume preview</span>
                              <pre className="workspace-builder-preview">
                                {resumeBuilderSession.generated_resume_markdown}
                              </pre>
                            </div>
                          ) : (
                            <div className="workspace-empty-state workspace-empty-state-compact">
                              Your base resume preview will appear here once the guided intake is complete.
                            </div>
                          )}
                        </>
                      ) : (
                        <div className="workspace-empty-state workspace-empty-state-compact">
                          Switch to the assistant lane to start building a resume from scratch.
                        </div>
                      )}
                    </div>
                  </div>
                </>
              )}

              {resumeIntakeMode === "upload" && currentProfile ? (
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

                  <div className="workspace-next-step-note">
                    You can proceed to Job Search if you want help finding roles, or move to the JD section if you already have a job description ready.
                  </div>
                </>
              ) : resumeIntakeMode === "upload" ? (
                <div className="workspace-empty-state">
                  Your parsed candidate snapshot will appear here after the upload finishes.
                </div>
              ) : null}
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
                      <span className="workspace-label">Keywords</span>
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
                        className="primary-button workspace-button workspace-action-button"
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
                    <span className="workspace-label">Job posting link</span>
                    <input
                      className="workspace-input"
                      onChange={(event) => setJobUrl(event.target.value)}
                      placeholder="Paste a Greenhouse or Lever job posting URL"
                      value={jobUrl}
                    />
                  </label>
                  <button
                    className="primary-button workspace-button workspace-action-button"
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
                    <div className="workspace-results-head-actions">
                      <span className="status-chip">
                        {searchResults.total_results} result
                        {searchResults.total_results === 1 ? "" : "s"}
                      </span>
                      {searchResults.results.length ? (
                        <button
                          className="secondary-button workspace-button workspace-button-small"
                          onClick={() =>
                            setSearchResultsCollapsed((current) => !current)
                          }
                          type="button"
                        >
                          {searchResultsCollapsed ? "Show results" : "Hide results"}
                        </button>
                      ) : null}
                    </div>
                  ) : null}
                </div>

                {searchResults?.results.length ? (
                  searchResultsCollapsed ? (
                    <div className="workspace-empty-state workspace-empty-state-compact">
                      Search results are collapsed. Expand them again whenever you want to review roles from this search.
                    </div>
                  ) : (
                  <div className="workspace-results-list workspace-saved-jobs-list">
                    {searchResults.results.map((job) => {
                      const isActive = activeJob?.id === job.id;
                      const isSaved = savedJobIds.has(job.id);
                      const isSaving = savedJobActionId === job.id;
                      return (
                        <article
                          className={
                            isActive
                              ? "job-result-card workspace-saved-job-card workspace-result-tile job-result-card-active"
                              : "job-result-card workspace-saved-job-card workspace-result-tile"
                          }
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
                            {authStatus === "signed_in" ? (
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
                  )
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
                        <div className="metric-tile workspace-status-tile">
                          <span>Saved Jobs</span>
                          <strong>{savedJobs.length}</strong>
                          <small>Your current account-backed shortlist.</small>
                        </div>
                        <div className="metric-tile workspace-status-tile">
                          <span>Latest Save</span>
                          <strong>{formatSavedLabel(latestSavedJobAt)}</strong>
                          <small>Most recent shortlist update for this signed-in account.</small>
                        </div>
                        <div className="metric-tile workspace-status-tile">
                          <span>Workspace Role</span>
                          <strong>{activeJob?.title || "No shortlisted role loaded"}</strong>
                          <small>
                            Load any saved role here to send it back into the review and analysis lane.
                          </small>
                        </div>
                      </div>

                      <div className="workspace-results-list workspace-saved-jobs-list">
                        {savedJobs.map((job) => {
                          const isActive = activeJob?.id === job.id;
                          const isRemoving = savedJobActionId === job.id;
                          return (
                            <article
                              className={
                                isActive
                                  ? "job-result-card workspace-saved-job-card workspace-result-tile job-result-card-active"
                                  : "job-result-card workspace-saved-job-card workspace-result-tile"
                              }
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

          </>
        ) : null}

        {mainTab === "jd" ? (
          <section className="surface-card surface-card-neutral">
              <div className="section-head">
                <div>
                  <p className="eyebrow">Step 3</p>
                  <h2 className="section-title">JD upload, manual input, and review</h2>
                </div>
                <div className="section-head-actions">
                  <span className="status-chip">
                    {review ? "Ready" : "Waiting for JD text"}
                  </span>
                  {review ? (
                    <button
                      className="secondary-button workspace-button workspace-button-small"
                      onClick={() => setJobInputCollapsed((current) => !current)}
                      type="button"
                    >
                      {jobInputCollapsed ? "Show JD input" : "Hide JD input"}
                    </button>
                  ) : null}
                </div>
              </div>
              <p className="section-copy">
                Paste a JD directly, load one from search, or upload a JD file. All three paths meet here.
              </p>

              {!jobInputCollapsed ? (
                <div className="workspace-jd-stack">
                  <div className="workspace-jd-load-panel">
                    <div className="workspace-uploader">
                      <label className="primary-button workspace-button" htmlFor="job-description-upload">
                        Upload JD
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
                      {(jobFileState || activeJob || manualJobText.trim()) ? (
                        <button
                          className="danger-button workspace-button workspace-action-end"
                          onClick={handleClearLoadedJobDescription}
                          type="button"
                        >
                          Clear uploaded JD
                        </button>
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
                      placeholder="Paste a job description here, or load one from job search."
                      value={manualJobText}
                    />
                  </div>
                </div>
              ) : null}

              <div className="workspace-jd-stack">
                <div className="workspace-section-card">
                  <div className="section-head">
                <div>
                  <p className="eyebrow">Review lane</p>
                  <h2 className="section-title">JD summary</h2>
                </div>
                    <span className="status-chip">
                      {activeJob
                        ? `Imported from ${activeJob.source}`
                        : jobFileState
                          ? "Ready"
                          : review
                            ? "Ready"
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
                        <div className="workspace-section-stack workspace-jd-sections">
                          {analysisState.jd_summary_view.sections.map((section) => (
                            <div className="workspace-section-card workspace-jd-section-card" key={section.title}>
                              <h3>{section.title}</h3>
                              <div className="workspace-jd-paragraphs">
                                {buildSectionParagraphs(section.items).map((paragraph) => (
                                  <p key={paragraph}>{paragraph}</p>
                                ))}
                              </div>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <div className="workspace-section-stack workspace-jd-sections">
                          {review.summarySections.map((section) => (
                            <div className="workspace-section-card workspace-jd-section-card" key={section.title}>
                              <h3>{section.title}</h3>
                              <div className="workspace-jd-paragraphs">
                                {buildSectionParagraphs(section.items).map((paragraph) => (
                                  <p key={paragraph}>{paragraph}</p>
                                ))}
                              </div>
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
                </div>
              </div>
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
                  Run the agentic workflow once your resume and job description are ready.
                </p>

                <div className="workspace-run-actions">
                  <button
                    className="primary-button workspace-button"
                    disabled={analysisLoading}
                    onClick={() => void handleRunAnalysis()}
                    type="button"
                  >
                    {analysisLoading ? "Running..." : "Run workflow"}
                </button>
                <button
                  className="danger-button workspace-button workspace-action-end"
                  onClick={clearWorkspaceRole}
                  type="button"
                >
                  Clear role
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
                      {analysisJobState?.progress_percent ?? currentWorkflowStage.value}%
                    </span>
                  </div>
                  <p className="workspace-progress-detail">
                    {analysisJobState?.stage_detail ?? currentWorkflowStage.detail}
                  </p>
                  <div
                    aria-hidden="true"
                    className="workspace-progress-bar"
                  >
                    <span
                      style={{ width: `${analysisJobState?.progress_percent ?? currentWorkflowStage.value}%` }}
                    />
                  </div>
                  <div className="workspace-progress-stage-list">
                    <div className="workspace-progress-stage workspace-progress-stage-live">
                      <span className="workspace-progress-stage-title">
                        {currentWorkflowStage.title}
                      </span>
                      <small>{analysisJobState?.stage_detail ?? currentWorkflowStage.detail}</small>
                    </div>
                  </div>
                  <p className="workspace-muted-copy workspace-progress-note">
                    This card now follows the real backend stage instead of stepping forward on a timer.
                  </p>
                </div>
              ) : null}

              {analysisIsStale ? (
                <div className="notice-panel notice-warning">
                  The inputs changed after the last run. Re-run the workflow to refresh your documents.
                </div>
              ) : null}

              {analysisState ? (
                <></>
              ) : (
                <div className="workspace-empty-state">
                  Run the workflow once to unlock your tailored documents.
                </div>
              )}
            </section>

            <section className="surface-card surface-card-neutral">
              <div className="section-head">
                <div>
                  <p className="eyebrow">Outputs</p>
                  <h2 className="section-title">Documents</h2>
                </div>
                <span className="status-chip">
                  {analysisState ? "Ready to review" : "Waiting for run"}
                </span>
              </div>
              <p className="section-copy">
                Review and download your documents.
              </p>

              {analysisState ? (
                  <>
                    <div className="workspace-tab-row">
                    {(["resume", "cover-letter"] as ArtifactTab[]).map((tab) => (
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
                          <p className="workspace-label">Current document</p>
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
                        </div>
                      </div>

                      <div className="workspace-section-card">
                        <h3>Preview</h3>
                        <p className="workspace-muted-copy">
                          {artifactPreviewTitle
                            ? `Preview of ${artifactPreviewTitle}.`
                            : "A preview of the current document will appear here once it is ready."}
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
                    </div>
                  ) : null}
                </>
                ) : (
                  <div className="workspace-empty-state">
                  The tailored resume and cover letter will appear here after the workflow runs.
                  </div>
                )}
              </section>
          </>
        ) : null}
      </div>
    </div>
  );
}
