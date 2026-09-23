import { defineConfig, devices } from "@playwright/test";
import { resolve } from "node:path";

/**
 * The Phase 5 browser gate.
 *
 * It runs against a **live stack**, not a dev server this config starts. That is
 * deliberate: the thing worth proving is that the app works through the front door
 * Caddy puts in front of it — same-origin `/api/v1`, the session cookie travelling
 * because the browser sends it, SSE arriving unbuffered — and none of that is
 * exercised by `next dev`, which proxies the API itself (see infra/compose/Caddyfile
 * on why the container does not). So `make test-browser` expects `make up-stack`.
 *
 * There is no `webServer` block for the same reason: a config that silently starts a
 * dev server would make the gate pass against a topology nothing deploys.
 */

const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:3000";

export const STORAGE_STATE = resolve(__dirname, ".playwright/state.json");

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./.playwright/results",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: 0,
  workers: process.env.CI ? 2 : undefined,
  timeout: 45_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? [["github"], ["list"]] : [["list"]],
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [
    { name: "setup", testMatch: /auth\.setup\.ts/ },
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], storageState: STORAGE_STATE },
      dependencies: ["setup"],
    },
  ],
});
