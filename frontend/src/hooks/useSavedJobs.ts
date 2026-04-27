"use client";

// Hook owning the saved-jobs shortlist state for the workspace.
// Lifted from `WorkspaceShell.tsx` as part of the Item 2 frontend
// split (see `docs/NEXT-STEPS-FRONTEND.md`, task #13).
//
// Manages auto-load on auth state change, save/remove handlers, and
// the derived `savedJobIds` Set + `latestSavedJobAt` watermark used
// by the JobSearch surface.
//
// Note: `handleLoadSavedJob` (which sets the active job + main tab +
// notice) is NOT in this hook; that's a cross-slice action handled
// by the parent shell.

import { useEffect, useMemo, useState } from "react";

import { loadSavedJobs, removeSavedJob, saveSavedJob } from "@/lib/api";
import type {
  AuthSessionResponse,
  JobPosting,
} from "@/lib/api-types";

type Notice =
  | { level: "info" | "success" | "warning"; message: string }
  | null;

type AuthStatus = "loading" | "restoring" | "signed_out" | "signed_in";

function sortSavedJobs(jobs: JobPosting[]): JobPosting[] {
  return [...jobs].sort((left, right) => {
    const leftSaved = left.saved_at ?? "";
    const rightSaved = right.saved_at ?? "";
    if (leftSaved !== rightSaved) {
      return rightSaved.localeCompare(leftSaved);
    }
    const leftPosted = left.posted_at ?? "";
    const rightPosted = right.posted_at ?? "";
    if (leftPosted !== rightPosted) {
      return rightPosted.localeCompare(leftPosted);
    }
    return left.title.localeCompare(right.title);
  });
}

export type UseSavedJobsOptions = {
  authStatus: AuthStatus;
  authSession: AuthSessionResponse | null;
};

export type UseSavedJobsReturn = {
  savedJobs: JobPosting[];
  savedJobsLoading: boolean;
  savedJobsNotice: Notice;
  savedJobActionId: string | null;
  savedJobIds: Set<string>;
  latestSavedJobAt: string;
  savedJobsEnabled: boolean;
  saveJob: (job: JobPosting) => Promise<void>;
  removeJob: (job: JobPosting) => Promise<void>;
  /** Used by sign-out to drop the cached shortlist + clear notices. */
  resetSavedJobs: () => void;
};

export function useSavedJobs({
  authStatus,
  authSession,
}: UseSavedJobsOptions): UseSavedJobsReturn {
  const [savedJobs, setSavedJobs] = useState<JobPosting[]>([]);
  const [savedJobsLoading, setSavedJobsLoading] = useState(false);
  const [savedJobsNotice, setSavedJobsNotice] = useState<Notice>(null);
  const [savedJobActionId, setSavedJobActionId] = useState<string | null>(
    null,
  );

  const savedJobsEnabled = Boolean(authSession?.features.saved_jobs_enabled);

  useEffect(() => {
    if (authStatus !== "signed_in" || !savedJobsEnabled) {
      setSavedJobs([]);
      setSavedJobsLoading(false);
      return;
    }

    let cancelled = false;

    async function hydrateSavedJobs() {
      setSavedJobsLoading(true);
      try {
        const response = await loadSavedJobs();
        if (!cancelled) {
          setSavedJobs(sortSavedJobs(response.saved_jobs));
        }
      } catch (error) {
        if (!cancelled) {
          setSavedJobsNotice({
            level: "warning",
            message:
              error instanceof Error
                ? error.message
                : "Saved jobs could not be loaded right now.",
          });
          setSavedJobs([]);
        }
      } finally {
        if (!cancelled) {
          setSavedJobsLoading(false);
        }
      }
    }

    void hydrateSavedJobs();

    return () => {
      cancelled = true;
    };
  }, [savedJobsEnabled, authStatus]);

  const savedJobIds = useMemo(
    () =>
      new Set(savedJobs.map((job) => job.id.trim()).filter(Boolean)),
    [savedJobs],
  );

  const latestSavedJobAt = useMemo(
    () =>
      savedJobs.reduce((latest, job) => {
        const savedAt = job.saved_at ?? "";
        return savedAt > latest ? savedAt : latest;
      }, ""),
    [savedJobs],
  );

  async function saveJob(job: JobPosting) {
    if (authStatus !== "signed_in") {
      setSavedJobsNotice({
        level: "warning",
        message: "Sign in with Google before saving jobs to your shortlist.",
      });
      return;
    }

    setSavedJobActionId(job.id);
    try {
      const response = await saveSavedJob(job);
      setSavedJobs((current) =>
        sortSavedJobs([
          response.saved_job,
          ...current.filter((item) => item.id !== response.saved_job.id),
        ]),
      );
      setSavedJobsNotice({
        level: "success",
        message: response.message,
      });
    } catch (error) {
      setSavedJobsNotice({
        level: "warning",
        message:
          error instanceof Error
            ? error.message
            : "This role could not be saved to your shortlist.",
      });
    } finally {
      setSavedJobActionId(null);
    }
  }

  async function removeJob(job: JobPosting) {
    if (authStatus !== "signed_in") {
      setSavedJobsNotice({
        level: "warning",
        message: "Sign in with Google before editing your shortlist.",
      });
      return;
    }

    setSavedJobActionId(job.id);
    try {
      await removeSavedJob(job.id);
      setSavedJobs((current) => current.filter((item) => item.id !== job.id));
      setSavedJobsNotice({
        level: "success",
        message: `Removed ${job.title || "this role"} from your shortlist.`,
      });
    } catch (error) {
      setSavedJobsNotice({
        level: "warning",
        message:
          error instanceof Error
            ? error.message
            : "This role could not be removed from your shortlist.",
      });
    } finally {
      setSavedJobActionId(null);
    }
  }

  function resetSavedJobs() {
    setSavedJobs([]);
    setSavedJobsNotice(null);
  }

  return {
    savedJobs,
    savedJobsLoading,
    savedJobsNotice,
    savedJobActionId,
    savedJobIds,
    latestSavedJobAt,
    savedJobsEnabled,
    saveJob,
    removeJob,
    resetSavedJobs,
  };
}
