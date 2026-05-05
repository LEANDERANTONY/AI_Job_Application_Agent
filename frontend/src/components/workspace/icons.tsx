// Pure presentational icon components extracted from
// `job-application-workspace.tsx` as the first step of the Item 2
// frontend split (see `docs/NEXT-STEPS-FRONTEND.md`).
//
// No "use client" directive: these components have no hooks or
// client-only APIs, so they can be imported by both Server and
// Client components.

export function ResumeMetricIcon() {
  return (
    <svg aria-hidden="true" fill="none" viewBox="0 0 20 20">
      <path
        d="M6.25 2.75h4.4l3.1 3.1v11.4H6.25V2.75Z"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
      />
      <path
        d="M10.65 2.75v3.1h3.1M8 10h4M8 13h4"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.5"
      />
    </svg>
  );
}

export function WorkflowMetricIcon() {
  return (
    <svg aria-hidden="true" fill="none" viewBox="0 0 20 20">
      <path
        d="M10 3.5v2.1M10 14.4v2.1M5.6 5.6l1.5 1.5M12.9 12.9l1.5 1.5M3.5 10h2.1M14.4 10h2.1M5.6 14.4l1.5-1.5M12.9 7.1l1.5-1.5"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="1.5"
      />
      <circle
        cx="10"
        cy="10"
        r="3.1"
        stroke="currentColor"
        strokeWidth="1.5"
      />
    </svg>
  );
}

export function ArtifactMetricIcon() {
  return (
    <svg aria-hidden="true" fill="none" viewBox="0 0 20 20">
      <path
        d="M10 3.2l1.35 3.2 3.45 1.35-3.45 1.35L10 12.4 8.65 9.1 5.2 7.75 8.65 6.4 10 3.2Z"
        stroke="currentColor"
        strokeLinejoin="round"
        strokeWidth="1.5"
      />
      <path
        d="M14.65 12.7l.7 1.65 1.65.7-1.65.7-.7 1.65-.7-1.65-1.65-.7 1.65-.7.7-1.65ZM5.35 11.8l.5 1.15 1.15.5-1.15.5-.5 1.15-.5-1.15-1.15-.5 1.15-.5.5-1.15Z"
        stroke="currentColor"
        strokeLinejoin="round"
        strokeWidth="1.4"
      />
    </svg>
  );
}

// ── Direction B ("Workbench") icon set ───────────────────────────
// Stroke-style monoline icons reused across the redesigned workspace
// (topbar trigger, command palette, FAB, intake panels, job rows).

export function SearchIcon() {
  return (
    <svg
      aria-hidden="true"
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
    >
      <circle cx="7" cy="7" r="5" />
      <path d="m11 11 3 3" />
    </svg>
  );
}

export function PinIcon() {
  return (
    <svg
      aria-hidden="true"
      width="14"
      height="14"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M8 1v6l3 3v1H5v-1l3-3V1z" />
      <path d="M8 11v4" />
    </svg>
  );
}

export function ExternalIcon() {
  return (
    <svg
      aria-hidden="true"
      width="12"
      height="12"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
    >
      <path d="M9 2h5v5" />
      <path d="M14 2 7 9" />
      <path d="M11 9v4H3V5h4" />
    </svg>
  );
}

export function SendIcon() {
  return (
    <svg
      aria-hidden="true"
      width="14"
      height="14"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="m2 14 12-6L2 2l2 6-2 6z" />
    </svg>
  );
}

export function SparkleIcon() {
  return (
    <svg
      aria-hidden="true"
      width="18"
      height="18"
      viewBox="0 0 18 18"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M9 2v4M9 12v4M2 9h4M12 9h4M4 4l2.5 2.5M11.5 11.5 14 14M14 4l-2.5 2.5M6.5 11.5 4 14" />
    </svg>
  );
}

export function CheckIcon() {
  return (
    <svg
      aria-hidden="true"
      width="11"
      height="11"
      viewBox="0 0 12 12"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="m2 6 3 3 5-6" />
    </svg>
  );
}

export function CloseIcon() {
  return (
    <svg
      aria-hidden="true"
      width="14"
      height="14"
      viewBox="0 0 14 14"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
    >
      <path d="m3 3 8 8M11 3l-8 8" />
    </svg>
  );
}

export function UploadIcon() {
  return (
    <svg
      aria-hidden="true"
      width="16"
      height="16"
      viewBox="0 0 16 16"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M8 11V2M5 5l3-3 3 3" />
      <path d="M2 11v2a1 1 0 0 0 1 1h10a1 1 0 0 0 1-1v-2" />
    </svg>
  );
}

export function PlayIcon() {
  return (
    <svg
      aria-hidden="true"
      width="11"
      height="11"
      viewBox="0 0 12 12"
      fill="currentColor"
    >
      <path d="M3 2v8l7-4z" />
    </svg>
  );
}

export function StarIcon() {
  return (
    <svg aria-hidden="true" viewBox="0 0 12 12" fill="currentColor">
      <path d="M6 .5l1.6 3.4 3.7.5-2.7 2.6.6 3.7L6 8.9 2.8 10.7l.6-3.7L.7 4.4l3.7-.5z" />
    </svg>
  );
}

export function ChevronRightIcon() {
  return (
    <svg
      aria-hidden="true"
      width="11"
      height="11"
      viewBox="0 0 11 11"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
    >
      <path d="M3.5 2L7 5.5L3.5 9" />
    </svg>
  );
}
