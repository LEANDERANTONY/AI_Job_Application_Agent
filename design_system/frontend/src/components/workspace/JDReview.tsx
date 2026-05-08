"use client";

// JD upload + manual input + review surface — extracted from
// `job-application-workspace.tsx` as part of the Item 2 frontend split
// (see `docs/NEXT-STEPS-FRONTEND.md`).
//
// Owns the markup for `mainTab === "jd"`. State stays in the parent
// for now and is passed down as props; the lift to the Zustand store
// lands alongside the JD slice in a later commit.

import type { ChangeEvent } from "react";

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
  if (level === "success") {
    return "notice-panel notice-success";
  }
  if (level === "warning") {
    return "notice-panel notice-warning";
  }
  return "notice-panel notice-info";
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
  /** Called when the user picks a file from the upload input. */
  onJobDescriptionUpload: (file: File | null) => void;
  onClearLoadedJobDescription: () => void;
};

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

  return (
    <section className="surface-card surface-card-neutral">
      <div className="section-head">
        <div>
          <p className="eyebrow">Step 3</p>
          <h2 className="section-title">JD upload, manual input, and review</h2>
        </div>
        <div className="section-head-actions">
          <span className="status-chip">
            {review ? "Ready" : "Waiting for JD text"}
          </span>
          {review ? (
            <button
              className="secondary-button workspace-button workspace-button-small"
              onClick={onToggleJobInputCollapsed}
              type="button"
            >
              {jobInputCollapsed ? "Show JD input" : "Hide JD input"}
            </button>
          ) : null}
        </div>
      </div>
      <p className="section-copy">
        Paste a JD directly, load one from search, or upload a JD file. All
        three paths meet here.
      </p>

      {!jobInputCollapsed ? (
        <div className="workspace-jd-stack">
          <div className="workspace-jd-load-panel">
            <div className="workspace-uploader">
              <label
                className="primary-button workspace-button"
                htmlFor="job-description-upload"
              >
                Upload JD
              </label>
              <input
                accept=".pdf,.docx,.txt"
                className="workspace-hidden-input"
                id="job-description-upload"
                onChange={handleFileInputChange}
                type="file"
              />
              <span className="workspace-file-name">
                {selectedJobFile?.name ||
                  jobFileState?.job_description.title ||
                  "No JD file selected"}
              </span>
              {jobFileUploading ? (
                <span className="workspace-file-status">Parsing JD...</span>
              ) : null}
              {jobFileState || activeJob || manualJobText.trim() ? (
                <button
                  className="danger-button workspace-button workspace-action-end"
                  onClick={onClearLoadedJobDescription}
                  type="button"
                >
                  Clear uploaded JD
                </button>
              ) : null}
            </div>

            {jobFileNotice ? (
              <div className={noticeClassName(jobFileNotice.level)}>
                {jobFileNotice.message}
              </div>
            ) : null}

            <textarea
              className="workspace-textarea"
              onChange={(event) => onManualJobTextChange(event.target.value)}
              placeholder="Paste a job description here, or load one from job search."
              value={manualJobText}
            />
          </div>
        </div>
      ) : null}

      <div className="workspace-jd-stack">
        <div className="workspace-section-card">
          <div className="section-head">
            <div>
              <p className="eyebrow">Review lane</p>
              <h2 className="section-title">JD summary</h2>
            </div>
            <span className="status-chip">
              {activeJob
                ? `Imported from ${activeJob.source}`
                : jobFileState
                  ? "Ready"
                  : review
                    ? "Ready"
                    : "Waiting"}
            </span>
          </div>

          {review ? (
            <>
              <div className="workspace-summary-grid">
                {review.summaryCards.map((card) => (
                  <div className="metric-tile" key={card.label}>
                    <span>{card.label}</span>
                    <strong>{card.value}</strong>
                    <small>{card.note}</small>
                  </div>
                ))}
              </div>

              <div className="workspace-review-columns">
                <div className="soft-panel">
                  <span className="soft-panel-label">Hard skills</span>
                  <div className="workspace-chip-grid">
                    {review.hardSkills.length ? (
                      review.hardSkills.map((skill) => (
                        <span className="workspace-meta-chip" key={skill}>
                          {skill}
                        </span>
                      ))
                    ) : (
                      <p className="workspace-muted-copy">
                        No explicit hard skills detected yet in the current
                        text.
                      </p>
                    )}
                  </div>
                </div>

                <div className="soft-panel">
                  <span className="soft-panel-label">Soft skills</span>
                  <div className="workspace-chip-grid">
                    {review.softSkills.length ? (
                      review.softSkills.map((skill) => (
                        <span className="workspace-meta-chip" key={skill}>
                          {skill}
                        </span>
                      ))
                    ) : (
                      <p className="workspace-muted-copy">
                        No explicit soft-skill signals detected yet in the
                        current text.
                      </p>
                    )}
                  </div>
                </div>
              </div>

              {analysisState && !analysisIsStale ? (
                <div className="workspace-section-stack workspace-jd-sections">
                  {analysisState.jd_summary_view.sections.map((section) => (
                    <div
                      className="workspace-section-card workspace-jd-section-card"
                      key={section.title}
                    >
                      <h3>{section.title}</h3>
                      <div className="workspace-jd-paragraphs">
                        {buildSectionParagraphs(section.items).map(
                          (paragraph) => (
                            <p key={paragraph}>{paragraph}</p>
                          ),
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="workspace-section-stack workspace-jd-sections">
                  {review.summarySections.map((section) => (
                    <div
                      className="workspace-section-card workspace-jd-section-card"
                      key={section.title}
                    >
                      <h3>{section.title}</h3>
                      <div className="workspace-jd-paragraphs">
                        {buildSectionParagraphs(section.items).map(
                          (paragraph) => (
                            <p key={paragraph}>{paragraph}</p>
                          ),
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : (
            <div className="workspace-empty-state">
              Once a job description is present, this panel mirrors the review
              lane with summary cards, skills, and structured sections.
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
