# Phase 1 E2E Verification Handoff

Run this on a machine or CI runner where Playwright Chromium can launch. Do
not change, skip, weaken, or rewrite the tests.

## Prerequisites

- Node.js 20.9 or newer and npm.
- A clean checkout of this repository with network access to
  `cdn.playwright.dev`, or a preinstalled matching Playwright browser.
- Ports `127.0.0.1:8100` and `127.0.0.1:3100` available locally.
- Permission to launch a headless Chromium process.

Install dependencies and the exact browser into the workspace-local cache:

```sh
npm ci
PLAYWRIGHT_BROWSERS_PATH=0 npx playwright install chromium-headless-shell
```

## Run the unchanged suite

```sh
CI=1 PLAYWRIGHT_BROWSERS_PATH=0 npm run test:e2e
```

`tests/e2e/start.mjs` is the complete test harness. Playwright starts it from
`playwright.config.ts`; it starts a mock BIA API on `127.0.0.1:8100` and the
Next development server on `127.0.0.1:3100`. Do not start the real backend and
do not set production `BIA_API_BASE_URL` or `BIA_API_KEY` for this command.
The harness supplies its own isolated values:

```text
BIA_API_BASE_URL=http://127.0.0.1:8100
BIA_API_KEY=e2e-key
```

`PLAYWRIGHT_BROWSERS_PATH=0` must be present for both installation and test
execution. If your environment manages browsers globally instead, omit it
from both commands and install the browser through that same global cache.

## Expected specifications

Both must pass:

1. `overview prioritizes operating state and explicit attention`
2. `supported evidence and empty operational states are reachable`

A successful run reports `2 passed`. It verifies the supported Phase 1
Overview, Signals, Opportunities empty state, Reports not-found state, and the
safe external-link relationship attributes.

## Pass/fail criteria

- **Pass:** Playwright launches Chromium and exits zero with both specs passed.
- **Fail:** any launch error, assertion failure, console/runtime error, or
  non-zero test exit. A missing browser is an environment failure, not a
  reason to modify the suite.

If a test fails, collect and attach:

- the complete `npm run test:e2e` output;
- the relevant trace ZIP under `test-results/` (open with
  `npx playwright show-trace <trace.zip>`);
- Playwright screenshots/videos, if generated under `test-results/`;
- Next/mock-server logs emitted by the test command;
- OS, Node (`node --version`), npm (`npm --version`), Playwright
  (`npx playwright --version`), and browser-install command output.

Do not weaken selectors or assertions, skip either specification, substitute
the real backend, or change frontend/backend behavior merely to obtain a green
result. Investigate any assertion failure as a Phase 1 regression.
