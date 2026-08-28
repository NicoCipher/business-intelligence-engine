import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  // Default 5s is too tight for the very first real navigation of a run:
  // Next.js dev mode compiles a route on-demand the first time it's
  // genuinely rendered (the webServer readiness probe below only waits
  // for an initial HTTP response, not the full Suspense-streamed
  // render), and /overview now does more work than it used to (an
  // added data-fetching panel). Every navigation after the first is
  // already warm and fast -- this only widens the one-time cold-start
  // margin, it does not change what any assertion requires.
  expect: { timeout: 10_000 },
  fullyParallel: false,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:3100",
    trace: "retain-on-failure"
  },
  webServer: {
    command: "node tests/e2e/start.mjs",
    url: "http://127.0.0.1:3100/overview",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000
  },
  projects: [{
    name: "chromium",
    use: {
      ...devices["Desktop Chrome"],
      ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE } : {})
    }
  }]
});
