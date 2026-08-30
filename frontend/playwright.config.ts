import { defineConfig, devices } from "@playwright/test";
import path from "path";
import { fileURLToPath } from "url";

// package.json sets "type": "module", so __dirname is unavailable here.
const ROOT_DIR = path.dirname(fileURLToPath(import.meta.url));

const BACKEND_PORT = Number(process.env.E2E_BACKEND_PORT ?? 3101);
const FRONTEND_PORT = Number(process.env.E2E_FRONTEND_PORT ?? 4173);

export const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;
export const FRONTEND_URL = `http://127.0.0.1:${FRONTEND_PORT}`;

// Scratch state for the disposable backend instance the suite drives.
export const E2E_TMP = path.resolve(ROOT_DIR, "e2e/.tmp");

const PYTHON_BIN = process.env.PYTHON_BIN ?? "python3";

export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",

  // The suite shares one backend database, so specs run serially.
  fullyParallel: false,
  workers: 1,

  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],

  timeout: 30_000,
  expect: { timeout: 10_000 },

  use: {
    baseURL: FRONTEND_URL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },

  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],

  webServer: [
    {
      // Disposable backend: temp SQLite database and encryption key, so the
      // suite never touches a real install.
      command: `${PYTHON_BIN} -m uvicorn app.main:app --host 127.0.0.1 --port ${BACKEND_PORT} --log-level warning`,
      cwd: path.resolve(ROOT_DIR, "../backend"),
      url: `${BACKEND_URL}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      stdout: "pipe",
      stderr: "pipe",
      env: {
        DATABASE_TYPE: "sqlite",
        DATABASE_URL: `sqlite:///${path.join(E2E_TMP, "e2e.db")}`,
        ENCRYPTION_KEY_FILE: path.join(E2E_TMP, ".encryption_key"),
        CONFIG_DIR: E2E_TMP,
        MEDIA_DIR: path.join(E2E_TMP, "media"),
        LOG_LEVEL: "WARNING",
        ENABLE_SCHEDULED_SCANS: "false",
        ENABLE_SCHEDULED_DELETION: "false",
      },
    },
    {
      // Serve the real production build, proxying /api to the test backend.
      command: "npm run build && npm run preview",
      cwd: ROOT_DIR,
      url: FRONTEND_URL,
      reuseExistingServer: !process.env.CI,
      timeout: 180_000,
      stdout: "pipe",
      stderr: "pipe",
      env: { VITE_PROXY_TARGET: BACKEND_URL },
    },
  ],
});
