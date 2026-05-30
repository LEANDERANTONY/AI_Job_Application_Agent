import { describe, it, expect } from "vitest";

import { humanizeApiError } from "@/lib/humanizeApiError";

describe("humanizeApiError", () => {
  it("maps a 401 'Request failed with status' to the re-auth copy", () => {
    expect(humanizeApiError(new Error("Request failed with status 401"))).toBe(
      "Please sign in to continue.",
    );
  });

  it("maps a 429 to the rate-limit copy", () => {
    expect(humanizeApiError(new Error("Request failed with status 429"))).toBe(
      "Too many requests right now. Please wait a moment and try again.",
    );
  });

  it("translates an unmapped 5xx to a generic server-error message", () => {
    expect(humanizeApiError(new Error("Request failed with status 503"))).toBe(
      "Something went wrong on our end. Please try again in a moment.",
    );
  });

  it("strips a leaky Python exception prefix down to the message", () => {
    expect(humanizeApiError(new Error("ValueError: bad input"))).toBe(
      "bad input",
    );
  });

  it("falls back to the provided fallback when the input carries no message", () => {
    expect(humanizeApiError(null, "Workspace analysis failed.")).toBe(
      "Workspace analysis failed.",
    );
  });
});
