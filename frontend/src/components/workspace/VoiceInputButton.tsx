"use client";

/**
 * Reusable microphone button that records audio via MediaRecorder,
 * posts it to /workspace/transcribe, and hands the transcribed text
 * to the parent via onTranscript.
 *
 * Used by:
 *   * Resume Builder chat input (flagship surface — users speak
 *     long-form answers about experience instead of typing one-liners)
 *   * Workspace assistant chat (secondary)
 *
 * Mic permission is requested lazily on first click rather than at
 * mount: a workspace user that never wants to talk shouldn't see a
 * permission prompt in the address bar. After permission is granted
 * once, the browser remembers it for the origin so subsequent clicks
 * start recording immediately.
 *
 * Stop behavior: clicking the button again stops the active recording
 * and triggers the transcription POST. The component itself doesn't
 * carry a max-duration timer — both the resume builder and the
 * assistant surfaces care more about long-form answers than capping
 * speakers at N seconds, and the 25 MB body limit at the server
 * effectively bounds a single take at several minutes of webm/opus.
 *
 * Accessibility:
 *   * aria-pressed reflects the recording state (idle vs recording)
 *     so screen readers announce the toggle correctly.
 *   * aria-label updates to reflect the current action ("Start
 *     recording" / "Stop recording"). aria-busy is set during the
 *     post-stop transcription window.
 *   * Pulsing red-dot indicator has aria-hidden because the live
 *     state is announced via aria-pressed / aria-label.
 *   * Disabled state is exposed via the standard `disabled` attribute
 *     so keyboard nav skips a busy / unsupported button.
 */

import { useEffect, useRef, useState } from "react";

import { transcribeAudio } from "@/lib/api";

export type VoiceInputButtonProps = {
  /**
   * Called with the transcribed text once the recording stops and the
   * Whisper response lands. The parent decides whether to replace,
   * append, or merge the existing input value.
   */
  onTranscript: (text: string) => void;
  /**
   * Called when the recording fails (mic denied, transcription error,
   * unsupported browser). The parent renders a toast / notice. The
   * message is already user-facing.
   */
  onError?: (message: string) => void;
  /**
   * Optional override for the button's compact label. Defaults to a
   * mic icon + "Voice" so the surface is recognizable even without
   * the explicit text fallback.
   */
  label?: string;
  /**
   * When true, the parent disables the button (e.g. the chat input is
   * mid-submit and another recording would clobber the in-flight POST).
   */
  disabled?: boolean;
  /**
   * ClassName to forward to the outer button so callers can match the
   * surrounding form's button styling (rd-btn-ghost rd-btn-sm in
   * practice). Defaults to the same combo so the button matches the
   * chat-form aesthetic out of the box.
   */
  className?: string;
};

type RecorderState = "idle" | "requesting" | "recording" | "transcribing";

/**
 * Whether the browser exposes the MediaRecorder + getUserMedia APIs
 * we need. Old Safari / mobile UA quirks: we feature-detect on the
 * client at first render so SSR doesn't blow up trying to touch
 * `navigator.mediaDevices`.
 */
function isVoiceInputSupported(): boolean {
  if (typeof window === "undefined") return false;
  if (typeof navigator === "undefined") return false;
  if (!navigator.mediaDevices?.getUserMedia) return false;
  if (typeof MediaRecorder === "undefined") return false;
  return true;
}

/**
 * Pick a MediaRecorder MIME type the current browser can encode.
 *
 * Chromium/Firefox emit `audio/webm;codecs=opus` happily; Safari is
 * stuck on `audio/mp4`. Letting the browser pick a default works on
 * most paths but Safari sometimes records a 0-byte container without
 * an explicit hint, so we try webm-opus first and fall back to
 * the audio/mp4 path when webm is rejected.
 */
function pickRecorderMimeType(): string {
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"];
  for (const candidate of candidates) {
    if (MediaRecorder.isTypeSupported(candidate)) {
      return candidate;
    }
  }
  // Fall through: let the browser default. Whisper's server-side
  // demuxer is forgiving enough on the common formats that this
  // shouldn't error in practice.
  return "";
}

export function VoiceInputButton({
  onTranscript,
  onError,
  label,
  disabled,
  className,
}: VoiceInputButtonProps) {
  const [state, setState] = useState<RecorderState>("idle");
  const [supported, setSupported] = useState<boolean>(true);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const mimeRef = useRef<string>("audio/webm");
  // Mirror the latest onTranscript/onError props into a ref so the
  // MediaRecorder ``stop`` event listener — registered once when
  // recording starts — reads the FRESH callbacks at firing time, not
  // the snapshot from when the recorder was constructed. Without
  // this, a parent that re-renders with new callback identities
  // between start and stop (e.g. because `question` state changed)
  // would have the stop handler invoke stale callbacks, potentially
  // routing the transcript to the wrong component state. Codex P2
  // on PR #3 round 5.
  const propsRef = useRef({ onTranscript, onError });
  propsRef.current = { onTranscript, onError };
  // Mounted guard. The MediaRecorder ``stop`` event fires whenever
  // the input track ends — including when the unmount cleanup below
  // calls track.stop(). Without this guard, handleRecorderStop would
  // run on an unmounted component, triggering React's "state update
  // on unmounted component" warning and pointless transcribe work.
  // Codex P1 on PR #3 round 5.
  const mountedRef = useRef<boolean>(true);

  // Run the feature detect once on the client after mount — we can't
  // call it during render because `navigator` doesn't exist in SSR.
  useEffect(() => {
    setSupported(isVoiceInputSupported());
  }, []);

  // Stop the mic track when the component unmounts mid-recording so we
  // don't leave the browser's mic indicator on after a route change.
  // Also flips mountedRef so the async handleRecorderStop bails before
  // touching state on an unmounted component.
  useEffect(() => {
    return () => {
      mountedRef.current = false;
      const stream = streamRef.current;
      if (stream) {
        stream.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
      }
    };
  }, []);

  async function startRecording() {
    if (!isVoiceInputSupported()) {
      onError?.(
        "Voice input isn't supported in this browser. Try Chrome, Firefox, or Safari.",
      );
      return;
    }
    setState("requesting");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mime = pickRecorderMimeType();
      const recorder = mime
        ? new MediaRecorder(stream, { mimeType: mime })
        : new MediaRecorder(stream);
      // After construction, the recorder knows what container it
      // actually settled on. Prefer that over a hardcoded
      // "audio/webm" fallback — browsers in the empty-mime path may
      // choose a non-webm container (Safari often produces mp4),
      // and labeling the blob as audio/webm anyway caused the
      // server-side MIME whitelist check to reject perfectly valid
      // recordings. Codex P2 on PR #3.
      mimeRef.current = mime || recorder.mimeType || "audio/webm";
      recorderRef.current = recorder;
      chunksRef.current = [];
      recorder.addEventListener("dataavailable", (event) => {
        if (event.data && event.data.size > 0) {
          chunksRef.current.push(event.data);
        }
      });
      recorder.addEventListener("stop", handleRecorderStop);
      recorder.start();
      setState("recording");
    } catch (error) {
      setState("idle");
      // Clean up any allocated mic stream so the OS-level mic
      // indicator turns off. Without this, if getUserMedia succeeded
      // but MediaRecorder construction / start failed, the tracks
      // stay live and the user sees an unexplained mic-on indicator.
      // CodeRabbit Major on PR #3.
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
      }
      recorderRef.current = null;
      // The most common path here is the user clicking "Block" on the
      // mic permission prompt. The error name is "NotAllowedError" in
      // that case; other browser-specific shapes get a generic
      // fallback. The copy needs to be actionable.
      const message =
        error instanceof Error && error.name === "NotAllowedError"
          ? "Microphone permission was denied. Update your browser settings to allow audio capture, then try again."
          : "Couldn't start the microphone. Check that your device has a working mic and try again.";
      onError?.(message);
    }
  }

  function stopRecording() {
    const recorder = recorderRef.current;
    if (!recorder) return;
    // MediaRecorder.stop() fires the final "dataavailable" event +
    // the "stop" event; we transition state in the "stop" listener so
    // a synchronous click doesn't race the final chunk.
    if (recorder.state === "recording") {
      recorder.stop();
    }
  }

  async function handleRecorderStop() {
    // Tear down the mic stream before the POST: the recording is
    // already complete and the user shouldn't see the OS-level mic
    // indicator while we're waiting on Whisper. The local Blob carries
    // the captured audio without needing the live tracks.
    const stream = streamRef.current;
    if (stream) {
      stream.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }

    const chunks = chunksRef.current;
    chunksRef.current = [];
    recorderRef.current = null;

    // If the component already unmounted (typical path: the unmount
    // cleanup stopped the stream, MediaRecorder fired ``stop`` in
    // response, and we landed here), bail before touching state or
    // invoking parent callbacks. Stream is already torn down so
    // nothing leaks. Codex P1 on PR #3 round 5.
    if (!mountedRef.current) return;

    // Read the LATEST callbacks via propsRef so a parent re-render
    // mid-recording doesn't leave us calling stale closure values.
    const currentProps = propsRef.current;

    if (!chunks.length) {
      // Browser stopped without buffering anything (rare — usually a
      // permission revoke during recording or a system audio service
      // glitch). Treat as a soft failure.
      setState("idle");
      currentProps.onError?.("No audio captured. Try recording again.");
      return;
    }
    const blob = new Blob(chunks, { type: mimeRef.current });
    if (blob.size === 0) {
      setState("idle");
      currentProps.onError?.("Empty recording — make sure your mic is unmuted and try again.");
      return;
    }

    setState("transcribing");
    try {
      const result = await transcribeAudio(blob);
      // Second mountedRef check: the await is multi-second (Whisper
      // round-trip) and the user may navigate during it. Skip
      // post-await state updates if we've unmounted.
      if (!mountedRef.current) return;
      const text = (result.text || "").trim();
      if (text) {
        currentProps.onTranscript(text);
      } else {
        currentProps.onError?.(
          "We couldn't make out any words in that recording. Try speaking more clearly or recording in a quieter spot.",
        );
      }
    } catch (error) {
      if (!mountedRef.current) return;
      const message =
        error instanceof Error && error.message
          ? error.message
          : "Voice transcription failed. Try recording again.";
      currentProps.onError?.(message);
    } finally {
      if (mountedRef.current) {
        setState("idle");
      }
    }
  }

  function handleClick() {
    if (state === "recording") {
      stopRecording();
      return;
    }
    if (state === "idle") {
      void startRecording();
    }
  }

  const isRecording = state === "recording";
  const isBusy = state === "requesting" || state === "transcribing";
  const buttonLabel = isRecording
    ? "Stop recording"
    : state === "transcribing"
      ? "Transcribing"
      : state === "requesting"
        ? "Starting microphone"
        : (label ?? "Voice");

  return (
    <button
      aria-label={
        isRecording
          ? "Stop recording"
          : state === "transcribing"
            ? "Transcribing audio"
            : "Start voice recording"
      }
      aria-pressed={isRecording}
      aria-busy={isBusy}
      className={className ?? "rd-btn rd-btn-ghost rd-btn-sm"}
      data-recording={isRecording ? "true" : undefined}
      disabled={!supported || disabled || isBusy}
      onClick={handleClick}
      title={
        !supported
          ? "Voice input isn't supported in this browser."
          : isRecording
            ? "Stop recording and transcribe"
            : "Record a voice note"
      }
      type="button"
    >
      <span
        aria-hidden="true"
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
        }}
      >
        {isRecording ? (
          // Pulsing red dot while recording. CSS keyframes in the
          // existing globals.css don't include a `pulse` animation yet
          // — inline keyframes via a style tag would over-complicate
          // the surface. We rely on a subtle scale via inline style
          // animation so a user can't tell whether the recording is
          // active just from a static screenshot.
          <span
            style={{
              display: "inline-block",
              width: 10,
              height: 10,
              borderRadius: "50%",
              background: "#ef4444",
              animation: "voice-pulse 1.2s ease-in-out infinite",
            }}
          />
        ) : (
          <MicIcon />
        )}
        <span>{buttonLabel}</span>
      </span>
      {/* Keyframes defined inline so the button is self-contained;
          adding a new global rule for one component would bloat the
          stylesheet. The animation reduces gracefully for users with
          `prefers-reduced-motion` via the media query below. */}
      <style jsx>{`
        @keyframes voice-pulse {
          0%, 100% {
            transform: scale(1);
            opacity: 1;
          }
          50% {
            transform: scale(1.4);
            opacity: 0.6;
          }
        }
        @media (prefers-reduced-motion: reduce) {
          span[style*="animation"] {
            animation: none !important;
          }
        }
      `}</style>
    </button>
  );
}

function MicIcon() {
  return (
    <svg
      aria-hidden="true"
      fill="none"
      height="14"
      viewBox="0 0 20 20"
      width="14"
    >
      <path
        d="M10 3a2.5 2.5 0 0 0-2.5 2.5v4a2.5 2.5 0 0 0 5 0v-4A2.5 2.5 0 0 0 10 3Z"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.4"
      />
      <path
        d="M5 9.5a5 5 0 0 0 10 0M10 14.5v2.5M7.5 17h5"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.4"
      />
    </svg>
  );
}
