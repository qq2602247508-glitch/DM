import { defineConfig, devices } from "@playwright/test";

const startLocalServices = process.env.E2E_START_SERVERS === "1";
const dmUrl = process.env.E2E_DM_URL ?? "http://127.0.0.1:5173";
const playerUrl = process.env.E2E_PLAYER_URL ?? "http://127.0.0.1:8787";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: dmUrl,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    launchOptions: process.env.E2E_CHROMIUM_PATH
      ? { executablePath: process.env.E2E_CHROMIUM_PATH }
      : undefined,
    ...devices["Desktop Chrome"],
  },
  webServer: startLocalServices
    ? [
      {
        command: "PYTHONPATH=../backend/src ../backend/.venv/bin/alembic -c ../backend/alembic.ini upgrade head && PYTHONPATH=../backend/src ../backend/.venv/bin/python -m uvicorn dnd_dm_assistant.api.app:app --host 127.0.0.1 --port 8000 --no-access-log",
        cwd: ".",
        url: "http://127.0.0.1:8000/api/v1/health",
        reuseExistingServer: true,
        timeout: 120_000,
      },
      {
        command: "npm run dev -- --host 127.0.0.1",
        cwd: ".",
        url: dmUrl,
        reuseExistingServer: true,
        timeout: 120_000,
      },
      {
        command: "bash ../scripts/player-gateway.sh",
        cwd: ".",
        url: `${playerUrl}/api/v1/health`,
        reuseExistingServer: true,
        timeout: 180_000,
      },
    ]
    : undefined,
});

export { dmUrl, playerUrl };
