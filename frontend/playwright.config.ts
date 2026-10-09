import { defineConfig, devices } from "@playwright/test";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

/**
 * End-to-end tests for the browser interface.
 *
 * These drive the real application: a real uvicorn process with the real OpenCV
 * pipeline and the real agent loop, and the production bundle served by the Vite
 * preview server, which proxies `/api` and `/health` the same way nginx does in the
 * container. Nothing is stubbed, so the tests exercise the same code path a user does.
 *
 * The scripted demonstration flows are used as the input, which is what makes this
 * deterministic: they feed real generated equipment photographs to the normal
 * inspection pipeline, so the measurements asserted here come from OpenCV.
 *
 *   npm run test:e2e            # add --headed or --ui while working on a test
 *
 * The backend needs the interpreter that has the backend's dependencies installed.
 * The repository's documented venv is `.venv/` at the root, so that is the default;
 * set `SIGHTOPS_PYTHON` to point somewhere else.
 */

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, "..");

const PYTHON = process.env.SIGHTOPS_PYTHON ?? join(REPO, ".venv", "bin", "python");
const BACKEND_URL = process.env.SIGHTOPS_BACKEND ?? "http://127.0.0.1:8000";
const WEB_URL = process.env.SIGHTOPS_WEB_BASE ?? "http://127.0.0.1:4173";

export default defineConfig({
  testDir: "./e2e",
  // The two flows share one backend, and an agent run is the slow part; running them
  // in parallel would only make the timings harder to read.
  workers: 1,
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  timeout: 240_000,
  expect: { timeout: 20_000 },
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: WEB_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      // A throwaway data directory: an end-to-end run must not leave inspections in
      // the developer's own database.
      command: `${PYTHON} -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level warning`,
      cwd: join(REPO, "backend"),
      url: `${BACKEND_URL}/health`,
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
      env: { SIGHTOPS_DATA_DIR: join(REPO, "data", "e2e") },
    },
    {
      // `preview` serves the production bundle, so this also asserts that the build
      // the Docker image ships is the one that works.
      command: "npm run preview",
      cwd: HERE,
      url: WEB_URL,
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
    },
  ],
});
