import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

import {
  startWorkspaceAnalysisJob,
  uploadJobDescriptionFile,
  TierLimitExceededError,
} from "@/lib/api";
import type { WorkspaceAnalysisRequest } from "@/lib/api-types";

const PAYLOAD: WorkspaceAnalysisRequest = {
  resume_text: "r",
  resume_filetype: "TXT",
  resume_source: "workspace",
  job_description_text: "j",
  imported_job_posting: null,
  run_assisted: true,
};

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

describe("api request() contract", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("maps a 429 tier_limit_exceeded body to a TierLimitExceededError with the structured fields", async () => {
    // This is the contract the upgrade-CTA path (CRITICAL-2) depends on: a
    // capped run must surface as a typed error carrying counter/cap/tier, not
    // a generic Error.
    const payload = {
      detail: "You've reached your weekly cap — upgrade to continue.",
      code: "tier_limit_exceeded",
      counter: "llm_tokens",
      current: 90000,
      cap: 90000,
      reset_period: "weekly",
      tier: "free",
    };
    vi.mocked(fetch).mockResolvedValue(jsonResponse(payload, 429) as Response);

    const error = await startWorkspaceAnalysisJob(PAYLOAD).catch((e) => e);

    expect(error).toBeInstanceOf(TierLimitExceededError);
    expect(error.code).toBe("tier_limit_exceeded");
    expect(error.counter).toBe("llm_tokens");
    expect(error.cap).toBe(90000);
    expect(error.tier).toBe("free");
    expect(error.message).toContain("upgrade");
  });

  it("POSTs to the analyze-jobs endpoint with credentials and a JSON body", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({
        job_id: "abc",
        status: "queued",
        stage_title: null,
        stage_detail: null,
        progress_percent: 3,
        result: null,
        error_message: null,
      }) as Response,
    );

    await startWorkspaceAnalysisJob(PAYLOAD);

    const [url, init] = vi.mocked(fetch).mock.calls[0];
    expect(url).toBe("/api/workspace/analyze-jobs");
    expect(init?.method).toBe("POST");
    // Cross-subdomain HttpOnly auth cookies ride on every call.
    expect(init?.credentials).toBe("include");
    expect(JSON.parse(String(init?.body)).resume_text).toBe("r");
  });

  it("throws a plain Error (not a tier-limit error) for a non-tier 4xx", async () => {
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse({ detail: "Bad request." }, 400) as Response,
    );
    const error = await startWorkspaceAnalysisJob(PAYLOAD).catch((e) => e);
    expect(error).toBeInstanceOf(Error);
    expect(error).not.toBeInstanceOf(TierLimitExceededError);
    expect(error.message).toBe("Bad request.");
  });

  it("threads the abort signal through uploadJobDescriptionFile to fetch (M16)", async () => {
    vi.mocked(fetch).mockResolvedValue(jsonResponse({}, 200) as Response);
    const controller = new AbortController();
    // jsdom's File has no arrayBuffer(); fileToUploadPayload only needs
    // name / type / arrayBuffer, so a minimal fake suffices.
    const file = {
      name: "pasted.txt",
      type: "text/plain",
      arrayBuffer: async () =>
        new TextEncoder().encode("a job description").buffer,
    } as unknown as File;

    await uploadJobDescriptionFile(file, controller.signal);

    const [, init] = vi.mocked(fetch).mock.calls[0];
    // The signal reaches fetch, so a superseded parse actually aborts.
    expect(init?.signal).toBe(controller.signal);
  });
});
