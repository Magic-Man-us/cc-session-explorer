import { resolve } from "node:path";
import react from "@vitejs/plugin-react";
import { viteSingleFile } from "vite-plugin-singlefile";
import { defineConfig } from "vite";

// The app bundles the design system from source (alias below), so the components
// it ships ARE the library — no drift, no separate publish step.
export default defineConfig({
  plugins: [react(), viteSingleFile()],
  resolve: {
    alias: {
      "@cc-session/dashboard-ui": resolve(__dirname, "../ui/src/index.ts"),
    },
  },
  build: {
    // Emit the single self-contained page as package data, where the FastAPI app reads it.
    outDir: resolve(__dirname, "../../src/cc_session_explorer/static"),
    emptyOutDir: false,
    target: "es2020",
  },
  server: {
    // `npm run dev` proxies API calls to the running Python dashboard server. Both lenses'
    // prefixes: /api (cost/usage) and /timeline (context-token replay).
    proxy: {
      "/api": "http://127.0.0.1:9821",
      "/timeline": "http://127.0.0.1:9821",
    },
  },
});
