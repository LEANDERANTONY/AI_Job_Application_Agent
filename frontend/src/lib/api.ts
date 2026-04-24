import type {
  AuthSessionResponse,
  AuthTokens,
  BackendHealth,
  GoogleSignInStartResponse,
  JobPosting,
  JobResolveResponse,
  JobSearchRequest,
  JobSearchResponse,
  LoadResumeBuilderSessionResponse,
  LoadSavedWorkspaceResponse,
  RemoveSavedJobResponse,
  ResumeBuilderCommitResponse,
  ResumeBuilderSessionResponse,
  SavedJobsResponse,
  SaveWorkspaceResponse,
  SaveSavedJobResponse,
  UploadedFilePayload,
  WorkspaceAnalysisRequest,
  WorkspaceAnalysisJobCreatedResponse,
  WorkspaceAnalysisJobStatusResponse,
  WorkspaceAnalysisResponse,
  WorkspaceArtifactExportRequest,
  WorkspaceArtifactExportResponse,
  WorkspaceArtifactPreviewRequest,
  WorkspaceArtifactPreviewResponse,
  WorkspaceAssistantRequest,
  WorkspaceAssistantResponse,
  WorkspaceJobDescriptionUploadResponse,
  WorkspaceResumeUploadResponse,
} from "@/lib/api-types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api";

const FILE_MIME_FALLBACKS: Record<string, string> = {
  pdf: "application/pdf",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  doc: "application/msword",
  txt: "text/plain",
  md: "text/markdown",
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    cache: "no-store",
    ...init,
  });
  const payload = await response
    .json()
    .catch(() => null);

  if (!response.ok) {
    const detail =
      payload && typeof payload === "object" && payload !== null
        ? "detail" in payload
          ? payload.detail
          : "error_message" in payload
            ? payload.error_message
            : null
        : null;
    const message = Array.isArray(detail)
      ? detail
          .map((item) =>
            typeof item === "object" && item !== null && "msg" in item
              ? String(item.msg)
              : String(item),
          )
          .join(", ")
      : detail
        ? String(detail)
        : `Request failed with status ${response.status}`;
    throw new Error(message);
  }

  return payload as T;
}

function inferMimeType(filename: string) {
  const extension = filename.split(".").pop()?.toLowerCase() ?? "";
  return FILE_MIME_FALLBACKS[extension] ?? "application/octet-stream";
}

function encodeBytesToBase64(bytes: Uint8Array) {
  let binary = "";
  const chunkSize = 0x8000;

  for (let index = 0; index < bytes.length; index += chunkSize) {
    const chunk = bytes.subarray(index, index + chunkSize);
    binary += String.fromCharCode(...chunk);
  }

  if (typeof globalThis.btoa !== "function") {
    throw new Error("Base64 encoding is unavailable in this browser context.");
  }

  return globalThis.btoa(binary);
}

function withAuthHeaders(authTokens?: AuthTokens | null) {
  const headers: Record<string, string> = {};
  if (!authTokens) {
    return headers;
  }
  headers["X-Auth-Access-Token"] = authTokens.access_token;
  headers["X-Auth-Refresh-Token"] = authTokens.refresh_token;
  return headers;
}

export async function fileToUploadPayload(file: File): Promise<UploadedFilePayload> {
  const buffer = await file.arrayBuffer();
  const bytes = new Uint8Array(buffer);

  return {
    filename: file.name,
    mime_type: file.type || inferMimeType(file.name),
    content_base64: encodeBytesToBase64(bytes),
  };
}

export async function getBackendHealth() {
  return request<BackendHealth>("/health");
}

export async function searchJobs(payload: JobSearchRequest) {
  return request<JobSearchResponse>("/jobs/search", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export async function resolveJobUrl(url: string) {
  return request<JobResolveResponse>("/jobs/resolve", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ url }),
  });
}

export async function startGoogleSignIn(redirectUrl: string) {
  return request<GoogleSignInStartResponse>("/auth/google/start", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ redirect_url: redirectUrl }),
  });
}

export async function exchangeGoogleCode(
  authCode: string,
  authFlow: string,
  redirectUrl: string,
) {
  return request<AuthSessionResponse>("/auth/google/exchange", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      auth_code: authCode,
      auth_flow: authFlow,
      redirect_url: redirectUrl,
    }),
  });
}

export async function restoreAuthSession(authTokens: AuthTokens) {
  return request<AuthSessionResponse>("/auth/session/restore", {
    method: "POST",
    headers: {
      ...withAuthHeaders(authTokens),
    },
  });
}

export async function signOutAuthSession(authTokens: AuthTokens) {
  return request<{ authenticated: boolean; status: string }>("/auth/session/sign-out", {
    method: "POST",
    headers: {
      ...withAuthHeaders(authTokens),
    },
  });
}

export async function uploadResumeFile(file: File, authTokens?: AuthTokens | null) {
  const payload = await fileToUploadPayload(file);
  return request<WorkspaceResumeUploadResponse>("/workspace/resume/upload", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...withAuthHeaders(authTokens),
    },
    body: JSON.stringify(payload),
  });
}

export async function loadLatestResumeBuilderSession(authTokens?: AuthTokens | null) {
  return request<LoadResumeBuilderSessionResponse>("/workspace/resume-builder/latest", {
    method: "GET",
    headers: {
      ...withAuthHeaders(authTokens),
    },
  });
}

export async function startResumeBuilderSession(authTokens?: AuthTokens | null) {
  return request<ResumeBuilderSessionResponse>("/workspace/resume-builder/start", {
    method: "POST",
    headers: {
      ...withAuthHeaders(authTokens),
    },
  });
}

export async function sendResumeBuilderMessage(
  sessionId: string,
  message: string,
  authTokens?: AuthTokens | null,
) {
  return request<ResumeBuilderSessionResponse>("/workspace/resume-builder/message", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...withAuthHeaders(authTokens),
    },
    body: JSON.stringify({
      session_id: sessionId,
      message,
      input_mode: "text",
    }),
  });
}

export async function generateResumeBuilderResume(
  sessionId: string,
  authTokens?: AuthTokens | null,
) {
  return request<ResumeBuilderSessionResponse>("/workspace/resume-builder/generate", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...withAuthHeaders(authTokens),
    },
    body: JSON.stringify({
      session_id: sessionId,
    }),
  });
}

export async function updateResumeBuilderDraft(
  sessionId: string,
  draftProfile: Record<string, unknown>,
  authTokens?: AuthTokens | null,
) {
  return request<ResumeBuilderSessionResponse>("/workspace/resume-builder/update", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...withAuthHeaders(authTokens),
    },
    body: JSON.stringify({
      session_id: sessionId,
      draft_profile: draftProfile,
    }),
  });
}

export async function commitResumeBuilderResume(
  sessionId: string,
  authTokens?: AuthTokens | null,
) {
  return request<ResumeBuilderCommitResponse>("/workspace/resume-builder/commit", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...withAuthHeaders(authTokens),
    },
    body: JSON.stringify({
      session_id: sessionId,
    }),
  });
}

export async function uploadJobDescriptionFile(file: File, authTokens?: AuthTokens | null) {
  const payload = await fileToUploadPayload(file);
  return request<WorkspaceJobDescriptionUploadResponse>(
    "/workspace/job-description/upload",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...withAuthHeaders(authTokens),
      },
      body: JSON.stringify(payload),
    },
  );
}

export async function runWorkspaceAnalysis(
  payload: WorkspaceAnalysisRequest,
  authTokens?: AuthTokens | null,
) {
  return request<WorkspaceAnalysisResponse>("/workspace/analyze", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...withAuthHeaders(authTokens),
    },
    body: JSON.stringify(payload),
  });
}

export async function startWorkspaceAnalysisJob(
  payload: WorkspaceAnalysisRequest,
  authTokens?: AuthTokens | null,
) {
  return request<WorkspaceAnalysisJobCreatedResponse>("/workspace/analyze-jobs", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...withAuthHeaders(authTokens),
    },
    body: JSON.stringify(payload),
  });
}

export async function getWorkspaceAnalysisJob(
  jobId: string,
  authTokens?: AuthTokens | null,
) {
  return request<WorkspaceAnalysisJobStatusResponse>(`/workspace/analyze-jobs/${jobId}`, {
    method: "GET",
    headers: {
      ...withAuthHeaders(authTokens),
    },
  });
}

export async function askWorkspaceAssistant(
  payload: WorkspaceAssistantRequest,
  authTokens?: AuthTokens | null,
) {
  return request<WorkspaceAssistantResponse>("/workspace/assistant/answer", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...withAuthHeaders(authTokens),
    },
    body: JSON.stringify(payload),
  });
}

export async function saveWorkspaceSnapshot(
  workspaceSnapshot: WorkspaceAnalysisResponse,
  authTokens: AuthTokens,
) {
  return request<SaveWorkspaceResponse>("/workspace/save", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...withAuthHeaders(authTokens),
    },
    body: JSON.stringify({
      workspace_snapshot: workspaceSnapshot,
    }),
  });
}

export async function loadSavedWorkspace(authTokens: AuthTokens) {
  return request<LoadSavedWorkspaceResponse>("/workspace/saved", {
    method: "GET",
    headers: {
      ...withAuthHeaders(authTokens),
    },
  });
}

export async function loadSavedJobs(authTokens: AuthTokens) {
  return request<SavedJobsResponse>("/workspace/saved-jobs", {
    method: "GET",
    headers: {
      ...withAuthHeaders(authTokens),
    },
  });
}

export async function saveSavedJob(jobPosting: JobPosting, authTokens: AuthTokens) {
  return request<SaveSavedJobResponse>("/workspace/saved-jobs", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...withAuthHeaders(authTokens),
    },
    body: JSON.stringify({
      job_posting: jobPosting,
    }),
  });
}

export async function removeSavedJob(jobId: string, authTokens: AuthTokens) {
  return request<RemoveSavedJobResponse>(`/workspace/saved-jobs/${encodeURIComponent(jobId)}`, {
    method: "DELETE",
    headers: {
      ...withAuthHeaders(authTokens),
    },
  });
}

export async function exportWorkspaceArtifact(
  payload: WorkspaceArtifactExportRequest,
) {
  return request<WorkspaceArtifactExportResponse>("/workspace/artifacts/export", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export async function previewWorkspaceArtifact(
  payload: WorkspaceArtifactPreviewRequest,
) {
  return request<WorkspaceArtifactPreviewResponse>("/workspace/artifacts/preview", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}
