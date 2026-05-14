"use client";

// Tier-aware quota hook (Step 7b). Drives the Premium toggle and the
// per-counter indicators on the workspace's run panel.
//
// Owned by `WorkspaceShell` and lifted out so the toggle component
// doesn't have to know how the snapshot is fetched. The hook:
//   1. Fetches /workspace/quota on mount (when authStatus is
//      "signed_in") and exposes the snapshot via `quota`.
//   2. Exposes `refresh()` so the analysis-runner hook can re-fetch
//      after every run (success OR failure — both can move counter
//      values via refund-on-failure paths).
//   3. Stays silent on anonymous + auth-loading paths — the snapshot
//      makes no sense without an authenticated user, and we don't
//      want to spam the backend with 401s while auth is restoring.
//
// Loose error handling: a fetch failure logs and surfaces `quota=null`
// but doesn't toast — the snapshot is informational, not blocking. If
// the underlying gate fails on the actual run, the global 429 handler
// owns the user-facing message.

import { useCallback, useEffect, useRef, useState } from "react";

import { getWorkspaceQuota } from "@/lib/api";
import type { WorkspaceQuotaResponse } from "@/lib/api-types";

export type UseWorkspaceQuotaOptions = {
  authStatus: "loading" | "restoring" | "signed_out" | "signed_in";
};

export type UseWorkspaceQuotaReturn = {
  /** The latest snapshot or null when nothing has been fetched yet
   *  (anonymous, auth still restoring, or fetch failed). */
  quota: WorkspaceQuotaResponse | null;
  /** Trigger a refetch. The analysis-runner hook calls this after
   *  every run so the indicator stays live. */
  refresh: () => void;
  /** True while a fetch is in flight — the UI uses this to suppress
   *  flicker between two snapshots without rendering a separate
   *  spinner. */
  quotaLoading: boolean;
};

export function useWorkspaceQuota({
  authStatus,
}: UseWorkspaceQuotaOptions): UseWorkspaceQuotaReturn {
  const [quota, setQuota] = useState<WorkspaceQuotaResponse | null>(null);
  const [quotaLoading, setQuotaLoading] = useState(false);

  // Bump on every explicit `refresh()` call so the effect below
  // refires. Storing this as a counter (rather than a boolean) means
  // back-to-back refreshes in the same render also retrigger.
  const [refreshNonce, setRefreshNonce] = useState(0);

  // Cancellation token for in-flight fetches — if `authStatus` flips
  // mid-fetch (sign-out, restoring → signed_in), we drop the older
  // response so it can't overwrite the new state.
  const cancelTokenRef = useRef(0);

  useEffect(() => {
    // Skip fetch entirely on non-signed-in states. Anonymous calls
    // would 401 (the route requires auth) and "loading"/"restoring"
    // are transient — wait for the steady state.
    if (authStatus !== "signed_in") {
      setQuota(null);
      return;
    }

    cancelTokenRef.current += 1;
    const token = cancelTokenRef.current;
    setQuotaLoading(true);

    void getWorkspaceQuota()
      .then((snapshot) => {
        if (cancelTokenRef.current !== token) return;
        setQuota(snapshot);
      })
      .catch((error) => {
        if (cancelTokenRef.current !== token) return;
        // Informational fetch — log and leave `quota` as-is. The UI
        // falls back to the disabled-toggle state when quota is null,
        // which is the safe default for a sign-out + sign-in window
        // where /workspace/quota briefly 401s.
        if (typeof window !== "undefined" && window.console?.warn) {
          window.console.warn("workspace_quota_fetch_failed", error);
        }
        setQuota(null);
      })
      .finally(() => {
        if (cancelTokenRef.current !== token) return;
        setQuotaLoading(false);
      });
  }, [authStatus, refreshNonce]);

  const refresh = useCallback(() => {
    setRefreshNonce((prev) => prev + 1);
  }, []);

  return {
    quota,
    refresh,
    quotaLoading,
  };
}
