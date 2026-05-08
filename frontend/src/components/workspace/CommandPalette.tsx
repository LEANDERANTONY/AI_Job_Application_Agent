"use client";

// ⌘K command palette — Direction B redesign.
//
// Adds a keyboard-first overlay that exposes navigation, saved jobs,
// recent assistant turns, and core actions. The component does not own
// the open/close state — the workspace shell registers the global
// ⌘K / Ctrl+K listener and toggles `open`. Esc + outside-click also
// close the palette.
//
// Items reflect the live workspace: gated steps stay disabled until
// their prerequisites are met, saved jobs come from `useSavedJobs`,
// recent assistant turns from `useAssistantHistory`. Selecting a
// recent turn re-asks the same question — wiring back through the
// existing assistant submit pipeline.

import { useEffect, useMemo, useRef, useState } from "react";

import {
  ChevronRightIcon,
  CloseIcon,
  PlayIcon,
  SearchIcon,
  SparkleIcon,
  UploadIcon,
} from "@/components/workspace/icons";
import type { JobPosting } from "@/lib/api-types";

export type CommandPaletteTab = "resume" | "jobs" | "jd" | "analysis";

export type CommandPaletteProps = {
  open: boolean;
  onClose: () => void;
  /** Current and gated step availability for the four-step flow. */
  navigation: {
    resume: boolean; // always true; included for symmetry
    jobs: boolean; // available once a candidate profile exists
    jd: boolean; // available once a candidate profile exists (or selected job)
    analysis: boolean; // available once both resume + jd are present
  };
  onNavigate: (tab: CommandPaletteTab) => void;

  /** Saved jobs from `useSavedJobs`. Empty = section hidden. */
  savedJobs: JobPosting[];
  onLoadSavedJob: (job: JobPosting) => void;

  /** Last few assistant Q's. Empty = section hidden. */
  recentAssistantQuestions: string[];
  onAskAssistant: (question: string) => void;

  /** Action: run analysis (gated by ready state). */
  analysisReady: boolean;
  onRunAnalysis: () => void;

  /** Action: re-upload resume (jumps to Step 1). */
  onReuploadResume: () => void;

  /** Action: clear active role. */
  onClearWorkspace: () => void;
};

type PaletteItem = {
  id: string;
  group: string;
  title: string;
  sub?: string;
  icon: React.ReactNode;
  shortcut?: string;
  disabled?: boolean;
  run: () => void;
};

export function CommandPalette({
  open,
  onClose,
  navigation,
  onNavigate,
  savedJobs,
  onLoadSavedJob,
  recentAssistantQuestions,
  onAskAssistant,
  analysisReady,
  onRunAnalysis,
  onReuploadResume,
  onClearWorkspace,
}: CommandPaletteProps) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setActive(0);
    // Focus the input on next tick to win against the keydown that
    // opened the palette.
    const id = window.setTimeout(() => inputRef.current?.focus(), 0);
    return () => window.clearTimeout(id);
  }, [open]);

  const items: PaletteItem[] = useMemo(() => {
    const list: PaletteItem[] = [
      {
        id: "nav-resume",
        group: "Navigate",
        title: "Go to Resume",
        sub: "Step 01 · Import & parse",
        icon: <UploadIcon />,
        shortcut: "1",
        disabled: !navigation.resume,
        run: () => {
          onNavigate("resume");
          onClose();
        },
      },
      {
        id: "nav-jobs",
        group: "Navigate",
        title: "Go to Job Search",
        sub: "Step 02 · Roles & filters",
        icon: <SearchIcon />,
        shortcut: "2",
        disabled: !navigation.jobs,
        run: () => {
          onNavigate("jobs");
          onClose();
        },
      },
      {
        id: "nav-jd",
        group: "Navigate",
        title: "Go to Job Description",
        sub: "Step 03 · Parsed JD",
        icon: <SparkleIcon />,
        shortcut: "3",
        disabled: !navigation.jd,
        run: () => {
          onNavigate("jd");
          onClose();
        },
      },
      {
        id: "nav-analysis",
        group: "Navigate",
        title: "Go to Analysis",
        sub: navigation.analysis
          ? "Step 04 · Run & artifacts"
          : "Need a parsed resume + JD",
        icon: <PlayIcon />,
        shortcut: "4",
        disabled: !navigation.analysis,
        run: () => {
          onNavigate("analysis");
          onClose();
        },
      },
    ];

    if (savedJobs.length) {
      for (const job of savedJobs.slice(0, 8)) {
        list.push({
          id: `saved-${job.id}`,
          group: "Saved jobs",
          title: job.title,
          sub: `${job.company} · ${job.source}`,
          icon: <SparkleIcon />,
          run: () => {
            onLoadSavedJob(job);
            onClose();
          },
        });
      }
    }

    // Recent questions used to be gated on `assistantUnlocked`, which
    // hid them until the user had run an analysis. The assistant is
    // ungated now (see AssistantPanel), so recent turns surface
    // whenever the user has any history at all.
    if (recentAssistantQuestions.length) {
      for (const question of recentAssistantQuestions.slice(0, 5)) {
        list.push({
          id: `recent-${question.slice(0, 24)}`,
          group: "Recent assistant",
          title: question,
          sub: "Re-ask this question",
          icon: <SparkleIcon />,
          run: () => {
            onAskAssistant(question);
            onClose();
          },
        });
      }
    }

    list.push({
      id: "act-run",
      group: "Actions",
      title: "Run analysis",
      sub: analysisReady
        ? "Generate tailored package"
        : "Need a parsed resume + JD",
      icon: <PlayIcon />,
      disabled: !analysisReady,
      run: () => {
        onRunAnalysis();
        onClose();
      },
    });
    list.push({
      id: "act-reupload",
      group: "Actions",
      title: "Re-upload resume",
      sub: "Jump back to Step 1",
      icon: <UploadIcon />,
      run: () => {
        onReuploadResume();
        onClose();
      },
    });
    list.push({
      id: "act-clear",
      group: "Actions",
      title: "Clear active role",
      sub: "Removes the JD + analysis from the workspace",
      icon: <CloseIcon />,
      run: () => {
        onClearWorkspace();
        onClose();
      },
    });

    return list;
  }, [
    analysisReady,
    navigation,
    onAskAssistant,
    onClearWorkspace,
    onClose,
    onLoadSavedJob,
    onNavigate,
    onReuploadResume,
    onRunAnalysis,
    recentAssistantQuestions,
    savedJobs,
  ]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return items;
    return items.filter((item) =>
      `${item.title} ${item.sub ?? ""} ${item.group}`.toLowerCase().includes(q),
    );
  }, [items, query]);

  // Group results in display order while preserving the section
  // ordering established by the construction above.
  const groups = useMemo(() => {
    const result: { label: string; items: PaletteItem[] }[] = [];
    for (const item of filtered) {
      let group = result.find((g) => g.label === item.group);
      if (!group) {
        group = { label: item.group, items: [] };
        result.push(group);
      }
      group.items.push(item);
    }
    return result;
  }, [filtered]);

  // Keep the cursor inside the filtered list.
  const safeActive = Math.min(active, Math.max(filtered.length - 1, 0));
  // Skip past disabled items when navigating.
  function moveActive(delta: 1 | -1) {
    if (!filtered.length) return;
    let next = safeActive;
    for (let step = 0; step < filtered.length; step += 1) {
      next = (next + delta + filtered.length) % filtered.length;
      if (!filtered[next].disabled) break;
    }
    setActive(next);
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      moveActive(1);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      moveActive(-1);
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      const item = filtered[safeActive];
      if (item && !item.disabled) {
        item.run();
      }
      return;
    }
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
    }
  }

  if (!open) return null;

  return (
    <div
      className="b-cmd-overlay"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="b-cmd-panel" onKeyDown={handleKeyDown}>
        <div className="b-cmd-input-wrap">
          <span className="b-cmd-input-icon">
            <SearchIcon />
          </span>
          <input
            className="b-cmd-input"
            onChange={(event) => {
              setQuery(event.target.value);
              setActive(0);
            }}
            placeholder="Search or run a command…"
            ref={inputRef}
            value={query}
          />
          {/* Close affordance — clickable on every platform. On
              desktop it reads "Esc" so the keyboard hint is preserved
              (the keydown listener still fires for power users). On
              mobile (≤ 540 px) the CSS swaps to a tappable X icon
              since there's no Esc key on touch devices. */}
          <button
            type="button"
            className="b-cmd-close"
            aria-label="Close command palette"
            onClick={onClose}
          >
            <span className="b-cmd-close-text" aria-hidden="true">
              Esc
            </span>
            <span className="b-cmd-close-icon" aria-hidden="true">
              <CloseIcon />
            </span>
          </button>
        </div>

        <div className="b-cmd-list">
          {groups.length === 0 ? (
            <div className="b-cmd-empty">No results for &ldquo;{query}&rdquo;</div>
          ) : (
            groups.map((group) => (
              <div key={group.label}>
                <div className="b-cmd-section-label">{group.label}</div>
                {group.items.map((item) => {
                  const flatIndex = filtered.indexOf(item);
                  return (
                    <button
                      className="b-cmd-item"
                      data-active={flatIndex === safeActive}
                      disabled={item.disabled}
                      key={item.id}
                      onClick={() => {
                        if (!item.disabled) item.run();
                      }}
                      onMouseEnter={() => setActive(flatIndex)}
                      type="button"
                    >
                      <span className="b-cmd-item-icon">{item.icon}</span>
                      <span className="b-cmd-item-main">
                        <span className="b-cmd-item-title">{item.title}</span>
                        {item.sub ? (
                          <span className="b-cmd-item-sub">{item.sub}</span>
                        ) : null}
                      </span>
                      {item.shortcut ? (
                        <span className="b-cmd-item-shortcut b-cmd-item-shortcut-key">
                          ⌘{item.shortcut}
                        </span>
                      ) : (
                        <span
                          className="b-cmd-item-shortcut b-cmd-item-shortcut-chev"
                          aria-hidden="true"
                        >
                          <ChevronRightIcon />
                        </span>
                      )}
                    </button>
                  );
                })}
              </div>
            ))
          )}
        </div>

        <div className="b-cmd-footer">
          <span>Grounded in your active workspace</span>
          <span className="b-cmd-footer-keys">
            <span className="b-cmd-footer-key">↑↓ navigate</span>
            <span className="b-cmd-footer-key">↵ run</span>
            <span className="b-cmd-footer-key">esc close</span>
          </span>
        </div>
      </div>
    </div>
  );
}
