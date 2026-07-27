import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.ts",
    css: true,
    // Playwright specs live beside unit tests but must only run through
    // `npm run e2e`; Vitest cannot collect Playwright's test() globals.
    exclude: ["**/node_modules/**", "**/dist/**", "**/e2e/**"],
  },
});
