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
