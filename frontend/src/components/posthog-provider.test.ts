import { describe, it, expect } from "vitest";

import { SESSION_RECORDING_OPTIONS } from "@/components/posthog-provider";

// The candidate's PII (parsed-JD hero, skill chips, LLM summary, fit
// analysis, assistant bubbles) is rendered as ordinary DOM text, which
// maskAllInputs does NOT cover. maskTextSelector "*" masks ALL rendered text
// so it is never streamed to the replay processor (M6).
describe("PostHog session-replay masking (M6)", () => {
  it("masks all rendered text, not just input values", () => {
    expect(SESSION_RECORDING_OPTIONS.maskTextSelector).toBe("*");
    expect(SESSION_RECORDING_OPTIONS.maskAllInputs).toBe(true);
  });
});
