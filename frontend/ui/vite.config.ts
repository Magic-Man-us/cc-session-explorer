import { resolve } from "node:path";
import react from "@vitejs/plugin-react";
import dts from "vite-plugin-dts";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), dts({ rollupTypes: true, tsconfigPath: "./tsconfig.json" })],
  build: {
    lib: {
      entry: resolve(__dirname, "src/index.ts"),
      name: "CcSessionUI",
      fileName: (format) => (format === "es" ? "cc-session-ui.js" : "cc-session-ui.umd.cjs"),
      formats: ["es", "umd"],
    },
    rollupOptions: {
      external: ["react", "react-dom", "react/jsx-runtime"],
      output: {
        globals: {
          react: "React",
          "react-dom": "ReactDOM",
          "react/jsx-runtime": "jsxRuntime",
        },
      },
    },
  },
});
