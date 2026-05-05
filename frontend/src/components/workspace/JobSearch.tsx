"use client";

// Job search + URL import + saved-jobs shortlist — Direction B redesign.
//
// Behavior preservation:
//   - searchJobs (debounced via parent) on submit
//   - Filter chips toggle filter set
//   - Saved jobs persist via useSavedJobs (auth + feature gate respected)
//   - Selected job highlights and drives Step 3 (parent's onReviewRole)
//   - "Resolve URL" path via parent's onImportSubmit
//   - Saved-jobs panel collapsible (drawer-style, above results)
//
// Layout (per handoff specs/02-jobs.md):
//   1. Region head (eyebrow + title + sub)
//   2. b-search-bar (keywords | location | submit)
//   3. b-search-row (filters + URL import on the right)
//   4. b-saved-section (collapsible drawer with saved-job cards)
//   5. b-results-head + b-job-grid (top-match badge on the leader)

import { useState, type FormEvent } from "react";

import {
  ChevronRightIcon,
  ExternalIcon,
  PinIcon,
  SearchIcon,
  StarIcon,
} from "@/components/workspace/icons";
import type { JobPosting, JobSearchResponse } from "@/lib/api-types";
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
  if (level === "success") return "b-notice b-notice-success";
  if (level === "warning") return "b-notice b-notice-warning";
  return "b-notice";
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

type JobCardProps = {
  job: JobPosting;
  isActive: boolean;
  isSaved: boolean;
  isPending: boolean;
  topMatch?: boolean;
  showSaveButton: boolean;
  showRemoveButton: boolean;
  onPrimary: () => void;
  primaryLabel: string;
  onSaveClick?: () => void;
  onRemoveClick?: () => void;
  savedAt?: string;
};

function JobCard({
  job,
  isActive,
  isSaved,
  isPending,
  topMatch,
  showSaveButton,
  showRemoveButton,
  onPrimary,
  primaryLabel,
  onSaveClick,
  onRemoveClick,
  savedAt,
}: JobCardProps) {
  return (
    <article
      className="b-job-card"
      data-active={isActive || undefined}
      data-top-match={topMatch || undefined}
    >
      <div className="b-job-card-head">
        <div>
          <h3 className="b-job-card-title">{job.title}</h3>
          <div className="b-job-card-company">
            {job.company} · {job.source}
          </div>
        </div>
        <div className="b-job-card-aside">
          {topMatch ? (
            <span className="b-top-match-badge">
              <StarIcon /> Top match
            </span>
          ) : null}
          {savedAt ? (
            <span className="b-saved-mark">{formatSavedLabel(savedAt)}</span>
          ) : isSaved ? (
            <span className="b-saved-mark">Saved</span>
          ) : null}
        </div>
      </div>

      <p className="b-job-card-summary">{resultPreview(job)}</p>

      <div className="b-job-card-meta">
        {buildJobResultBadges(job).map((badge, index) => (
          <span key={`${job.id}-${badge}-${index}`}>
            {index > 0 ? <span className="b-job-card-meta-dot" /> : null}
            {badge}
          </span>
        ))}
      </div>

      <div className="b-job-card-actions">
        <button
          className="rd-btn rd-btn-ghost rd-btn-sm"
          onClick={onPrimary}
          type="button"
        >
          {primaryLabel}
        </button>
        {job.url ? (
          <a
            className="rd-btn rd-btn-quiet rd-btn-sm"
            href={job.url}
            rel="noreferrer"
            target="_blank"
          >
            <ExternalIcon /> Open
          </a>
        ) : null}
        {showSaveButton && onSaveClick ? (
          <button
            aria-pressed={isSaved}
            className="rd-btn rd-btn-quiet rd-btn-sm"
            disabled={isPending || isSaved}
            onClick={onSaveClick}
            type="button"
          >
            <PinIcon /> {isPending ? "Saving…" : isSaved ? "Saved" : "Save"}
          </button>
        ) : null}
        {showRemoveButton && onRemoveClick ? (
          <button
            className="rd-btn rd-btn-danger rd-btn-sm"
            disabled={isPending}
            onClick={onRemoveClick}
            type="button"
          >
            {isPending ? "Removing…" : "Remove"}
          </button>
        ) : null}
      </div>
    </article>
  );
}

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
  const results = searchResults?.results ?? [];
  // Saved-jobs drawer is closed by default; user toggles to expand.
  const [savedDrawerOpen, setSavedDrawerOpen] = useState(false);

  return (
    <div className="b-region">
      <div className="b-region-head">
        <div>
          <div className="b-region-title">Find a role</div>
          <div className="b-region-sub">
            Search live listings, paste a posting URL, or open a saved job.
          </div>
        </div>
        <span className="b-region-tag">STEP 02</span>
      </div>

      <form className="b-search-bar" onSubmit={onSearchSubmit}>
        <div className="b-search-icon">
          <SearchIcon />
        </div>
        <input
          onChange={(event) => onSearchQueryChange(event.target.value)}
          placeholder="Keywords"
          value={searchQuery}
        />
        <div className="b-search-divider" />
        <input
          onChange={(event) => onSearchLocationChange(event.target.value)}
          placeholder="Location · or remote"
          value={searchLocation}
        />
        <button
          className="rd-btn rd-btn-primary rd-btn-sm"
          disabled={searching}
          type="submit"
        >
          {searching ? "Searching…" : "Search"}
        </button>
      </form>

      <div className="b-search-row">
        <div className="b-search-filters">
          <label className="b-search-toggle">
            <input
              checked={remoteOnly}
              onChange={(event) => onRemoteOnlyChange(event.target.checked)}
              type="checkbox"
            />
            Remote only
          </label>
          <label className="b-search-toggle">
            Posted within
            <select
              className="rd-select"
              onChange={(event) => onPostedWithinDaysChange(event.target.value)}
              style={{
                width: "auto",
                padding: "3px 6px",
                marginLeft: 4,
                height: 26,
              }}
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
        <form className="b-search-import" onSubmit={onImportSubmit}>
          <span>Or paste URL:</span>
          <input
            className="rd-input b-search-import-input"
            onChange={(event) => onJobUrlChange(event.target.value)}
            placeholder="greenhouse.io/…"
            value={jobUrl}
          />
          <button
            className="rd-btn rd-btn-ghost rd-btn-sm"
            disabled={importing}
            type="submit"
          >
            {importing ? "Importing…" : "Import"}
          </button>
        </form>
      </div>

      {searchNotice ? (
        <div className={noticeClassName(searchNotice.level)}>
          {searchNotice.message}
        </div>
      ) : null}

      {/* Saved jobs collapsible drawer */}
      <div className="b-saved-section">
        <button
          aria-expanded={savedDrawerOpen}
          className="b-saved-toggle"
          onClick={() => setSavedDrawerOpen((open) => !open)}
          type="button"
        >
          <span className="b-saved-caret">
            <ChevronRightIcon />
          </span>
          <span className="b-saved-title">Saved jobs</span>
          <span className="b-saved-count">
            {authSignedIn && savedJobsEnabled
              ? `${savedJobs.length} saved`
              : "Sign in to save"}
          </span>
        </button>

        {savedJobsNotice ? (
          <div
            className={noticeClassName(savedJobsNotice.level)}
            style={{ marginTop: 10 }}
          >
            {savedJobsNotice.message}
          </div>
        ) : null}

        {savedDrawerOpen ? (
          !authSignedIn ? (
            <div className="b-saved-empty">
              Sign in with Google to save roles for later.
            </div>
          ) : !savedJobsEnabled ? (
            <div className="b-saved-empty">
              Saved jobs are not available for this session.
            </div>
          ) : savedJobsLoading ? (
            <div className="b-saved-empty">Loading your shortlist…</div>
          ) : savedJobs.length ? (
            <div
              className="b-job-grid"
              style={{ marginTop: 12 }}
            >
              {savedJobs.map((job) => {
                const isActive = activeJob?.id === job.id;
                const isPending = savedJobActionId === job.id;
                return (
                  <JobCard
                    isActive={isActive}
                    isPending={isPending}
                    isSaved
                    job={job}
                    key={`saved-${job.id}`}
                    onPrimary={() => onLoadSavedJob(job)}
                    onRemoveClick={() => onRemoveSavedJob(job)}
                    primaryLabel={isActive ? "Loaded" : "Load into workspace"}
                    savedAt={job.saved_at ?? latestSavedJobAt}
                    showRemoveButton
                    showSaveButton={false}
                  />
                );
              })}
            </div>
          ) : (
            <div className="b-saved-empty">
              Save matches to revisit them later — your shortlist is empty.
            </div>
          )
        ) : null}
      </div>

      {/* Results header + grid */}
      {searchResults ? (
        <div className="b-results-head">
          <div className="b-section-label">
            Matches · {searchResults.total_results} role
            {searchResults.total_results === 1 ? "" : "s"}
          </div>
          <div style={{ fontSize: 12.5, color: "var(--fg-3)" }}>
            Sorted by recency
          </div>
        </div>
      ) : null}

      {results.length ? (
        <div className="b-job-grid">
          {results.map((job, index) => {
            const isActive = activeJob?.id === job.id;
            const isSaved = savedJobIds.has(job.id);
            const isPending = savedJobActionId === job.id;
            return (
              <JobCard
                isActive={isActive}
                isPending={isPending}
                isSaved={isSaved}
                job={job}
                key={job.id}
                onPrimary={() => onReviewRole(job)}
                onSaveClick={
                  authSignedIn && !isSaved ? () => onSaveJob(job) : undefined
                }
                primaryLabel={isActive ? "Loaded" : "Review role"}
                showRemoveButton={false}
                showSaveButton={authSignedIn}
                topMatch={index === 0 && results.length >= 2}
              />
            );
          })}
        </div>
      ) : searchResults ? (
        <div className="b-saved-empty">
          No roles matched this search. Try different keywords.
        </div>
      ) : (
        <div className="b-saved-empty">
          Search for roles to load one into your workspace.
        </div>
      )}
    </div>
  );
}
