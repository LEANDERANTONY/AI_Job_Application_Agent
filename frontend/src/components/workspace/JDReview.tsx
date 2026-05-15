"use client";

// JD upload + manual input + review surface — Direction B redesign.
//
// Behavior preservation:
//   - Paste mode → parse from textarea
//   - URL mode → resolve via parent's onResolveUrl flow (handled in shell)
//   - File mode → onJobDescriptionUpload
//   - Hard/soft skills render parser output verbatim (no reorder/dedupe)
//   - Match-score / metric values come from JobSummaryView when fresh, or
//     `review.summaryCards` when working off the live `manualJobText`
//   - Stale notice shown when analysis is out-of-date with current inputs
//
// Layout (per handoff specs/03-jd.md):
//   1. b-intake-panel — upload + paste textarea + clear
//   2. b-resume-hero (re-used) — parsed-JD hero w/ b-jd-metrics row
//   3. b-twoup-section — Summary block (full-width)
//   4. b-resume-twoup — Hard skills + Soft skills
//   5. b-jd-block list — one per parser-returned section

import { useEffect, useRef, useState, type ChangeEvent } from "react";

import { UploadIcon } from "@/components/workspace/icons";
import { CollapsibleSection } from "@/components/workspace/CollapsibleSection";
import { FeedbackButtons } from "@/components/workspace/FeedbackButtons";

// Count-up animation for the big JD metric numbers. Animates from 0
// to the parsed integer over ~600ms using requestAnimationFrame, then
// holds. Skips animation when the user prefers reduced motion. Falls
// back to the literal value verbatim when it's not a clean integer
// (e.g. "5+" → renders as-is).
function useCountUp(target: string, durationMs = 600): string {
  const numeric = Number.parseInt(target.replace(/[^\d]/g, ""), 10);
  const isNumeric = Number.isFinite(numeric) && /^\d/.test(target);
  const [value, setValue] = useState(isNumeric ? 0 : numeric);
  const lastTarget = useRef<number>(numeric);

  useEffect(() => {
    if (!isNumeric) return;
    const prefersReduced =
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (prefersReduced) {
      setValue(numeric);
      lastTarget.current = numeric;
      return;
    }
    if (lastTarget.current === numeric && value === numeric) return;
    lastTarget.current = numeric;
    let raf = 0;
    const start = performance.now();
    const startValue = 0;
    const tick = (now: number) => {
      const elapsed = now - start;
      const ratio = Math.min(elapsed / durationMs, 1);
      // Ease-out-cubic for a snappy entry that decelerates.
      const eased = 1 - Math.pow(1 - ratio, 3);
      setValue(Math.round(startValue + (numeric - startValue) * eased));
      if (ratio < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [numeric, isNumeric, durationMs]);

  if (!isNumeric) return target;
  // Preserve any trailing characters (e.g. the "+" in "5+") once we've
  // reached the target. While animating, just show the integer.
  const trailing = target.replace(/^\d+/, "");
  return value < numeric ? String(value) : `${numeric}${trailing}`;
}

// Small wrapper so the count-up hook fires per-metric inside the map.
function JDMetricValue({
  value,
  unit,
}: {
  value: string;
  unit: string;
}) {
  const display = useCountUp(value);
  return (
    <div className="b-jd-metric-value">
      {display}
      {unit ? <span className="b-jd-metric-unit">{unit}</span> : null}
    </div>
  );
}
import type {
  JobPosting,
  WorkspaceAnalysisResponse,
  WorkspaceJobDescriptionUploadResponse,
} from "@/lib/api-types";
import {
  buildSectionParagraphs,
  type JobReview,
} from "@/lib/job-workspace";

export type JDReviewNotice = {
  level: "info" | "success" | "warning";
  message: string;
};

function noticeClassName(level: JDReviewNotice["level"]) {
  if (level === "success") return "b-notice b-notice-success";
  if (level === "warning") return "b-notice b-notice-warning";
  return "b-notice";
}

export type JDReviewProps = {
  analysisState: WorkspaceAnalysisResponse | null;
  analysisIsStale: boolean;
  /** Result of `buildJobReview(...)`, or `null` when no JD text yet. */
  review: JobReview | null;
  manualJobText: string;
  onManualJobTextChange: (value: string) => void;
  selectedJobFile: File | null;
  onSelectedJobFileChange: (file: File | null) => void;
  jobFileState: WorkspaceJobDescriptionUploadResponse | null;
  jobFileUploading: boolean;
  jobFileNotice: JDReviewNotice | null;
  activeJob: JobPosting | null;
  jobInputCollapsed: boolean;
  onToggleJobInputCollapsed: () => void;
  onJobDescriptionUpload: (file: File | null) => void;
  onClearLoadedJobDescription: () => void;
};

function summaryHeadlineFromAnalysis(
  analysis: WorkspaceAnalysisResponse | null,
): string | null {
  if (!analysis) return null;
  return analysis.jd_summary_view?.summary || null;
}

export function JDReview({
  analysisState,
  analysisIsStale,
  review,
  manualJobText,
  onManualJobTextChange,
  selectedJobFile,
  onSelectedJobFileChange,
  jobFileState,
  jobFileUploading,
  jobFileNotice,
  activeJob,
  jobInputCollapsed,
  onToggleJobInputCollapsed,
  onJobDescriptionUpload,
  onClearLoadedJobDescription,
}: JDReviewProps) {
  function handleFileInputChange(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0] ?? null;
    onSelectedJobFileChange(file);
    onJobDescriptionUpload(file);
    event.target.value = "";
  }

  const heroTitle =
    activeJob?.title ||
    jobFileState?.job_description.title ||
    analysisState?.job_description.title ||
    review?.summaryCards.find((card) => card.label === "Target Role")?.value ||
    "Job description";

  const heroCompany =
    activeJob?.company ||
    review?.summaryCards.find((card) => card.label === "Company")?.value ||
    "";

  const heroLocation =
    activeJob?.location ||
    review?.summaryCards.find((card) => card.label === "Location")?.value ||
    "";

  const heroSource =
    activeJob?.source ||
    (jobFileState ? "Uploaded file" : review ? "Pasted text" : "");

  // Hero metrics: prefer the parsed analysisState numbers when fresh,
  // fall back to the JobReview computed by `buildJobReview` from the
  // current manualJobText.
  const metrics = (() => {
    if (analysisState && !analysisIsStale) {
      const fit = analysisState.fit_analysis;
      return [
        {
          label: "Match score",
          value: String(fit.overall_score ?? 0),
          unit: "%",
        },
        {
          label: "Hard skills",
          value: String(
            analysisState.job_description.requirements.hard_skills.length,
          ),
          unit: "",
        },
        {
          label: "Years required",
          value: analysisState.job_description.requirements
            .experience_requirement
            ? analysisState.job_description.requirements.experience_requirement
                .replace(/[^0-9+]/g, "")
                .slice(0, 4) || "—"
            : "—",
          unit: "",
        },
      ];
    }
    if (review) {
      return [
        {
          label: "Hard skills",
          value: String(review.hardSkills.length),
          unit: "",
        },
        {
          label: "Soft skills",
          value: String(review.softSkills.length),
          unit: "",
        },
        {
          label: "Must-haves",
          value: String(review.mustHaves.length),
          unit: "",
        },
      ];
    }
    return [];
  })();

  const summaryText =
    (analysisState && !analysisIsStale && summaryHeadlineFromAnalysis(analysisState)) ||
    review?.summarySections.find((section) => section.title === "Role Snapshot")
      ?.items?.[0] ||
    null;

  const hardSkills =
    analysisState && !analysisIsStale
      ? analysisState.job_description.requirements.hard_skills
      : (review?.hardSkills ?? []);
  const softSkills =
    analysisState && !analysisIsStale
      ? analysisState.job_description.requirements.soft_skills
      : (review?.softSkills ?? []);

  const bodySections =
    analysisState && !analysisIsStale
      ? analysisState.jd_summary_view.sections
      : (review?.summarySections.filter(
          (section) => section.title !== "Role Snapshot",
        ) ?? []);

  const inputBodyVisible = !jobInputCollapsed;

  return (
    <div className="b-region">
      {/* 1 — Intake panel: upload + paste textarea */}
      <div className="b-intake-panel">
        <div className="b-intake-head">
          <div>
            <div className="b-section-label">Step 03 · Import JD</div>
            <div className="b-intake-title">Bring in the job description</div>
          </div>
          <div className="b-intake-head-actions">
            {review ? (
              <button
                className="rd-btn rd-btn-ghost rd-btn-sm"
                onClick={onToggleJobInputCollapsed}
                type="button"
              >
                {jobInputCollapsed ? "Show JD input" : "Hide JD input"}
              </button>
            ) : null}
            {jobFileState || activeJob || manualJobText.trim() ? (
              <button
                className="rd-btn rd-btn-danger rd-btn-sm"
                onClick={onClearLoadedJobDescription}
                type="button"
              >
                Clear
              </button>
            ) : null}
          </div>
        </div>

        {inputBodyVisible ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <div
              style={{
                display: "flex",
                gap: 8,
                alignItems: "center",
                flexWrap: "wrap",
              }}
            >
              <label
                className="rd-btn rd-btn-ghost rd-btn-sm"
                htmlFor="job-description-upload"
              >
                <UploadIcon /> Upload file
              </label>
              <input
                accept=".pdf,.docx,.txt"
                id="job-description-upload"
                onChange={handleFileInputChange}
                style={{ display: "none" }}
                type="file"
              />
              <span
                className="rd-mono"
                style={{ fontSize: 12, color: "var(--fg-3)" }}
              >
                {selectedJobFile?.name ||
                  jobFileState?.job_description.title ||
                  "or paste below"}
              </span>
              {jobFileUploading ? (
                <span style={{ fontSize: 12, color: "var(--fg-3)" }}>
                  Parsing JD…
                </span>
              ) : null}
            </div>

            {jobFileNotice ? (
              <div className={noticeClassName(jobFileNotice.level)}>
                {jobFileNotice.message}
              </div>
            ) : null}

            <textarea
              className="rd-textarea"
              onChange={(event) => onManualJobTextChange(event.target.value)}
              placeholder="Paste a job description here, or load one from job search."
              style={{ minHeight: 220 }}
              value={manualJobText}
            />
          </div>
        ) : null}
      </div>

      {/* 2 — Parsed JD hero (only when we have something to show) */}
      {review || analysisState ? (
        <div className="b-resume-hero">
          <span className="b-resume-hero-pill">Parsed JD</span>
          <h1 className="b-resume-hero-title">{heroTitle}</h1>
          <div className="b-resume-hero-meta">
            {heroCompany ? <span>{heroCompany}</span> : null}
            {heroLocation ? <span>{heroLocation}</span> : null}
            {heroSource ? <span>Source · {heroSource}</span> : null}
          </div>
          {metrics.length ? (
            <div className="b-jd-metrics">
              {metrics.map((metric) => (
                <div className="b-jd-metric" key={metric.label}>
                  <div className="b-jd-metric-label">{metric.label}</div>
                  <JDMetricValue unit={metric.unit} value={metric.value} />
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      {analysisIsStale ? (
        <div className="b-notice b-notice-warning">
          The inputs changed after the last run. Re-run the workflow to refresh
          the analysis-derived fields.
        </div>
      ) : null}

      {/* 3 — Summary block (collapsible) */}
      {summaryText ? (
        <CollapsibleSection sub="At a glance" title="Summary">
          <p
            style={{
              fontSize: 13.5,
              lineHeight: 1.7,
              color: "var(--fg-2)",
              margin: 0,
            }}
          >
            {summaryText}
          </p>
          {/* Online feedback for the JD summary — surfaces the LLM-
              produced narrative directly to the user so a stale /
              hallucinated paragraph gets caught fast. */}
          <FeedbackButtons
            surface="jd_summary"
            prompt="Was this summary accurate?"
          />
        </CollapsibleSection>
      ) : null}

      {/* 4 — Hard / Soft skills two-up (each collapsible) */}
      {review || analysisState ? (
        <div className="b-resume-twoup">
          <CollapsibleSection
            sub={`${hardSkills.length} required`}
            title="Hard skills"
          >
            {hardSkills.length ? (
              <div className="b-skill-chips">
                {hardSkills.map((skill, index) => (
                  <span
                    className="b-skill-chip"
                    data-tone={index % 3 === 0 ? "bold" : undefined}
                    key={skill}
                  >
                    {skill}
                  </span>
                ))}
              </div>
            ) : (
              <div className="b-twoup-empty">
                No explicit hard-skill keywords detected yet.
              </div>
            )}
          </CollapsibleSection>
          <CollapsibleSection
            sub={`${softSkills.length} signals`}
            title="Soft skills"
          >
            {softSkills.length ? (
              <div className="b-skill-chips">
                {softSkills.map((skill) => (
                  <span className="b-skill-chip" key={skill}>
                    {skill}
                  </span>
                ))}
              </div>
            ) : (
              <div className="b-twoup-empty">
                No explicit soft-skill signals detected yet.
              </div>
            )}
          </CollapsibleSection>
        </div>
      ) : null}

      {/* 5 — JD body sections rendered as a single editorial document.
          Each parser-returned heading + its paragraphs flow inside one
          card with hairline-divided sections instead of stacked
          bordered cards (less dashboard-y). */}
      {bodySections.length ? (
        <div className="b-doc">
          {bodySections.map((section, index) => {
            const paragraphs = buildSectionParagraphs(section.items);
            return (
              <CollapsibleSection
                index={String(index + 1).padStart(2, "0")}
                key={section.title}
                title={section.title}
                variant="bare"
              >
                <div className="b-jd-block-body">
                  {paragraphs.map((paragraph) => (
                    <p key={paragraph}>{paragraph}</p>
                  ))}
                </div>
              </CollapsibleSection>
            );
          })}
        </div>
      ) : null}

      {!review && !analysisState ? (
        <div className="b-empty-hint">
          <div className="b-empty-hint-eyebrow">Once a JD is loaded</div>
          <div className="b-empty-hint-body">
            The parsed hero, hard / soft skills, and structured body sections
            will appear here. Paste a JD or upload a file above to begin.
          </div>
        </div>
      ) : null}
    </div>
  );
}
