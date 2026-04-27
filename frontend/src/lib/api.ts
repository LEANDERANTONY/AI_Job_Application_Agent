import type {
  AuthSessionResponse,
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
  AssistantStreamEvent,
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
  // credentials: "include" makes the browser send and accept the
  // HttpOnly auth cookies issued by /auth/google/exchange and
  // /auth/session/restore. Required for cross-subdomain calls and
  // harmless on same-origin/proxy setups.
  const response = await fetch(`${API_BASE_URL}${path}`, {
    cache: "no-store",
    credentials: "include",
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

export async function restoreAuthSession() {
  return request<AuthSessionResponse>("/auth/session/restore", {
    method: "POST",
  });
}

export async function signOutAuthSession() {
  return request<{ authenticated: boolean; status: string }>("/auth/session/sign-out", {
    method: "POST",
  });
}

export async function uploadResumeFile(file: File) {
  const payload = await fileToUploadPayload(file);
  return request<WorkspaceResumeUploadResponse>("/workspace/resume/upload", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export async function loadLatestResumeBuilderSession() {
  return request<LoadResumeBuilderSessionResponse>("/workspace/resume-builder/latest", {
    method: "GET",
  });
}

export async function startResumeBuilderSession() {
  return request<ResumeBuilderSessionResponse>("/workspace/resume-builder/start", {
    method: "POST",
  });
}

export async function sendResumeBuilderMessage(
  sessionId: string,
  message: string,
) {
  return request<ResumeBuilderSessionResponse>("/workspace/resume-builder/message", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      session_id: sessionId,
      message,
      input_mode: "text",
    }),
  });
}

export async function generateResumeBuilderResume(sessionId: string) {
  return request<ResumeBuilderSessionResponse>("/workspace/resume-builder/generate", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      session_id: sessionId,
    }),
  });
}

export async function updateResumeBuilderDraft(
  sessionId: string,
  draftProfile: Record<string, unknown>,
) {
  return request<ResumeBuilderSessionResponse>("/workspace/resume-builder/update", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      session_id: sessionId,
      draft_profile: draftProfile,
    }),
  });
}

export async function commitResumeBuilderResume(sessionId: string) {
  return request<ResumeBuilderCommitResponse>("/workspace/resume-builder/commit", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      session_id: sessionId,
    }),
  });
}

export async function uploadJobDescriptionFile(file: File) {
  const payload = await fileToUploadPayload(file);
  return request<WorkspaceJobDescriptionUploadResponse>(
    "/workspace/job-description/upload",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    },
  );
}

export async function runWorkspaceAnalysis(payload: WorkspaceAnalysisRequest) {
  return request<WorkspaceAnalysisResponse>("/workspace/analyze", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export async function startWorkspaceAnalysisJob(payload: WorkspaceAnalysisRequest) {
  return request<WorkspaceAnalysisJobCreatedResponse>("/workspace/analyze-jobs", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export async function getWorkspaceAnalysisJob(jobId: string) {
  return request<WorkspaceAnalysisJobStatusResponse>(`/workspace/analyze-jobs/${jobId}`, {
    method: "GET",
  });
}

export async function askWorkspaceAssistant(payload: WorkspaceAssistantRequest) {
  return request<WorkspaceAssistantResponse>("/workspace/assistant/answer", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

// ---------------------------------------------------------------------------
// Streaming assistant: Server-Sent Events client.
//
// Why fetch+ReadableStream and not EventSource:
//   1. EventSource only supports GET, but the assistant request has a
//      JSON body.
//   2. EventSource doesn't allow custom credentials handling.
// So we POST normally and parse the SSE byte stream by hand. Auth
// rides along on the HttpOnly cookie via credentials: "include".
// ---------------------------------------------------------------------------

function parseSseFrame(frame: string): AssistantStreamEvent | null {
  let eventName = "";
  const dataLines: string[] = [];
  for (const line of frame.split(/\r?\n/)) {
    if (line.startsWith("event:")) {
      eventName = line.slice("event:".length).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice("data:".length).trim());
    }
  }
  const dataText = dataLines.join("\n");
  let data: unknown = {};
  if (dataText) {
    try {
      data = JSON.parse(dataText);
    } catch {
      return null;
    }
  }
  const obj = (data && typeof data === "object" ? data : {}) as Record<string, unknown>;
  switch (eventName) {
    case "meta":
      return {
        type: "meta",
        sources: Array.isArray(obj.sources)
          ? (obj.sources as unknown[]).map((value) => String(value))
          : [],
      };
    case "delta":
      return {
        type: "delta",
        text: typeof obj.text === "string" ? obj.text : "",
      };
    case "done":
      return { type: "done" };
    case "error":
      return {
        type: "error",
        detail:
          typeof obj.detail === "string" && obj.detail
            ? obj.detail
            : "Assistant stream failed.",
      };
    default:
      return null;
  }
}

export async function streamWorkspaceAssistantAnswer(
  payload: WorkspaceAssistantRequest,
  onEvent: (event: AssistantStreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API_BASE_URL}/workspace/assistant/answer/stream`, {
    method: "POST",
    cache: "no-store",
    credentials: "include",
    signal,
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    // For non-200 responses the body is JSON, not SSE. Surface the
    // detail in the same shape as the request<T> error path.
    const errorPayload = await response.json().catch(() => null);
    const detail =
      errorPayload && typeof errorPayload === "object" && errorPayload !== null
        ? "detail" in errorPayload
          ? (errorPayload as { detail?: unknown }).detail
          : null
        : null;
    throw new Error(
      typeof detail === "string" && detail.trim()
        ? detail
        : `Assistant stream request failed (${response.status}).`,
    );
  }

  if (!response.body) {
    throw new Error("Assistant stream returned an empty body.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    // Each iteration drains every fully-formed SSE frame from `buffer`
    // before reading the next chunk, so a large network read never
    // delays already-complete frames from reaching `onEvent`.
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let delimiterIndex = buffer.indexOf("\n\n");
      while (delimiterIndex >= 0) {
        const frame = buffer.slice(0, delimiterIndex);
        buffer = buffer.slice(delimiterIndex + 2);
        const event = parseSseFrame(frame);
        if (event) onEvent(event);
        delimiterIndex = buffer.indexOf("\n\n");
      }
    }

    // Tail: trailing frame without the terminating blank line. The
    // backend always emits one, but defensive parsing here keeps the
    // client robust to upstream changes or proxy quirks.
    const tail = buffer.trim();
    if (tail) {
      const event = parseSseFrame(tail);
      if (event) onEvent(event);
    }
  } finally {
    try {
      reader.releaseLock();
    } catch {
      // Reader may already be released if the body was cancelled;
      // that's expected on AbortController.abort() and not an error.
    }
  }
}

export async function saveWorkspaceSnapshot(
  workspaceSnapshot: WorkspaceAnalysisResponse,
) {
  return request<SaveWorkspaceResponse>("/workspace/save", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      workspace_snapshot: workspaceSnapshot,
    }),
  });
}

export async function loadSavedWorkspace() {
  return request<LoadSavedWorkspaceResponse>("/workspace/saved", {
    method: "GET",
  });
}

export async function loadSavedJobs() {
  return request<SavedJobsResponse>("/workspace/saved-jobs", {
    method: "GET",
  });
}

export async function saveSavedJob(jobPosting: JobPosting) {
  return request<SaveSavedJobResponse>("/workspace/saved-jobs", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      job_posting: jobPosting,
    }),
  });
}

export async function removeSavedJob(jobId: string) {
  return request<RemoveSavedJobResponse>(`/workspace/saved-jobs/${encodeURIComponent(jobId)}`, {
    method: "DELETE",
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
