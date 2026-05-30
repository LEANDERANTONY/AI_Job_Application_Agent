import { describe, it, expect, vi } from "vitest";
import { useRef } from "react";
import { render, fireEvent, waitFor } from "@testing-library/react";

import { useAccessibleDialog } from "@/lib/useAccessibleDialog";

function Dialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  useAccessibleDialog({
    open,
    onClose,
    containerRef,
    initialFocusRef: inputRef,
  });
  if (!open) return null;
  return (
    <div ref={containerRef} role="dialog" aria-modal="true">
      <input ref={inputRef} aria-label="first" />
      <button type="button">middle</button>
      <button type="button">last</button>
    </div>
  );
}

describe("useAccessibleDialog (A11Y-1/A11Y-2)", () => {
  it("closes on Escape dispatched at the document level", () => {
    const onClose = vi.fn();
    render(<Dialog open onClose={onClose} />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("moves initial focus into the dialog (the configured input)", async () => {
    const { getByLabelText } = render(<Dialog open onClose={vi.fn()} />);
    const input = getByLabelText("first");
    await waitFor(() => expect(document.activeElement).toBe(input));
  });

  it("traps Tab: from the last focusable it wraps to the first", () => {
    const { getByText, getByLabelText } = render(
      <Dialog open onClose={vi.fn()} />,
    );
    const last = getByText("last");
    last.focus();
    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(getByLabelText("first"));
  });

  it("traps Shift+Tab: from the first focusable it wraps to the last", () => {
    const { getByText, getByLabelText } = render(
      <Dialog open onClose={vi.fn()} />,
    );
    getByLabelText("first").focus();
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(getByText("last"));
  });
});
