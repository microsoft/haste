// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// Browser-side Phase 0 baseline for the project page (perf-layer-loading spec).
//
// Drives the real React UI (served by the swa-cli emulator in Docker) with
// Playwright and measures, for a seeded project:
//   - time-to-interactive: navigation start -> first image-layer row visible
//   - the real GetProjectDetails request duration (the expensive call)
//   - the 20s background poll: whether it fires and its cost
//
// The cheap session bootstrap is mocked so the page renders without a real
// login; GetProjectDetails hits the REAL API and is what we measure.
//
// Run (playwright installed in a scratch dir):
//   NODE_PATH=/tmp/haste-uibench/node_modules \
//   node spec/features/perf-layer-loading/tools/ui_bench.cjs \
//     --ui http://localhost:4280 --api http://localhost:7071 \
//     --project 00000000-0000-4000-8000-000050000005
const { chromium } = require("playwright");

function arg(name, def) {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 && process.argv[i + 1] ? process.argv[i + 1] : def;
}

const UI = arg("ui", "http://localhost:4280");
const API = arg("api", "http://localhost:7071");
const PROJECT = arg("project", "00000000-0000-4000-8000-000050000005");
const POLL_WAIT_MS = parseInt(arg("pollwait", "26000"), 10);
const ROW_TIMEOUT_MS = parseInt(arg("rowtimeout", "90000"), 10);
const SCREENSHOT_PATH = arg("shot", null);

if (!Number.isInteger(POLL_WAIT_MS) || POLL_WAIT_MS < 0) {
  throw new Error("--pollwait must be a non-negative integer.");
}
if (!Number.isInteger(ROW_TIMEOUT_MS) || ROW_TIMEOUT_MS < 1) {
  throw new Error("--rowtimeout must be a positive integer.");
}
const uiUrl = new URL(UI);
const apiUrl = new URL(API);
if (!["http:", "https:"].includes(uiUrl.protocol)) {
  throw new Error("--ui must use HTTP or HTTPS.");
}
if (!["http:", "https:"].includes(apiUrl.protocol)) {
  throw new Error("--api must use HTTP or HTTPS.");
}

const principal = {
  identityProvider: "aad",
  userId: "benchuser",
  userDetails: "bench@example.com",
  userRoles: ["authenticated", "administrators", "contributors"],
  claims: [],
};
const mockSession = {
  user: {
    userId: "bench@example.com",
    identityId: "benchuser",
    userRoles: ["administrators", "contributors"],
    settings: { itemsPerPage: 10 },
    status: "Active",
  },
  publishing: {
    publishingEnabled: true,
    providers: [],
  },
};

(async () => {
  const browser = await chromium.launch({ headless: true });
  try {
    const context = await browser.newContext({ bypassCSP: true });

    // Crafted SWA auth cookie: base64(JSON(clientPrincipal)), no signing locally.
    const cookieVal = Buffer.from(JSON.stringify(principal)).toString("base64");
    await context.addCookies([
      {
        name: "StaticWebAppsAuthCookie",
        value: cookieVal,
        domain: uiUrl.hostname,
        path: "/",
      },
    ]);

    const page = await context.newPage();
    const consoleErrors = [];
    const pageErrors = [];
    const requestFailures = [];
    const httpErrors = [];
    const requestTimeline = [];
    const trackedRequests = new WeakMap();
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("pageerror", () => pageErrors.push(true));
    page.on("requestfailed", () => requestFailures.push(true));
    page.on("response", (response) => {
      if (response.status() >= 400) httpErrors.push(response.status());
    });

    // Mock the cheap bootstrap call (not what we measure).
    await context.route("**/GetSessionBootstrap**", (route) =>
      route.fulfill({
        contentType: "application/json",
        body: JSON.stringify(mockSession),
      })
    );
    await context.route("**/api/GetProjectDetails**", (route) => {
      const source = new URL(route.request().url());
      const target = new URL(source.pathname + source.search, apiUrl);
      return route.continue({ url: target.toString() });
    });

    // Time every GetProjectDetails call (the real, expensive one).
    const gpd = [];
    const requestRecords = new WeakMap();
    page.on("request", (request) => {
      if (!request.url().includes("GetProjectDetails")) return;
      const record = { startedAt: Date.now(), ms: null };
      requestRecords.set(request, record);
      gpd.push(record);
    });
    page.on("requestfinished", (request) => {
      if (!request.url().includes("GetProjectDetails")) return;
      const timing = request.timing();
      const record = requestRecords.get(request);
      if (record) {
        record.ms = Number.isFinite(timing.responseEnd)
          ? Math.round(timing.responseEnd)
          : Date.now() - record.startedAt;
      }
    });

    const observedApiOrigins = new Set();
    page.on("response", (response) => {
      const record = requestRecords.get(response.request());
      if (!record) return;
      record.status = response.status();
      record.cache = response.headers()["x-haste-cache"] ?? null;
      observedApiOrigins.add(new URL(response.url()).origin);
    });

    const t0 = Date.now();
    page.on("request", (request) => {
      const url = request.url();
      if (
        request.resourceType() === "document" ||
        /GetSessionBootstrap/.test(url)
      ) {
        const record = {
          kind:
            request.resourceType() === "document"
              ? "document"
              : "session-bootstrap",
          startedMs: Date.now() - t0,
          finishedMs: null,
        };
        trackedRequests.set(request, record);
        requestTimeline.push(record);
      }
    });
    page.on("requestfinished", (request) => {
      const record = trackedRequests.get(request);
      if (record) record.finishedMs = Date.now() - t0;
    });
    await page.goto(new URL(`/project/${PROJECT}`, uiUrl).toString(), {
      waitUntil: "commit",
      timeout: 60000,
    });

    // TTI: first image-layer row (seed names layers "Layer <n>").
    let tti;
    try {
      await page.waitForFunction(
        () => !!document.body && /Layer \d+/.test(document.body.innerText),
        null,
        { timeout: ROW_TIMEOUT_MS, polling: 50 }
      );
      tti = Date.now() - t0;
    } catch {
      throw new Error("The project content marker did not become ready.");
    }
    if (SCREENSHOT_PATH) {
      await page.screenshot({ path: SCREENSHOT_PATH, fullPage: true });
    }

    const interactiveAt = Date.now();
    const initialCalls = gpd.filter(
      (call) => call.startedAt <= interactiveAt
    );
    const initialGpdMs = initialCalls.length ? initialCalls[0].ms : null;
    const initialGpdStartedMs = initialCalls.length
      ? initialCalls[0].startedAt - t0
      : null;
    const initialGpdFinishedMs =
      initialGpdStartedMs !== null && initialGpdMs !== null
        ? initialGpdStartedMs + initialGpdMs
        : null;
    const gpdCountAfterLoad = initialCalls.length;

    // Observe the 20s background poll.
    const pollStart = Date.now();
    await page.waitForTimeout(POLL_WAIT_MS);
    const pollCalls = gpd.filter((call) => call.startedAt >= pollStart);

    const validationFailures = [];
    if (initialCalls.length !== 1) {
      validationFailures.push("initial-project-request-count");
    }
    if (!Number.isFinite(initialGpdMs)) {
      validationFailures.push("initial-project-request-timing");
    }
    if (
      initialCalls[0]?.status === undefined ||
      initialCalls[0].status >= 400
    ) {
      validationFailures.push("initial-project-request-status");
    }
    if (
      observedApiOrigins.size !== 1 ||
      !observedApiOrigins.has(apiUrl.origin)
    ) {
      validationFailures.push("api-origin");
    }
    if (consoleErrors.length) validationFailures.push("console-errors");
    if (pageErrors.length) validationFailures.push("page-errors");
    if (requestFailures.length) validationFailures.push("request-failures");
    if (httpErrors.length) validationFailures.push("http-errors");

    const result = {
      time_to_interactive_ms: tti,
      initial_getprojectdetails_started_ms: initialGpdStartedMs,
      initial_getprojectdetails_ms: initialGpdMs,
      initial_getprojectdetails_finished_ms: initialGpdFinishedMs,
      initial_getprojectdetails_status: initialCalls[0]?.status ?? null,
      initial_getprojectdetails_cache: initialCalls[0]?.cache ?? null,
      render_after_project_response_ms:
        tti !== null && initialGpdFinishedMs !== null
          ? Math.max(0, tti - initialGpdFinishedMs)
          : null,
      getprojectdetails_calls_during_load: gpdCountAfterLoad,
      poll_window_ms: POLL_WAIT_MS,
      poll_getprojectdetails_calls: pollCalls.length,
      poll_getprojectdetails_ms: pollCalls.map((call) => call.ms),
      poll_getprojectdetails: pollCalls.map((call) => ({
        ms: call.ms,
        status: call.status ?? null,
        cache: call.cache ?? null,
      })),
      api_origin_matches_requested:
        !validationFailures.includes("api-origin"),
      navigation_timing: await page.evaluate(() => {
        const navigation = performance.getEntriesByType("navigation")[0];
        return navigation
          ? {
              responseEnd: Math.round(navigation.responseEnd),
              domInteractive: Math.round(navigation.domInteractive),
              domContentLoadedEventEnd: Math.round(
                navigation.domContentLoadedEventEnd
              ),
              loadEventEnd: Math.round(navigation.loadEventEnd),
            }
          : null;
      }),
      slowest_resources: await page.evaluate(() =>
        performance
          .getEntriesByType("resource")
          .sort((left, right) => right.duration - left.duration)
          .slice(0, 10)
          .map((entry) => ({
            path: new URL(entry.name).pathname,
            initiatorType: entry.initiatorType,
            startTime: Math.round(entry.startTime),
            duration: Math.round(entry.duration),
            transferSize: entry.transferSize,
          }))
      ),
      bootstrap_requests: requestTimeline,
      console_error_count: consoleErrors.length,
      page_error_count: pageErrors.length,
      request_failure_count: requestFailures.length,
      http_error_count: httpErrors.length,
      validation_failures: validationFailures,
    };
    console.log(JSON.stringify(result, null, 2));

    if (validationFailures.length) {
      throw new Error(
        `Project benchmark failed ${validationFailures.length} validation check(s).`
      );
    }
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error("FATAL", error.message);
  process.exit(1);
});
