import type { JobPosting } from "@/lib/api-types";

export type WorkspaceStage = {
  title: string;
  note: string;
  state: "live" | "ready" | "next";
};

export type WorkspaceLane = {
  title: string;
  status: string;
  body: string;
  bullets: string[];
};

export type JobReview = {
  summaryCards: Array<{
    label: string;
    value: string;
    note: string;
  }>;
  hardSkills: string[];
  softSkills: string[];
  mustHaves: string[];
  niceToHaves: string[];
  summarySections: Array<{
    title: string;
    items: string[];
  }>;
};

const HARD_SKILL_KEYWORDS = [
  "Python",
  "SQL",
  "FastAPI",
  "Docker",
  "Kubernetes",
  "AWS",
  "GCP",
  "Azure",
  "TypeScript",
  "JavaScript",
  "React",
  "Next.js",
  "Node.js",
  "PostgreSQL",
  "Machine Learning",
  "LLMs",
  "RAG",
  "Prompt Engineering",
  "Data Engineering",
  "System Design",
  "GraphQL",
  "Terraform",
  "Pandas",
  "PyTorch",
  "TensorFlow",
];

const SOFT_SKILL_KEYWORDS = [
  "Communication",
  "Leadership",
  "Collaboration",
  "Stakeholder Management",
  "Mentorship",
  "Problem Solving",
  "Ownership",
  "Cross-Functional Partnership",
  "Adaptability",
  "Initiative",
  "Strategy",
];

function normalizeText(value: string) {
  return value.replace(/\s+/g, " ").trim();
}

function uniqueMatches(text: string, labels: string[]) {
  const normalized = text.toLowerCase();
  const matches: string[] = [];
  for (const label of labels) {
    if (normalized.includes(label.toLowerCase())) {
      matches.push(label);
    }
  }
  return matches;
}

function splitSignals(text: string) {
  const fromLines = text
    .split(/\n+/)
    .map((line) => line.replace(/^[-*•\s]+/, "").trim())
    .filter(Boolean);

  if (fromLines.length >= 4) {
    return fromLines;
  }

  return text
    .split(/(?<=[.!?])\s+/)
    .map((sentence) => sentence.trim())
    .filter(Boolean);
}

function pickSignals(lines: string[], pattern: RegExp, limit: number) {
  return lines.filter((line) => pattern.test(line)).slice(0, limit);
}

function getMetadataList(job: JobPosting | null, key: string) {
  const value = job?.metadata?.[key];
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => String(item || "").trim())
    .filter(Boolean)
    .slice(0, 4);
}

function extractCompensation(text: string) {
  const normalized = normalizeText(text);
  const match = normalized.match(
    /\$\s?\d[\d,]*(?:\.\d+)?(?:\s*(?:-|to)\s*\$?\s?\d[\d,]*(?:\.\d+)?)?(?:\s*(?:USD|CAD|EUR|GBP|AUD|INR|per year|annually))?/i,
  );
  return match?.[0]?.trim() ?? "";
}

export function formatPostedLabel(postedAt: string) {
  return postedAt ? postedAt.slice(0, 10) : "";
}

export function buildJobResultBadges(job: JobPosting) {
  const badges = [
    job.employment_type,
    job.location,
    formatPostedLabel(job.posted_at)
      ? `Posted ${formatPostedLabel(job.posted_at)}`
      : "",
  ];

  const departments = getMetadataList(job, "departments");
  if (departments.length) {
    badges.push(departments[0]);
  }

  return badges.filter(Boolean).slice(0, 4);
}

export function buildSourceCoverage(sourceStatus: Record<string, string>) {
  const boardEntries = Object.entries(sourceStatus).filter(
    ([key]) => !["backend", "greenhouse", "lever"].includes(key),
  );

  if (!boardEntries.length) {
    return null;
  }

  let matched = 0;
  let noMatch = 0;
  let unavailable = 0;

  for (const [, value] of boardEntries) {
    if (value === "matched") {
      matched += 1;
    } else if (value === "error") {
      unavailable += 1;
    } else {
      noMatch += 1;
    }
  }

  return {
    searched: boardEntries.length,
    matched,
    noMatch,
    unavailable,
  };
}

export function buildJobReview(text: string, job: JobPosting | null): JobReview {
  const normalized = normalizeText(text);
  const lines = splitSignals(text);
  const hardSkills = uniqueMatches(normalized, HARD_SKILL_KEYWORDS);
  const softSkills = uniqueMatches(normalized, SOFT_SKILL_KEYWORDS);
  const mustHaves = pickSignals(
    lines,
    /(must|required|requirement|experience with|proficiency|hands-on|strong)/i,
    4,
  );
  const niceToHaves = pickSignals(
    lines,
    /(nice to have|preferred|bonus|plus|good to have|familiarity)/i,
    3,
  );
  const departments = getMetadataList(job, "departments");
  const offices = getMetadataList(job, "offices");
  const compensation = extractCompensation(text);
  const postedLabel = formatPostedLabel(job?.posted_at ?? "");

  const summaryCards = [
    {
      label: "Target Role",
      value: job?.title || lines[0] || "Manual JD",
      note: "Primary role title carried into the workflow.",
    },
    {
      label: "Company",
      value: job?.company || "",
      note: "Employer tied to the imported posting.",
    },
    {
      label: "Location",
      value: job?.location || offices[0] || "",
      note: "Location or office signal extracted from the JD.",
    },
    {
      label: "Compensation",
      value: compensation,
      note: "Compensation text detected directly from the JD copy.",
    },
    {
      label: "Posted",
      value: postedLabel,
      note: "Source posting date reported by the provider.",
    },
    {
      label: "Hard Skills",
      value: hardSkills.length ? String(hardSkills.length) : "",
      note: "Keyword-based skill matches visible in the current text.",
    },
  ].filter((card) => card.value);

  const roleSnapshot = [
    job?.summary || "",
    departments.length ? `Primary team: ${departments.join(", ")}` : "",
    offices.length ? `Office signals: ${offices.join(", ")}` : "",
  ].filter(Boolean);

  const responsibilities = lines
    .filter(
      (line) =>
        !/(nice to have|preferred|bonus|plus|good to have)/i.test(line) &&
        line.length > 28,
    )
    .slice(0, 4);

  const summarySections = [
    {
      title: "Role Snapshot",
      items: roleSnapshot.length
        ? roleSnapshot
        : [`${job?.title || "This role"} is now loaded into the workspace review lane.`],
    },
    {
      title: "Core Responsibilities",
      items: responsibilities.length
        ? responsibilities
        : ["Paste a fuller JD or import a supported role to expand this review."],
    },
    {
      title: "Must-Have Themes",
      items: mustHaves.length
        ? mustHaves
        : ["No explicit must-have lines were detected yet in the current text."],
    },
    {
      title: "Nice-to-Have Signals",
      items: niceToHaves.length
        ? niceToHaves
        : ["No explicit nice-to-have signals were detected yet."],
    },
  ];

  return {
    summaryCards,
    hardSkills,
    softSkills,
    mustHaves,
    niceToHaves,
    summarySections,
  };
}

export const stagedLanes: WorkspaceLane[] = [
  {
    title: "Resume Intake",
    status: "API contract next",
    body:
      "The Streamlit flow currently owns upload, parsing feedback, saved workspace restore, and candidate snapshot state.",
    bullets: [
      "Upload and parser progress panel",
      "Candidate profile snapshot",
      "Saved workspace restore and plan gating",
    ],
  },
  {
    title: "Agentic Analysis",
    status: "Workflow endpoint next",
    body:
      "The orchestration core already exists in Python. The frontend is waiting on run, progress, and result endpoints.",
    bullets: [
      "Scout, signal, matchmaker, and review progress",
      "Quota-aware run trigger",
      "Grounded fit and report-ready payloads",
    ],
  },
  {
    title: "Artifacts",
    status: "Retrieval endpoint next",
    body:
      "Tailored resume, cover letter, and report outputs need fetchable resources instead of Streamlit-rendered panels.",
    bullets: [
      "Artifact tabs and export actions",
      "Theme-aware resume rendering",
      "Markdown and PDF download states",
    ],
  },
  {
    title: "Assistant",
    status: "Session model next",
    body:
      "The assistant needs an API-backed session boundary before the richer chat panel can replace Streamlit session memory.",
    bullets: [
      "Shared context and grounded follow-ups",
      "Product-help and package QA routing",
      "Resettable conversation memory",
    ],
  },
];
