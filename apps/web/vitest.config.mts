import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Vite's dep-optimizer cache can materialize a *second*, separate local
// copy of react/react-dom under apps/web/node_modules on some runs (its
// .vite / .vite-temp pre-bundle cache) even when the "real" install lives
// at the workspace root -- picked up as a distinct module instance and
// producing a spurious "Invalid hook call" from two different React
// instances. Pinning the alias to an explicit absolute path at the
// workspace root (rather than a bare specifier Vite could re-resolve into
// its own cache) sidesteps it reliably -- confirmed empirically: this
// exact config passed 10+ consecutive runs; every variant that instead
// resolved to the local apps/web copy (even the identical absolute path,
// via require.resolve) failed 100% of runs. CI's frontend job runs an
// extra `bun install` at the workspace root (see ci.yml) purely so this
// path exists there too.
const workspaceRoot = path.resolve(import.meta.dirname, "..", "..");

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "."),
      react: path.resolve(workspaceRoot, "node_modules/react"),
      "react-dom/client": path.resolve(workspaceRoot, "node_modules/react-dom/client"),
      "react-dom": path.resolve(workspaceRoot, "node_modules/react-dom"),
    },
    dedupe: ["react", "react-dom"],
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.tsx"],
    server: {
      deps: {
        inline: [/^react$/, /^react-dom$/, /^react-dom\//],
      },
    },
  },
});
