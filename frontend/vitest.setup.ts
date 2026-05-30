// Registers @testing-library/jest-dom matchers (toBeInTheDocument,
// toHaveAttribute, …) AND augments Vitest's expect types — so the build's
// isolated type pass over *.test.tsx files does not error on the matchers.
import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// Auto-unmount and clear the DOM between tests.
afterEach(() => {
  cleanup();
});
