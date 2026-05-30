import { defineConfig } from "vitest/config";
import { resolve } from "node:path";

// No @vitejs/plugin-react here: it is ESM-only and the project is not
// `type: module`, so importing it breaks the CJS config load. esbuild's
// automatic JSX runtime is sufficient to transform the .tsx component tests.
export default defineConfig({
  esbuild: { jsx: "automatic", jsxImportSource: "react" },
  resolve: {
    // Mirror the tsconfig path mapping `@/* -> ./src/*`. `npm test` runs with
    // cwd = frontend/, so a cwd-relative resolve avoids needing import.meta.
    alias: { "@": resolve("src") },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
  },
});
