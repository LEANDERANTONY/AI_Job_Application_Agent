import type {
  ArtifactTheme,
  AuthSessionResponse,
  BackendHealth,
  FeedbackRequest,
  FeedbackResponse,
  GoogleSignInStartResponse,
  JobPosting,
  JobResolveResponse,
  JobSearchRequest,
  JobSearchResponse,
  LoadResumeBuilderSessionResponse,
  LoadSavedWorkspaceResponse,
  RemoveSavedJobResponse,
  ResumeBuilderCommitResponse,
  ResumeBuilderExportResponse,
  ResumeBuilderSessionResponse,
  SavedJobsResponse,
  SaveWorkspaceResponse,
  SaveSavedJobResponse,
  TierLimitExceededPayload,
  UploadedFilePayload,
  WorkspaceAnalysisRequest,
  WorkspaceAnalysisJobCreatedResponse,
  WorkspaceAnalysisJobStatusResponse,
  WorkspaceAnalysisResponse,
  WorkspaceArtifactExportFormat,
  WorkspaceArtifactExportRequest,
  WorkspaceArtifactExportResponse,
  WorkspaceArtifactPreviewRequest,
  WorkspaceArtifactPreviewResponse,
  WorkspaceHandoffStartResponse,
  AssistantStreamEvent,
  WorkspaceAssistantRequest,
  WorkspaceAssistantResponse,
  WorkspaceJobDescriptionUploadResponse,
  WorkspaceQuotaResponse,
  WorkspaceResumeUploadResponse,
} from "@/lib/api-types";

/** Error subclass thrown when the backend returns a 429 with the
 *  `tier_limit_exceeded` payload (Step 7b). Callers `instanceof`-check
 *  this to render a toast with an upgrade CTA rather than the generic
 *  error path. Falling through to the generic path would surface a
 *  red toast with the raw `detail` text — usable, but missing the
 *  upgrade affordance. */
export class TierLimitExceededError extends Error {
  readonly code = "tier_limit_exceeded" as const;
  readonly counter: string;
  readonly current: number;
  readonly cap: number;
  readonly resetPeriod: string;
  readonly tier: "free" | "pro" | "business";

  constructor(payload: TierLimitExceededPayload) {
    super(payload.detail);
    this.name = "TierLimitExceededError";
    this.counter = payload.counter;
    this.current = payload.current;
    this.cap = payload.cap;
    this.resetPeriod = payload.reset_period;
    this.tier = payload.tier;
  }
}

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "/api";

const FILE_MIME_FALLBACKS: Record<string, string> = {
  pdf: "application/pdf",
  docx: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  doc: "application/msword",
  txt: "text/plain",
  md: "text/markdown",
};

/** Decode a base64 file payload (returned by the backend's export
 *  routes) and trigger a browser download. Shared between the
 *  workspace artifact viewer and the resume builder download row so
 *  both surfaces produce identically-shaped downloads. */
export function downloadBase64File(
  filename: string,
  contentBase64: string,
  mimeType: string,
) {
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
    // 429 with the canonical tier-limit body gets converted to a
    // typed exception so the caller can render a structured upgrade
    // toast (counter + cap + upgrade CTA). Falls through to the
    // generic Error path for any other 429 (e.g. SlowAPI's
    // rate-limit middleware uses a different body shape).
    if (
      response.status === 429 &&
      payload &&
      typeof payload === "object" &&
      "code" in payload &&
      (payload as { code?: unknown }).code === "tier_limit_exceeded"
    ) {
      throw new TierLimitExceededError(payload as TierLimitExceededPayload);
    }
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

export async function startWorkspaceHandoff(targetUrl: string) {
  return request<WorkspaceHandoffStartResponse>("/auth/workspace-handoff/start", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ target_url: targetUrl }),
  });
}

export async function exchangeWorkspaceHandoff(handoffToken: string) {
  return request<AuthSessionResponse>("/auth/workspace-handoff/exchange", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ handoff_token: handoffToken }),
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

export async function exportResumeBuilderArtifact(payload: {
  session_id: string;
  export_format: WorkspaceArtifactExportFormat;
  theme: ArtifactTheme;
}) {
  return request<ResumeBuilderExportResponse>(
    "/workspace/resume-builder/export",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    },
  );
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

/** Request cooperative cancellation of an in-flight analysis run.
 *  Returns the job state (usually still "running" — the backend
 *  worker observes the cancel flag at its next stage boundary, so the
 *  caller keeps polling until the terminal "cancelled" lands). 404
 *  when the job is already gone/finished. */
export async function cancelWorkspaceAnalysisJob(jobId: string) {
  return request<WorkspaceAnalysisJobStatusResponse>(
    `/workspace/analyze-jobs/${jobId}/cancel`,
    {
      method: "POST",
    },
  );
}

/** Fetch the read-only quota snapshot for the workspace UI.
 *  Drives the Premium toggle's enabled/disabled state and per-counter
 *  indicators. The hook owning the toggle calls this on mount and
 *  after every workflow run so the indicator stays in sync with the
 *  actual backend state.
 *
 *  Anonymous callers get a 401 here; the caller is expected to skip
 *  the quota render in that branch rather than treat it as a hard
 *  error. */
export async function getWorkspaceQuota() {
  return request<WorkspaceQuotaResponse>("/workspace/quota", {
    method: "GET",
  });
}

// ---------------------------------------------------------------------------
// Lemon Squeezy: hosted checkout URLs + customer portal redirect.
//
// The hosted checkout URL pattern is documented at
// https://docs.lemonsqueezy.com/help/checkout/hosted-checkouts.
// Format: https://{store_subdomain}.lemonsqueezy.com/checkout/buy/{variant_uuid}
// An earlier draft used `/buy/<variant>` which is a non-checkout
// endpoint (Codex P1 finding on HelpmateAI's PR #4, mirrored here
// because the LS scaffold for both apps was built from the same
// template). Paid conversion fails the moment LS goes live with the
// wrong path, so this fix lands BEFORE KYC clears.
//
// We append checkout[custom][user_id] so the LS webhook can bind the
// subscription back to our Supabase user. Without that binding the
// webhook handler has no way to write the right row.
//
// Env vars (NEXT_PUBLIC_ prefix so Next.js inlines them into the JS
// bundle at build time):
//   NEXT_PUBLIC_LEMONSQUEEZY_STORE_ID — subdomain piece. "" disables.
//   NEXT_PUBLIC_LEMONSQUEEZY_PRODUCT_VARIANT_PRO     — pro variant uuid
//   NEXT_PUBLIC_LEMONSQUEEZY_PRODUCT_VARIANT_BUSINESS — business uuid
//
// When any of these are empty (the integration isn't live on this
// deploy), getCheckoutUrl returns "" so the caller can render the CTA
// as "Coming soon" / disabled.

const LEMONSQUEEZY_STORE_ID =
  process.env.NEXT_PUBLIC_LEMONSQUEEZY_STORE_ID ?? "";
const LEMONSQUEEZY_VARIANT_PRO =
  process.env.NEXT_PUBLIC_LEMONSQUEEZY_PRODUCT_VARIANT_PRO ?? "";
const LEMONSQUEEZY_VARIANT_BUSINESS =
  process.env.NEXT_PUBLIC_LEMONSQUEEZY_PRODUCT_VARIANT_BUSINESS ?? "";

/** True when the LS env vars are populated. Pricing CTAs gate on this
 *  to render "Coming soon" copy when the integration hasn't shipped
 *  to this deploy yet. */
export function isLemonSqueezyEnabled(): boolean {
  return Boolean(
    LEMONSQUEEZY_STORE_ID &&
      (LEMONSQUEEZY_VARIANT_PRO || LEMONSQUEEZY_VARIANT_BUSINESS),
  );
}

/** Build a Lemon Squeezy hosted checkout URL for a tier, bound to the
 *  supplied Supabase user_id via checkout[custom][user_id]. The
 *  webhook handler reads that field out of meta.custom_data on
 *  subscription_created and writes the matching subscriptions row.
 *
 *  Also passes `checkout[success_url]` so the user lands back on the
 *  workspace with `?ls_checkout=success` -- WorkspaceShell's effect
 *  refreshes the quota snapshot on that param.
 *
 *  Returns "" when the integration isn't configured on this build.
 *  The pricing CTA renders "Coming soon" in that branch. */
export function getCheckoutUrl(
  tier: "pro" | "business",
  userId: string,
): string {
  if (!LEMONSQUEEZY_STORE_ID) return "";
  const variant =
    tier === "pro"
      ? LEMONSQUEEZY_VARIANT_PRO
      : LEMONSQUEEZY_VARIANT_BUSINESS;
  if (!variant) return "";
  const base = `https://${LEMONSQUEEZY_STORE_ID}.lemonsqueezy.com/checkout/buy/${variant}`;
  if (!userId) return base;
  // LS expects checkout fields as URL-encoded query params; the
  // bracket syntax is the documented form for nested fields.
  const query = new URLSearchParams();
  query.set("checkout[custom][user_id]", userId);
  // Per-checkout success URL override. Build off the current origin
  // so dev / staging / prod each land on themselves; the LS
  // dashboard's default success URL is still honored when this
  // parameter isn't sent (e.g. a checkout link shared offline).
  if (typeof window !== "undefined" && window.location?.origin) {
    const successUrl = new URL(window.location.origin);
    // Preserve the current path so a click from /pricing returns
    // to /pricing; default to /workspace so the post-checkout user
    // lands somewhere useful when initiated from the marketing
    // site. The success param gates the quota refresh effect in
    // WorkspaceShell.
    successUrl.pathname = window.location.pathname || "/workspace";
    successUrl.searchParams.set("ls_checkout", "success");
    query.set("checkout[success_url]", successUrl.toString());
  }
  return `${base}?${query.toString()}`;
}

/** Hit the backend `/billing/portal` route to mint a one-time LS
 *  customer portal URL and redirect the browser to it. The portal
 *  lets the user update card details, cancel, or resume the
 *  subscription.
 *
 *  Throws on 401 (sign in), 404 (no subscription), 503 (LS not
 *  configured), 502 (LS upstream error). Callers wrap with a try/
 *  catch + toast — the failure modes are user-meaningful so we
 *  don't want them to surface as a generic "request failed". */
export async function getCustomerPortalUrl(): Promise<{ url: string }> {
  return request<{ url: string }>("/billing/portal", {
    method: "POST",
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

/**
 * POST audio Blob (webm/mp4/wav from MediaRecorder) to the Whisper-
 * backed transcription endpoint. Returns `{ text, duration_seconds }`.
 *
 * Used by:
 *   * Resume Builder chat input (flagship surface — speak a long
 *     answer about experience instead of typing one-liners)
 *   * Workspace assistant chat (secondary)
 *
 * Auth required: anonymous callers get 401. The 25 MB cap on the
 * server is checked locally too via the size of the Blob before the
 * POST, but the route enforces the canonical limit.
 */
export type TranscribeResponse = {
  text: string;
  duration_seconds: number;
};

/**
 * Record one 👍 / 👎 feedback row for a workspace artifact / turn.
 *
 * Each call writes ONE row — feedback is immutable from the app's
 * perspective, so a follow-up comment becomes its own row that
 * aggregations correlate by (user_id, surface, created_at).
 *
 * Auth is required (401 otherwise). The route validates surface +
 * rating against a Pydantic Literal so a typo in this call site
 * fails at the FastAPI parse boundary with a 422 — surfaced here as
 * the generic request<>() path.
 */
export async function recordFeedback(payload: FeedbackRequest) {
  return request<FeedbackResponse>("/workspace/feedback", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

// Mirrors MAX_AUDIO_BYTES in backend/services/transcribe_service.py
// (Whisper's hard cap is 25 MB). Surfacing the check client-side
// avoids burning a multi-MB upload over a slow connection only to be
// rejected at the server with a 413. CodeRabbit on PR #3.
const TRANSCRIBE_MAX_AUDIO_BYTES = 25 * 1024 * 1024;

export async function transcribeAudio(audioBlob: Blob): Promise<TranscribeResponse> {
  // Client-side size guard so a slow uploader doesn't wait for a
  // 413 to land after spending tens of seconds uploading. The
  // server-side check is still authoritative (a hostile client can
  // bypass this), so we keep the backend gate as defense in depth.
  if (audioBlob.size > TRANSCRIBE_MAX_AUDIO_BYTES) {
    throw new Error(
      "Audio recording exceeds the 25 MB limit. Try a shorter recording or a more compressed format.",
    );
  }
  // FormData lets the browser set the multipart boundary correctly —
  // don't add Content-Type ourselves or fetch will pick the wrong
  // boundary and the upload will fail at FastAPI's parser.
  const formData = new FormData();
  // Filename hint: Whisper inspects the extension to pick a demuxer.
  // The MIME comes off the Blob; the server normalizes both.
  const extensionHint = audioBlob.type.includes("mp4")
    ? "mp4"
    : audioBlob.type.includes("wav")
      ? "wav"
      : audioBlob.type.includes("ogg")
        ? "ogg"
        : "webm";
  formData.append("file", audioBlob, `voice.${extensionHint}`);

  const response = await fetch(`${API_BASE_URL}/workspace/transcribe`, {
    method: "POST",
    credentials: "include",
    cache: "no-store",
    body: formData,
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const detail =
      payload && typeof payload === "object" && payload !== null && "detail" in payload
        ? String((payload as { detail?: unknown }).detail ?? "")
        : "";
    throw new Error(
      detail || `Voice transcription failed with status ${response.status}`,
    );
  }
  return payload as TranscribeResponse;
}
