"use client";

import { useEffect, useRef, type RefObject } from "react";

export interface UseAccessibleDialogOptions {
  /** Whether the dialog is currently open/mounted. */
  open: boolean;
  /** Called when the user dismisses with Escape. */
  onClose: () => void;
  /** The dialog container that bounds the focus trap. */
  containerRef: RefObject<HTMLElement | null>;
  /** Element focused when the dialog opens (e.g. the search input / textarea).
   *  Falls back to the container itself. */
  initialFocusRef?: RefObject<HTMLElement | null>;
  /** Element focused when the dialog closes. If omitted, focus is restored to
   *  whatever `document.activeElement` was when the dialog opened — used by the
   *  command palette, which has no DOM trigger (it opens via a global keydown).
   *  The assistant FAB passes its button ref so focus returns to the trigger. */
  restoreFocusRef?: RefObject<HTMLElement | null>;
}

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "textarea:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  '[tabindex]:not([tabindex="-1"])',
].join(", ");

/**
 * The accessible modal-dialog BEHAVIOUR contract (review A11Y-1 / A11Y-2),
 * shared by the command palette and the assistant FAB popover so the three
 * re-implementations collapse to one. The caller owns the JSX (role="dialog",
 * aria-modal, listbox/option semantics); this hook supplies:
 *   - document-level Escape-to-close while open,
 *   - initial focus moved into the dialog on open,
 *   - a Tab / Shift+Tab focus trap cycling within the container,
 *   - focus restored to the trigger (or the previously-focused element) on close.
 *
 * Dependency-free and matches the existing custom-hook style (no headless-UI).
 */
export function useAccessibleDialog({
  open,
  onClose,
  containerRef,
  initialFocusRef,
  restoreFocusRef,
}: UseAccessibleDialogOptions): void {
  // Keep the latest onClose without re-subscribing the document listener.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  });

  // Capture the trigger and move initial focus on open; restore on close/unmount.
  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    // Resolve the restore target up front: the trigger (e.g. the assistant
    // FAB) is a stable, mounted element; the palette passes none, so it
    // restores to whatever was focused when it opened. Capturing here (not
    // in cleanup) keeps the value stable and avoids a stale-ref read.
    const restoreTarget = restoreFocusRef?.current ?? opener;
    // Defer one tick so initial focus wins the race against the keydown that
    // opened the dialog (mirrors the command palette's prior focus pattern).
    const id = window.setTimeout(() => {
      const target = initialFocusRef?.current ?? containerRef.current;
      target?.focus?.();
    }, 0);
    return () => {
      window.clearTimeout(id);
      restoreTarget?.focus?.();
    };
    // Only on the open transition — the refs are stable across renders.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  // Document-level Escape + Tab focus trap while open.
  useEffect(() => {
    if (!open) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const root = containerRef.current;
      if (!root) return;
      const focusables = Array.from(
        root.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
      );
      if (focusables.length === 0) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      const active = document.activeElement as HTMLElement | null;
      if (event.shiftKey && active === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      } else if (active && !root.contains(active)) {
        // Focus escaped the dialog (e.g. Tab from a non-trapped element) —
        // pull it back to the first focusable.
        event.preventDefault();
        first.focus();
      }
    }
    // Capture phase so Escape/Tab fire regardless of which inner element has
    // focus, and so each call site's own panel keydown (arrows/enter in the
    // palette, enter-to-submit in the assistant) is left untouched.
    document.addEventListener("keydown", onKeyDown, true);
    return () => document.removeEventListener("keydown", onKeyDown, true);
  }, [open, containerRef]);
}
