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

import { useId, useState } from "react";

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
  | { kind: "submitting"; rating: "up" | "down" }
  | { kind: "submitted"; rating: "up" | "down" }
  | { kind: "error"; rating: "up" | "down"; message: string };

export function FeedbackButtons({
  surface,
  traceId,
  className,
  prompt,
}: FeedbackButtonsProps) {
  const [state, setState] = useState<FeedbackState>({ kind: "idle" });
  const [comment, setComment] = useState<string>("");
  const [commentSubmitting, setCommentSubmitting] = useState<boolean>(false);
  const [commentSubmitted, setCommentSubmitted] = useState<boolean>(false);
  const [commentError, setCommentError] = useState<string | null>(null);
  // useId guarantees a DOM-unique value per component instance — the
  // prior ``feedback-comment-${surface}`` collided whenever the page
  // mounted multiple FeedbackButtons with the same surface (notably
  // multiple ``assistant_turn`` cards in one panel), causing every
  // <label htmlFor=> to target the first matching textarea and the
  // "tell us more" click to focus the wrong input.
  // Flagged 3x: CodeRabbit Major + Codex P2 + Codex P3 on PR #3.
  const commentTextareaId = useId();

  const currentRating =
    state.kind === "submitting" ||
    state.kind === "submitted" ||
    state.kind === "error"
      ? state.rating
      : null;

  async function handleRating(rating: "up" | "down") {
    // Optimistic flip — don't wait for the POST. The "Thanks!" copy
    // and the selected button state appear synchronously.
    setState({ kind: "submitting", rating });
    try {
      await recordFeedback({
        surface,
        rating,
        trace_id: traceId ?? null,
        comment: "",
      });
      setState({ kind: "submitted", rating });
    } catch (error) {
      // Failure surface: we keep the rating "selected" so the user
      // sees what they intended; the inline error nudges retry.
      const message =
        error instanceof Error && error.message
          ? error.message
          : "Couldn't save your feedback. Try again in a moment.";
      setState({ kind: "error", rating, message });
    }
  }

  async function handleCommentSubmit() {
    const text = comment.trim();
    if (!text) return;
    if (!currentRating) return;
    setCommentSubmitting(true);
    setCommentError(null);
    try {
      // A fresh row carries the comment text alongside the rating —
      // feedback rows are immutable so a follow-up comment is its own
      // row that aggregations correlate by (user_id, surface,
      // created_at).
      await recordFeedback({
        surface,
        rating: currentRating,
        trace_id: traceId ?? null,
        comment: text,
      });
      setCommentSubmitted(true);
    } catch (error) {
      const message =
        error instanceof Error && error.message
          ? error.message
          : "Couldn't save your comment. Try again.";
      setCommentError(message);
    } finally {
      setCommentSubmitting(false);
    }
  }

  const hasRating =
    state.kind === "submitted" ||
    state.kind === "error" ||
    state.kind === "submitting";

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
          disabled={state.kind === "submitting"}
          onClick={() => void handleRating("up")}
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
          disabled={state.kind === "submitting"}
          onClick={() => void handleRating("down")}
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

      {hasRating && !commentSubmitted ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
          <label
            htmlFor={commentTextareaId}
            style={{ fontSize: 11.5, color: "var(--fg-3)" }}
          >
            Want to tell us more? (optional)
          </label>
          <textarea
            disabled={commentSubmitting}
            id={commentTextareaId}
            maxLength={4096}
            onChange={(event) => setComment(event.target.value)}
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
              disabled={!comment.trim() || commentSubmitting}
              onClick={() => void handleCommentSubmit()}
              style={{ fontSize: 11, padding: "3px 10px" }}
              type="button"
            >
              {commentSubmitting ? "Saving…" : "Send"}
            </button>
            {commentError ? (
              <span
                role="status"
                style={{ fontSize: 11, color: "#fbbf24" }}
              >
                {commentError}
              </span>
            ) : null}
          </div>
        </div>
      ) : null}

      {commentSubmitted ? (
        <div
          aria-live="polite"
          role="status"
          style={{ fontSize: 11, color: "var(--fg-2)" }}
        >
          Thanks for the detail.
        </div>
      ) : null}
    </div>
  );
}
