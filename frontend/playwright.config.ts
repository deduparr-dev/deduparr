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

// A stand-in Jellyfin, so the suite can drive the Jellyfin adapter for real.
const JELLYFIN_PORT = Number(process.env.E2E_JELLYFIN_PORT ?? 8097);
export const JELLYFIN_URL = `http://127.0.0.1:${JELLYFIN_PORT}`;
export const JELLYFIN_API_KEY = "fake-admin-key";
export const JELLYFIN_LIBRARY = "Fake Movies";

// Stand-ins for the services a deletion goes through
const RADARR_PORT = Number(process.env.E2E_RADARR_PORT ?? 17901);
const SONARR_PORT = Number(process.env.E2E_SONARR_PORT ?? 17902);
const QBIT_PORT = Number(process.env.E2E_QBIT_PORT ?? 17903);
export const RADARR_URL = `http://127.0.0.1:${RADARR_PORT}`;
export const SONARR_URL = `http://127.0.0.1:${SONARR_PORT}`;
export const QBIT_URL = `http://127.0.0.1:${QBIT_PORT}`;
export const ARR_API_KEY = "fake-arr-key";
export const QBIT_USERNAME = "admin";
export const QBIT_PASSWORD = "adminadmin";

const MEDIA_DIR = path.join(E2E_TMP, "media");

function fakeService(script: string, port: number, env: Record<string, string>) {
  return {
    command: `node ${script}`,
    cwd: ROOT_DIR,
    url: `http://127.0.0.1:${port}/state`,
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
    stdout: "pipe" as const,
    stderr: "pipe" as const,
    env: { PORT: String(port), MEDIA_DIR, ...env },
  };
}

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
      // Stand-in Jellyfin. Started first so the backend can reach it.
      command: `node e2e/fake-jellyfin/server.mjs`,
      cwd: ROOT_DIR,
      url: `${JELLYFIN_URL}/system/info/public`,
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
      stdout: "pipe",
      stderr: "pipe",
      env: {
        PORT: String(JELLYFIN_PORT),
        MEDIA_DIR,
        ADMIN_API_KEY: JELLYFIN_API_KEY,
      },
    },
    fakeService("e2e/fake-services/arr.mjs", RADARR_PORT, {
      FLAVOUR: "radarr",
      API_KEY: ARR_API_KEY,
    }),
    fakeService("e2e/fake-services/arr.mjs", SONARR_PORT, {
      FLAVOUR: "sonarr",
      API_KEY: ARR_API_KEY,
    }),
    fakeService("e2e/fake-services/qbittorrent.mjs", QBIT_PORT, {
      USERNAME: QBIT_USERNAME,
      PASSWORD: QBIT_PASSWORD,
    }),
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
        MEDIA_DIR,
        // DEBUG unlocks /api/scan/dev/disk-scan, the only way a spec can
        // create duplicate sets without a real Plex server.
        LOG_LEVEL: "DEBUG",
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
