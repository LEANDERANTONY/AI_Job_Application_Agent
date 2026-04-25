"use client";

// Job search + URL import + saved-jobs shortlist — extracted from
// `job-application-workspace.tsx` as part of the Item 2 frontend split
// (see `docs/NEXT-STEPS-FRONTEND.md`).
//
// Owns the markup for `mainTab === "jobs"`. State stays in the parent
// for now; the lift to a Zustand `jobSearch` + `savedJobs` slice is
// deferred to a later commit.

import type { FormEvent } from "react";

import type {
  JobPosting,
  JobSearchResponse,
} from "@/lib/api-types";
import {
  buildJobResultBadges,
  formatSavedLabel,
  resultPreview,
} from "@/lib/job-workspace";

export type JobSearchNotice = {
  level: "info" | "success" | "warning";
  message: string;
};

function noticeClassName(level: JobSearchNotice["level"]) {
  if (level === "success") return "notice-panel notice-success";
  if (level === "warning") return "notice-panel notice-warning";
  return "notice-panel notice-info";
}

export type JobSearchProps = {
  // Search form
  searchQuery: string;
  onSearchQueryChange: (value: string) => void;
  searchLocation: string;
  onSearchLocationChange: (value: string) => void;
  remoteOnly: boolean;
  onRemoteOnlyChange: (value: boolean) => void;
  postedWithinDays: string;
  onPostedWithinDaysChange: (value: string) => void;
  searching: boolean;
  onSearchSubmit: (event: FormEvent<HTMLFormElement>) => void;

  // URL import
  jobUrl: string;
  onJobUrlChange: (value: string) => void;
  importing: boolean;
  onImportSubmit: (event: FormEvent<HTMLFormElement>) => void;

  // Results
  searchNotice: JobSearchNotice | null;
  searchResults: JobSearchResponse | null;
  searchResultsCollapsed: boolean;
  onToggleSearchResultsCollapsed: () => void;
  savedJobIds: Set<string>;
  savedJobActionId: string | null;
  activeJob: JobPosting | null;
  /** Handles "Review role": set active job + switch to JD tab. */
  onReviewRole: (job: JobPosting) => void;
  authSignedIn: boolean;
  onSaveJob: (job: JobPosting) => void;

  // Saved jobs panel
  savedJobsEnabled: boolean;
  savedJobs: JobPosting[];
  savedJobsNotice: JobSearchNotice | null;
  savedJobsLoading: boolean;
  latestSavedJobAt: string;
  onLoadSavedJob: (job: JobPosting) => void;
  onRemoveSavedJob: (job: JobPosting) => void;
};

export function JobSearch({
  searchQuery,
  onSearchQueryChange,
  searchLocation,
  onSearchLocationChange,
  remoteOnly,
  onRemoteOnlyChange,
  postedWithinDays,
  onPostedWithinDaysChange,
  searching,
  onSearchSubmit,
  jobUrl,
  onJobUrlChange,
  importing,
  onImportSubmit,
  searchNotice,
  searchResults,
  searchResultsCollapsed,
  onToggleSearchResultsCollapsed,
  savedJobIds,
  savedJobActionId,
  activeJob,
  onReviewRole,
  authSignedIn,
  onSaveJob,
  savedJobsEnabled,
  savedJobs,
  savedJobsNotice,
  savedJobsLoading,
  latestSavedJobAt,
  onLoadSavedJob,
  onRemoveSavedJob,
}: JobSearchProps) {
  return (
    <section className="workspace-section-stack">
      <article className="surface-card surface-card-neutral">
        <div className="section-head">
          <div>
            <p className="eyebrow">Step 2</p>
            <h2 className="section-title">
              Search roles, import postings, and build your shortlist
            </h2>
          </div>
          <span className="status-chip">Live search</span>
        </div>

        <form className="workspace-form-stack" onSubmit={onSearchSubmit}>
          <div className="workspace-field-grid workspace-field-grid-search">
            <label className="workspace-field">
              <span className="workspace-label">Keywords</span>
              <input
                className="workspace-input"
                onChange={(event) => onSearchQueryChange(event.target.value)}
                placeholder="Machine learning engineer, product designer, data analyst..."
                value={searchQuery}
              />
            </label>
            <label className="workspace-field">
              <span className="workspace-label">Preferred location</span>
              <input
                className="workspace-input"
                onChange={(event) =>
                  onSearchLocationChange(event.target.value)
                }
                placeholder="Bengaluru, Chennai, Remote..."
                value={searchLocation}
              />
            </label>
          </div>

          <div className="workspace-search-toolbar">
            <div className="workspace-search-filters">
              <div className="workspace-search-filter-group">
                <label className="workspace-toggle">
                  <input
                    checked={remoteOnly}
                    onChange={(event) =>
                      onRemoteOnlyChange(event.target.checked)
                    }
                    type="checkbox"
                  />
                  <span>Remote only</span>
                </label>

                <label className="workspace-select-field workspace-select-field-inline">
                  <span className="workspace-label workspace-label-inline">
                    Posted within
                  </span>
                  <select
                    className="workspace-select"
                    onChange={(event) =>
                      onPostedWithinDaysChange(event.target.value)
                    }
                    value={postedWithinDays}
                  >
                    <option value="">Any time</option>
                    <option value="3">Last 3 days</option>
                    <option value="7">Last 7 days</option>
                    <option value="14">Last 14 days</option>
                    <option value="30">Last 30 days</option>
                  </select>
                </label>
              </div>
              <button
                className="primary-button workspace-button workspace-action-button"
                disabled={searching}
                type="submit"
              >
                {searching ? "Searching..." : "Search jobs"}
              </button>
            </div>
          </div>
        </form>

        <form
          className="workspace-inline-import workspace-inline-import-split"
          onSubmit={onImportSubmit}
        >
          <label className="workspace-field workspace-field-wide">
            <span className="workspace-label">Job posting link</span>
            <input
              className="workspace-input"
              onChange={(event) => onJobUrlChange(event.target.value)}
              placeholder="Paste a Greenhouse or Lever job posting URL"
              value={jobUrl}
            />
          </label>
          <button
            className="primary-button workspace-button workspace-action-button"
            disabled={importing}
            type="submit"
          >
            {importing ? "Importing..." : "Load into workspace"}
          </button>
        </form>

        {searchNotice ? (
          <div className={noticeClassName(searchNotice.level)}>
            {searchNotice.message}
          </div>
        ) : null}

        <div className="workspace-results-head">
          <div>
            <p className="workspace-label">Matching roles</p>
          </div>
          {searchResults ? (
            <div className="workspace-results-head-actions">
              <span className="status-chip">
                {searchResults.total_results} result
                {searchResults.total_results === 1 ? "" : "s"}
              </span>
              {searchResults.results.length ? (
                <button
                  className="secondary-button workspace-button workspace-button-small"
                  onClick={onToggleSearchResultsCollapsed}
                  type="button"
                >
                  {searchResultsCollapsed ? "Show results" : "Hide results"}
                </button>
              ) : null}
            </div>
          ) : null}
        </div>

        {searchResults?.results.length ? (
          searchResultsCollapsed ? (
            <div className="workspace-empty-state workspace-empty-state-compact">
              Search results are collapsed. Expand them again whenever you want
              to review roles from this search.
            </div>
          ) : (
            <div className="workspace-results-list workspace-saved-jobs-list">
              {searchResults.results.map((job) => {
                const isActive = activeJob?.id === job.id;
                const isSaved = savedJobIds.has(job.id);
                const isSaving = savedJobActionId === job.id;
                return (
                  <article
                    className={
                      isActive
                        ? "job-result-card workspace-saved-job-card workspace-result-tile job-result-card-active"
                        : "job-result-card workspace-saved-job-card workspace-result-tile"
                    }
                    key={job.id}
                  >
                    <div className="job-result-head">
                      <div>
                        <h3>{job.title}</h3>
                        <p className="job-result-company">
                          {job.company} - {job.source}
                        </p>
                      </div>
                      {isSaved ? (
                        <span className="status-chip status-chip-live">
                          Saved
                        </span>
                      ) : null}
                    </div>

                    <div className="job-result-badges">
                      {buildJobResultBadges(job).map((badge) => (
                        <span
                          className="workspace-meta-chip"
                          key={`${job.id}-${badge}`}
                        >
                          {badge}
                        </span>
                      ))}
                    </div>

                    <p className="job-result-summary">{resultPreview(job)}</p>

                    <div className="job-result-actions">
                      <button
                        className="secondary-button workspace-button workspace-button-small"
                        onClick={() => onReviewRole(job)}
                        type="button"
                      >
                        {isActive ? "Loaded" : "Review role"}
                      </button>
                      {job.url ? (
                        <a
                          className="secondary-button workspace-button workspace-button-small"
                          href={job.url}
                          rel="noreferrer"
                          target="_blank"
                        >
                          Open posting
                        </a>
                      ) : null}
                      {authSignedIn ? (
                        <button
                          className="primary-button workspace-button workspace-button-small"
                          disabled={isSaving || isSaved}
                          onClick={() => onSaveJob(job)}
                          type="button"
                        >
                          {isSaving
                            ? "Saving..."
                            : isSaved
                              ? "Saved"
                              : "Save job"}
                        </button>
                      ) : null}
                    </div>
                  </article>
                );
              })}
            </div>
          )
        ) : (
          <div className="workspace-empty-state">
            Search for roles to load one into your workspace.
          </div>
        )}

        <div className="workspace-saved-jobs-panel">
          <div className="workspace-results-head">
            <div>
              <p className="workspace-label">Saved jobs</p>
            </div>
            {authSignedIn && savedJobsEnabled ? (
              <span className="status-chip">{savedJobs.length} saved</span>
            ) : null}
          </div>

          {savedJobsNotice ? (
            <div className={noticeClassName(savedJobsNotice.level)}>
              {savedJobsNotice.message}
            </div>
          ) : null}

          {!authSignedIn ? (
            <div className="workspace-empty-state">
              Sign in with Google to save roles for later.
            </div>
          ) : !savedJobsEnabled ? (
            <div className="workspace-empty-state">
              Saved jobs are not available for this session.
            </div>
          ) : savedJobsLoading ? (
            <div className="workspace-empty-state">
              Loading your shortlist...
            </div>
          ) : savedJobs.length ? (
            <>
              <div className="workspace-summary-grid workspace-summary-grid-tight">
                <div className="metric-tile workspace-status-tile">
                  <span>Saved Jobs</span>
                  <strong>{savedJobs.length}</strong>
                  <small>Your current account-backed shortlist.</small>
                </div>
                <div className="metric-tile workspace-status-tile">
                  <span>Latest Save</span>
                  <strong>{formatSavedLabel(latestSavedJobAt)}</strong>
                  <small>
                    Most recent shortlist update for this signed-in account.
                  </small>
                </div>
                <div className="metric-tile workspace-status-tile">
                  <span>Workspace Role</span>
                  <strong>
                    {activeJob?.title || "No shortlisted role loaded"}
                  </strong>
                  <small>
                    Load any saved role here to send it back into the review and
                    analysis lane.
                  </small>
                </div>
              </div>

              <div className="workspace-results-list workspace-saved-jobs-list">
                {savedJobs.map((job) => {
                  const isActive = activeJob?.id === job.id;
                  const isRemoving = savedJobActionId === job.id;
                  return (
                    <article
                      className={
                        isActive
                          ? "job-result-card workspace-saved-job-card workspace-result-tile job-result-card-active"
                          : "job-result-card workspace-saved-job-card workspace-result-tile"
                      }
                      key={`saved-${job.id}`}
                    >
                      <div className="job-result-head">
                        <div>
                          <h3>{job.title}</h3>
                          <p className="job-result-company">
                            {job.company} - {job.source}
                          </p>
                        </div>
                        <span className="status-chip status-chip-live">
                          {formatSavedLabel(job.saved_at ?? "")}
                        </span>
                      </div>

                      <div className="job-result-badges">
                        {buildJobResultBadges(job).map((badge) => (
                          <span
                            className="workspace-meta-chip"
                            key={`saved-${job.id}-${badge}`}
                          >
                            {badge}
                          </span>
                        ))}
                      </div>

                      <p className="job-result-summary">
                        {resultPreview(job)}
                      </p>

                      <div className="job-result-actions">
                        <button
                          className="secondary-button workspace-button workspace-button-small"
                          onClick={() => onLoadSavedJob(job)}
                          type="button"
                        >
                          {isActive ? "Loaded" : "Load into workspace"}
                        </button>
                        {job.url ? (
                          <a
                            className="secondary-button workspace-button workspace-button-small"
                            href={job.url}
                            rel="noreferrer"
                            target="_blank"
                          >
                            Open posting
                          </a>
                        ) : null}
                        <button
                          className="primary-button workspace-button workspace-button-small"
                          disabled={isRemoving}
                          onClick={() => onRemoveSavedJob(job)}
                          type="button"
                        >
                          {isRemoving ? "Removing..." : "Remove"}
                        </button>
                      </div>
                    </article>
                  );
                })}
              </div>
            </>
          ) : (
            <div className="workspace-empty-state">
              Save roles from search to build your shortlist.
            </div>
          )}
        </div>
      </article>
    </section>
  );
}
