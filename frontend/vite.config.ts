import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    // PlayerPage intentionally uses same-origin /api/v1 requests so the
    // production LAN gateway can keep its session cookie isolated. Mirror
    // that route in the dev server as well; without this, Vite's SPA fallback
    // returns index.html and the player page fails while parsing JSON.
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
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
