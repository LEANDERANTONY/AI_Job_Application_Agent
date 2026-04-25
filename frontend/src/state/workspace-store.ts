"use client";

// Zustand store for the workspace surface. Built incrementally as part of
// Item 2 of `docs/NEXT-STEPS-FRONTEND.md` — sliced so each feature area
// (assistant, artifacts, JD review, ...) lives in its own slice and
// per-slice subscriptions avoid cross-area re-render avalanches.
//
// Right now only the `ui` slice is implemented. Later commits add
// `auth/session`, `jobSearch`, `savedJobs`, `jdReview`, `analysisJob`,
// `artifacts`, `assistant`, and `resumeIntake` slices and `&`-merge them
// into `WorkspaceStore`.

import { create, type StateCreator } from "zustand";

// ---------------------------------------------------------------------------
// ui slice — sidebar + main-tab routing
// ---------------------------------------------------------------------------

export type WorkspaceMainTab = "resume" | "jobs" | "jd" | "analysis";

export type UiSlice = {
  sidebarCollapsed: boolean;
  mainTab: WorkspaceMainTab;

  setSidebarCollapsed: (collapsed: boolean) => void;
  toggleSidebar: () => void;
  setMainTab: (tab: WorkspaceMainTab) => void;

  /**
   * Read `?tab=...`, `?drawer=...`, and the URL hash from the current
   * `window.location` and apply them. Safe to call in a `useEffect`
   * after mount.
   *
   * Mirrors the prior monolith's `getInitialSidebarCollapsed` and
   * `getInitialMainTab` exactly so existing shareable links keep working.
   */
  hydrateUiFromUrl: () => void;
};

function isValidMainTab(value: string | null): value is WorkspaceMainTab {
  return (
    value === "resume" ||
    value === "jobs" ||
    value === "jd" ||
    value === "analysis"
  );
}

const createUiSlice: StateCreator<WorkspaceStore, [], [], UiSlice> = (set) => ({
  sidebarCollapsed: false,
  mainTab: "resume",

  setSidebarCollapsed: (sidebarCollapsed) => set({ sidebarCollapsed }),
  toggleSidebar: () =>
    set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
  setMainTab: (mainTab) => set({ mainTab }),

  hydrateUiFromUrl: () => {
    if (typeof window === "undefined") {
      return;
    }
    const params = new URLSearchParams(window.location.search);

    // Drawer: `closed` collapses; `open` and any other value (including
    // absent) leave it expanded — matches getInitialSidebarCollapsed.
    const sidebarCollapsed = params.get("drawer") === "closed";

    // Tab: prefer ?tab=, fall back to #hash, default "resume".
    const tabParam = params.get("tab");
    const hashValue = window.location.hash.replace(/^#/, "");
    const mainTab: WorkspaceMainTab = isValidMainTab(tabParam)
      ? tabParam
      : isValidMainTab(hashValue)
        ? hashValue
        : "resume";

    set({ sidebarCollapsed, mainTab });
  },
});

// ---------------------------------------------------------------------------
// Combined store
// ---------------------------------------------------------------------------

export type WorkspaceStore = UiSlice;

export const useWorkspaceStore = create<WorkspaceStore>()((...a) => ({
  ...createUiSlice(...a),
}));
