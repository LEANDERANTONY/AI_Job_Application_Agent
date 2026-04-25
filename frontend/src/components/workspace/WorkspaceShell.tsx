"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import {
  askWorkspaceAssistant,
  commitResumeBuilderResume,
  generateResumeBuilderResume,
  loadLatestResumeBuilderSession,
  resolveJobUrl,
  searchJobs,
  sendResumeBuilderMessage,
  startResumeBuilderSession,
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
  WorkspaceAnalysisResponse,
  WorkspaceJobDescriptionUploadResponse,
  WorkspaceResumeUploadResponse,
} from "@/lib/api-types";
import {
  buildJobResultBadges,
  buildJobReview,
} from "@/lib/job-workspace";
import {
  ArtifactMetricIcon,
  ResumeMetricIcon,
  WorkflowMetricIcon,
} from "@/components/workspace/icons";
import {
  AssistantPanel,
  type AssistantTurn,
} from "@/components/workspace/AssistantPanel";
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
import { Sidebar } from "@/components/workspace/Sidebar";
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

function noticeClassName(level: NonNullable<Notice>["level"]) {
  if (level === "success") {
    return "notice-panel notice-success";
  }
  if (level === "warning") {
    return "notice-panel notice-warning";
  }
  return "notice-panel notice-info";
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

export function WorkspaceShell() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(getInitialSidebarCollapsed);
  const [mainTab, setMainTab] = useState<WorkspaceMainTab>(getInitialMainTab);
  const [accountMenuOpen, setAccountMenuOpen] = useState(false);
  const [workspaceNotice, setWorkspaceNotice] = useState<Notice>(null);

  const {
    authStatus,
    authSession,
    setAuthSession,
    authError,
    authActionLoading,
    workspaceSaveMeta,
    setWorkspaceSaveMeta,
    workspaceReloading,
    autoSaving,
    authTokens,
    dailyQuota,
    signIn: handleGoogleSignIn,
    signOutAuth,
    persistLatestWorkspace,
    reloadSavedWorkspace,
  } = useWorkspaceSession({ setNotice: setWorkspaceNotice });

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

  const [jobUrl, setJobUrl] = useState("");
  const [importing, setImporting] = useState(false);
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
    currentArtifactKind,
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
  } = useSavedJobs({ authStatus, authTokens, authSession });

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
    setAnalysisJobState,
    currentWorkflowStage,
    runAnalysis: handleRunAnalysis,
    resetAnalysis,
  } = useAnalysisJob({
    resumeText,
    jobDescriptionText: manualJobText,
    resumeFiletype: activeResumeState?.resume_document.filetype,
    resumeSource: activeResumeState?.resume_document.source,
    importedJobPosting: activeJob,
    authTokens,
    setNotice: setWorkspaceNotice,
    setAnalysisState,
    onCompleted: onAnalysisCompleted,
  });

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

  const assistantRequiresWorkspaceRun = !analysisState;
  const assistantCanSubmit =
    !assistantRequiresWorkspaceRun &&
    !assistantSending &&
    Boolean(assistantQuestion.trim());

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
    resetArtifacts();
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

  // Sign-out wraps the hook's auth-only `signOutAuth` with cross-slice
  // resets (saved jobs, resume builder fields) that the hook can't
  // reach into.
  async function handleSignOut() {
    await signOutAuth();
    resetSavedJobs();
    setResumeBuilderSession(null);
    setResumeBuilderInitialized(false);
    setResumeBuilderAnswer("");
    setResumeBuilderNotice(null);
  }

  // Reload-saved-workspace wraps the hook's `reloadSavedWorkspace` to
  // apply the returned snapshot across the shell's other slices and
  // surface the success notice.
  async function handleReloadSavedWorkspace() {
    const result = await reloadSavedWorkspace();
    if (result.kind !== "snapshot") {
      return;
    }
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

  function clearWorkspaceRole() {
    setActiveJob(null);
    setJobFileState(null);
    setManualJobText("");
    setAnalysisState(null);
    resetAnalysis();
    resetArtifacts();
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
    <div className="workspace-shell">
      <div className="workspace-shell-inner">
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
          <ResumeIntake
            mode={resumeIntakeMode}
            onModeChange={setResumeIntakeMode}
            onResetBuilderInitialized={() => setResumeBuilderInitialized(false)}
            selectedResumeFile={selectedResumeFile}
            onSelectedResumeFileChange={setSelectedResumeFile}
            onResumeUpload={(file) => void handleResumeUpload(file)}
            resumeUploading={resumeUploading}
            resumeState={resumeState}
            resumeNotice={resumeNotice}
            currentProfile={currentProfile}
            onClearUploadedResumeProfile={handleClearUploadedResumeProfile}
            authSignedIn={authStatus === "signed_in"}
            builderSession={resumeBuilderSession}
            builderCollapsed={resumeBuilderCollapsed}
            onToggleBuilderCollapsed={() =>
              setResumeBuilderCollapsed((current) => !current)
            }
            builderAnswer={resumeBuilderAnswer}
            onBuilderAnswerChange={setResumeBuilderAnswer}
            builderNotice={resumeBuilderNotice}
            builderLoading={resumeBuilderLoading}
            builderGenerating={resumeBuilderGenerating}
            builderCommitting={resumeBuilderCommitting}
            builderEditing={resumeBuilderEditing}
            builderDraftForm={resumeBuilderDraftForm}
            setBuilderDraftForm={setResumeBuilderDraftForm}
            onBuilderAnswerSubmit={() => void handleResumeBuilderAnswer()}
            onBuilderGenerate={() => void handleResumeBuilderGenerate()}
            onBuilderCommit={() => void handleResumeBuilderCommit()}
            onBuilderDraftSave={() => void handleResumeBuilderDraftSave()}
          />
        ) : null}

        {mainTab === "jobs" ? (
          <JobSearch
            searchQuery={searchQuery}
            onSearchQueryChange={setSearchQuery}
            searchLocation={searchLocation}
            onSearchLocationChange={setSearchLocation}
            remoteOnly={remoteOnly}
            onRemoteOnlyChange={setRemoteOnly}
            postedWithinDays={postedWithinDays}
            onPostedWithinDaysChange={setPostedWithinDays}
            searching={searching}
            onSearchSubmit={handleSearch}
            jobUrl={jobUrl}
            onJobUrlChange={setJobUrl}
            importing={importing}
            onImportSubmit={handleResolveJob}
            searchNotice={searchNotice}
            searchResults={searchResults}
            searchResultsCollapsed={searchResultsCollapsed}
            onToggleSearchResultsCollapsed={() =>
              setSearchResultsCollapsed((current) => !current)
            }
            savedJobIds={savedJobIds}
            savedJobActionId={savedJobActionId}
            activeJob={activeJob}
            onReviewRole={(job) => {
              setActiveJob(job);
              setMainTab("jd");
            }}
            authSignedIn={authStatus === "signed_in"}
            onSaveJob={(job) => void handleSaveJob(job)}
            savedJobsEnabled={savedJobsEnabled}
            savedJobs={savedJobs}
            savedJobsNotice={savedJobsNotice}
            savedJobsLoading={savedJobsLoading}
            latestSavedJobAt={latestSavedJobAt}
            onLoadSavedJob={handleLoadSavedJob}
            onRemoveSavedJob={(job) => void handleRemoveSavedJob(job)}
          />
        ) : null}
        {mainTab === "jd" ? (
          <JDReview
            analysisState={analysisState}
            analysisIsStale={analysisIsStale}
            review={review}
            manualJobText={manualJobText}
            onManualJobTextChange={setManualJobText}
            selectedJobFile={selectedJobFile}
            onSelectedJobFileChange={setSelectedJobFile}
            jobFileState={jobFileState}
            jobFileUploading={jobFileUploading}
            jobFileNotice={jobFileNotice}
            activeJob={activeJob}
            jobInputCollapsed={jobInputCollapsed}
            onToggleJobInputCollapsed={() =>
              setJobInputCollapsed((current) => !current)
            }
            onJobDescriptionUpload={(file) =>
              void handleJobDescriptionUpload(file)
            }
            onClearLoadedJobDescription={handleClearLoadedJobDescription}
          />
        ) : null}

        {mainTab === "analysis" ? (
          <>
            <AnalysisRunner
              analysisState={analysisState}
              analysisLoading={analysisLoading}
              analysisJobState={analysisJobState}
              analysisIsStale={analysisIsStale}
              currentWorkflowStage={currentWorkflowStage}
              onRunAnalysis={() => void handleRunAnalysis()}
              onClearRole={clearWorkspaceRole}
            />

            <ArtifactViewer
              hasAnalysis={Boolean(analysisState)}
              artifact={currentArtifact}
              tab={artifactTab}
              onTabChange={setArtifactTab}
              exporting={artifactExporting}
              previewHtml={artifactPreviewHtml}
              previewTitle={artifactPreviewTitle}
              previewLoading={artifactPreviewLoading}
              onExport={(kind, format) => void handleArtifactExport(kind, format)}
            />
          </>
        ) : null}
      </div>
        </div>
      </div>
    </div>
  );
}
