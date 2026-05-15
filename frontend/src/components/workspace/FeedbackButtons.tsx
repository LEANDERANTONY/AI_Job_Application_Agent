"use client";

/**
 * Thumb-up / thumb-down pair with optional comment box.
 *
 * Rendered on every artifact surface where it makes sense:
 *   * tailored resume artifact card (after analysis completes)
 *   * cover letter artifact card
 *   * JD summary view
 *   * assistant turn (under each assistant response)
 *   * resume-builder session (after the user commits the profile)
 *
 * UX flow:
 *   1. User sees two unselected buttons (👍 / 👎) and a small
 *      "Was this helpful?" label.
 *   2. Click either button → state flips to "selected", a "Thanks!"
 *      confirmation slides in, AND the optional comment box becomes
 *      visible so the user can add context if they want.
 *   3. The POST to /workspace/feedback happens immediately on click
 *      (optimistic). If the request fails, we surface a tiny inline
 *      error and let the user retry without losing their rating
 *      state.
 *   4. If the user adds a comment, a second POST writes a fresh row
 *      with the comment text — feedback rows are immutable from the
 *      app's perspective, so a follow-up comment becomes its own
 *      row that aggregations can correlate by user_id + surface +
 *      timestamp.
 *
 * Optimistic UI: the "Thanks!" confirmation appears synchronously on
 * click; we DON'T wait for the POST to land before flipping the
 * state. That keeps the click feel snappy. If the POST fails, the
 * inline error still surfaces but the rating stays visible — the user
 * can retry by clicking again.
 *
 * Accessibility:
 *   * Each button has aria-label and aria-pressed reflecting the
 *     current rating selection. Screen readers announce the pair as
 *     a togglable pair.
 *   * The "Thanks!" status uses role="status" with aria-live="polite"
 *     so it's announced without interrupting whatever the user is
 *     reading.
 *   * The comment textarea has a visible label associated via htmlFor
 *     + id rather than aria-label so it works for sighted users too.
 *   * Disabled / busy state is communicated via the `disabled`
 *     attribute (skipped by keyboard nav).
 */

import { useCallback, useEffect, useId, useRef, useState } from "react";

import type { FeedbackSurface } from "@/lib/api-types";
import { recordFeedback } from "@/lib/api";

export type FeedbackButtonsProps = {
  /**
   * Which surface this feedback applies to. The shape is locked to
   * the SQL CHECK constraint via the FeedbackSurface union type.
   */
  surface: FeedbackSurface;
  /**
   * Optional trace_id from the OpenAIService cost-trace bridge. When
   * the surface maps to a single LLM call (tailored resume, cover
   * letter, assistant turn) we can correlate the rating with the
   * call's cost + model in the aggregate query. Resume-builder
   * sessions don't have a single trace to point at; we send `null`.
   */
  traceId?: string | null;
  /**
   * Optional className to forward to the outer container. Defaults
   * to a compact inline layout that fits inside an artifact card's
   * footer row.
   */
  className?: string;
  /**
   * Short prompt rendered next to the buttons. Defaults to "Was this
   * helpful?" — overridable for surfaces with different phrasing
   * (e.g. assistant: "Was this answer helpful?").
   */
  prompt?: string;
};

type FeedbackState =
  | { kind: "idle" }
  // rated-pending holds the rating locally without inserting a row.
  // We only commit once the user sends a comment, skips, the auto-
  // commit timer fires, or the component unmounts — guarantees
  // exactly ONE submitFeedback call per user action. Codex P1 on
  // PR #3 caught the previous design double-inserted (one row for
  // the rating, a second for the comment).
  | { kind: "rated-pending"; rating: "up" | "down" }
  | { kind: "submitting"; rating: "up" | "down" }
  | { kind: "submitted"; rating: "up" | "down" }
  | { kind: "error"; rating: "up" | "down"; message: string };

/** Wait window after user activity before auto-committing the rating
 *  alone. Long enough that a thoughtful comment has time to start
 *  typing (each keystroke resets the timer), short enough that idle
 *  users still get their rating captured. */
const AUTO_COMMIT_MS = 8000;

export function FeedbackButtons({
  surface,
  traceId,
  className,
  prompt,
}: FeedbackButtonsProps) {
  const [state, setState] = useState<FeedbackState>({ kind: "idle" });
  const [comment, setComment] = useState<string>("");
  // useId guarantees a DOM-unique value per component instance — the
  // prior ``feedback-comment-${surface}`` collided whenever the page
  // mounted multiple FeedbackButtons with the same surface (notably
  // multiple ``assistant_turn`` cards in one panel), causing every
  // <label htmlFor=> to target the first matching textarea and the
  // "tell us more" click to focus the wrong input.
  // Flagged 3x: CodeRabbit Major + Codex P2 + Codex P3 on PR #3.
  const commentTextareaId = useId();

  // Refs for the auto-commit timer + unmount best-effort flush.
  // Read by handlers that need the LATEST values rather than the
  // snapshot at first render.
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const stateRef = useRef<FeedbackState>(state);
  const commentRef = useRef<string>(comment);
  stateRef.current = state;
  commentRef.current = comment;
  // Belt-and-suspenders against the unmount race Codex flagged on
  // PR #3 round 4: setState is async, so between a Send/Skip click
  // (or auto-commit timer firing) and the next render, stateRef
  // still says "rated-pending" — and an unmount during that window
  // would fire a second recordFeedback. ``committingRef`` flips true
  // the instant any commit path starts; the unmount effect bails out
  // if it's set, ensuring exactly one submitFeedback per user action.
  const committingRef = useRef<boolean>(false);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  /** Single submit point. Sends EXACTLY ONE row per user action
   *  (Send button, Skip button, auto-commit timer, or unmount
   *  cleanup all funnel here). */
  const commitFeedback = useCallback(
    async (rating: "up" | "down", commentText: string) => {
      // Re-entry guard. ``committingRef`` is set true on entry; if
      // a second trigger fires (auto-commit timer racing a Send/Skip
      // click in the window before the disabled state has propagated
      // to the DOM), this returns early instead of letting both paths
      // call recordFeedback. Synchronous check + set guarantees only
      // one entry per commit attempt. Codex P1 on PR #3 round 5.
      if (committingRef.current) return;
      clearTimer();
      // Mark in-flight synchronously BEFORE the async setState. The
      // unmount effect reads this to decide whether to fire its own
      // best-effort flush — without the flag, an unmount between
      // the Send click and the next render would double-submit.
      committingRef.current = true;
      setState({ kind: "submitting", rating });
      try {
        await recordFeedback({
          surface,
          rating,
          trace_id: traceId ?? null,
          comment: commentText.slice(0, 4096),
        });
        setState({ kind: "submitted", rating });
      } catch (error) {
        const message =
          error instanceof Error && error.message
            ? error.message
            : "Couldn't save your feedback. Try again in a moment.";
        setState({ kind: "error", rating, message });
      } finally {
        // Reset the guard so a subsequent rated-pending state can
        // still trigger the unmount flush. Without this, after the
        // first submit ``committingRef`` would stay stuck at true,
        // and a user who re-rates and closes the tab would lose the
        // second rating. Codex P2 on PR #3 round 5.
        committingRef.current = false;
      }
    },
    [clearTimer, surface, traceId],
  );

  const scheduleAutoCommit = useCallback(
    (rating: "up" | "down") => {
      clearTimer();
      timerRef.current = setTimeout(() => {
        if (stateRef.current.kind !== "rated-pending") return;
        void commitFeedback(rating, commentRef.current);
      }, AUTO_COMMIT_MS);
    },
    [clearTimer, commitFeedback],
  );

  // Best-effort flush on unmount: if the user navigated away while
  // a rating is still pending AND no commit path has started, fire
  // one final recordFeedback so the rating isn't silently dropped.
  // The committingRef guard prevents the race where Send/Skip
  // already started a commit but state hasn't re-rendered yet.
  useEffect(() => {
    return () => {
      clearTimer();
      const current = stateRef.current;
      if (current.kind === "rated-pending" && !committingRef.current) {
        void recordFeedback({
          surface,
          rating: current.rating,
          trace_id: traceId ?? null,
          comment: commentRef.current.slice(0, 4096),
        }).catch(() => {
          // Unmount path: the user is gone, nothing to do with the error.
        });
      }
    };
  }, [clearTimer, surface, traceId]);

  function handleRating(rating: "up" | "down") {
    if (state.kind === "submitting") return;

    if (state.kind === "rated-pending" && state.rating === rating) {
      // Toggle off — return to idle without ever inserting a row.
      // Analytics never see this rating; the user effectively
      // un-rated before commit.
      clearTimer();
      setState({ kind: "idle" });
      setComment("");
      return;
    }
    if (state.kind === "submitted" && state.rating === rating) {
      // Already committed; clicking the same thumb is a no-op.
      // The backend row exists; clearing the UI without deleting
      // the row would be misleading. (Backend has no DELETE policy.)
      return;
    }
    // Fresh rating or switching ratings while pending — land in
    // rated-pending with the latest rating and restart the timer.
    //
    // Clear any leftover comment text: a comment typed under the
    // PRIOR rating shouldn't auto-submit with the new rating.
    // Without this, a user could type "wrong tone" under 👎, switch
    // to 👍, and the 8s auto-commit fires with rating="up" + stale
    // "wrong tone" comment. CodeRabbit + Codex P2 on PR #3 round 4.
    setComment("");
    setState({ kind: "rated-pending", rating });
    scheduleAutoCommit(rating);
  }

  function handleCommentChange(value: string) {
    setComment(value);
    if (state.kind === "rated-pending") {
      // Typing means the user is engaging with the comment — push
      // the auto-commit timer out so they have time to finish.
      scheduleAutoCommit(state.rating);
    }
  }

  function handleSend() {
    if (state.kind !== "rated-pending") return;
    void commitFeedback(state.rating, comment.trim());
  }

  function handleSkipComment() {
    if (state.kind !== "rated-pending") return;
    void commitFeedback(state.rating, "");
  }

  const currentRating =
    state.kind === "rated-pending" ||
    state.kind === "submitting" ||
    state.kind === "submitted" ||
    state.kind === "error"
      ? state.rating
      : null;
  const hasRating = currentRating !== null;
  const isInFlight = state.kind === "submitting";
  const showCommentArea = state.kind === "rated-pending";

  return (
    <div
      className={className}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 6,
        marginTop: 8,
      }}
    >
      <div
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 8,
          fontSize: 12,
          color: "var(--fg-3)",
        }}
      >
        <span>{prompt ?? "Was this helpful?"}</span>
        <button
          aria-label="Thumbs up — was helpful"
          aria-pressed={currentRating === "up"}
          className="rd-btn rd-btn-ghost rd-btn-sm"
          disabled={isInFlight}
          onClick={() => handleRating("up")}
          style={{
            padding: "2px 8px",
            opacity: currentRating === "down" ? 0.4 : 1,
            color: currentRating === "up" ? "#86efac" : undefined,
          }}
          type="button"
        >
          <span aria-hidden="true">👍</span>
        </button>
        <button
          aria-label="Thumbs down — wasn't helpful"
          aria-pressed={currentRating === "down"}
          className="rd-btn rd-btn-ghost rd-btn-sm"
          disabled={isInFlight}
          onClick={() => handleRating("down")}
          style={{
            padding: "2px 8px",
            opacity: currentRating === "up" ? 0.4 : 1,
            color: currentRating === "down" ? "#fb7185" : undefined,
          }}
          type="button"
        >
          <span aria-hidden="true">👎</span>
        </button>
        {hasRating ? (
          <span
            aria-live="polite"
            role="status"
            style={{ fontSize: 11.5, color: "var(--fg-2)" }}
          >
            {state.kind === "submitting"
              ? "Saving…"
              : state.kind === "submitted"
                ? "Thanks!"
                : null}
          </span>
        ) : null}
      </div>

      {state.kind === "error" ? (
        <div
          role="status"
          style={{
            fontSize: 11.5,
            color: "#fbbf24",
          }}
        >
          {state.message}
        </div>
      ) : null}

      {showCommentArea ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <label
            htmlFor={commentTextareaId}
            style={{ fontSize: 11.5, color: "var(--fg-3)" }}
          >
            Want to tell us more? (optional)
          </label>
          <textarea
            disabled={isInFlight}
            id={commentTextareaId}
            maxLength={4096}
            onChange={(event) => handleCommentChange(event.target.value)}
            placeholder={
              currentRating === "up"
                ? "What worked? (e.g. specific bullets, summary tone)"
                : "What missed? (e.g. wrong tone, missing skills, fabricated claims)"
            }
            rows={2}
            style={{
              padding: "6px 8px",
              fontSize: 12.5,
              background: "rgba(255, 255, 255, 0.02)",
              border: "1px solid var(--bd-1)",
              borderRadius: 4,
              color: "var(--fg-1)",
              resize: "vertical",
              minHeight: 48,
            }}
            value={comment}
          />
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <button
              className="rd-btn rd-btn-soft rd-btn-sm"
              disabled={isInFlight}
              onClick={handleSend}
              style={{ fontSize: 11, padding: "3px 10px" }}
              type="button"
            >
              Send
            </button>
            <button
              className="rd-btn rd-btn-ghost rd-btn-sm"
              disabled={isInFlight}
              onClick={handleSkipComment}
              style={{ fontSize: 11, padding: "3px 10px" }}
              type="button"
            >
              Skip
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
