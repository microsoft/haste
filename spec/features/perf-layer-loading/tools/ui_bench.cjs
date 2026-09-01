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
// The cheap auth/user bootstrap is mocked (crafted SWA admin cookie + route
// interception of /.auth/me, GetUserById, PutUser) so the page renders without a
// real login; GetProjectDetails hits the REAL API and is what we measure.
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

const principal = {
  identityProvider: "aad",
  userId: "benchuser",
  userDetails: "bench@example.com",
  userRoles: ["authenticated", "administrators", "contributors"],
  claims: [],
};
const mockUser = {
  userId: "bench@example.com",
  email: "bench@example.com",
  name: "Bench User",
  status: "Active",
  userRoles: ["administrators"],
  identityProvider: "aad",
  settings: { itemsPerPage: 10 },
};

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ bypassCSP: true });

  // Crafted SWA auth cookie: base64(JSON(clientPrincipal)), no signing locally.
  const cookieVal = Buffer.from(JSON.stringify(principal)).toString("base64");
  await context.addCookies([
    { name: "StaticWebAppsAuthCookie", value: cookieVal, domain: "localhost", path: "/" },
  ]);

  const page = await context.newPage();
  const consoleErrors = [];
  const requestTimeline = [];
  const trackedRequests = new WeakMap();
  page.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });

  // Mock cheap bootstrap calls (not what we measure).
  await context.route("**/.auth/me", (r) =>
    r.fulfill({ contentType: "application/json", body: JSON.stringify({ clientPrincipal: principal }) })
  );
  await context.route("**/GetUserById**", (r) =>
    r.fulfill({ contentType: "application/json", body: JSON.stringify(mockUser) })
  );
  await context.route("**/PutUser**", (r) =>
    r.fulfill({ contentType: "application/json", body: JSON.stringify(mockUser) })
  );

  // Time every GetProjectDetails call (the real, expensive one).
  const gpd = [];
  const requestRecords = new WeakMap();
  page.on("request", (req) => {
    if (!req.url().includes("GetProjectDetails")) return;
    const record = { url: req.url(), startedAt: Date.now(), ms: null };
    requestRecords.set(req, record);
    gpd.push(record);
  });
  page.on("requestfinished", async (req) => {
    if (!req.url().includes("GetProjectDetails")) return;
    const t = req.timing();
    const record = requestRecords.get(req);
    if (record) {
      record.ms = Number.isFinite(t.responseEnd)
        ? Math.round(t.responseEnd)
        : Date.now() - record.startedAt;
    }
  });
  page.on("response", (response) => {
    const record = requestRecords.get(response.request());
    if (!record) return;
    record.status = response.status();
    record.cache = response.headers()["x-haste-cache"] ?? null;
  });

  const observedApiOrigins = new Set();
  page.on("request", (req) => {
    const u = req.url();
    if (u.includes("/api/GetProjectDetails")) observedApiOrigins.add(new URL(u).origin);
  });

  const t0 = Date.now();
  page.on("request", (req) => {
    const url = req.url();
    if (
      req.resourceType() === "document" ||
      /\.auth\/me|GetUserById|PutUser|GetPublishingProviders/.test(url)
    ) {
      const record = {
        resourceType: req.resourceType(),
        path: new URL(url).pathname,
        startedMs: Date.now() - t0,
        finishedMs: null,
      };
      trackedRequests.set(req, record);
      requestTimeline.push(record);
    }
  });
  page.on("requestfinished", (req) => {
    const record = trackedRequests.get(req);
    if (record) record.finishedMs = Date.now() - t0;
  });
  await page.goto(`${UI}/project/${PROJECT}`, { waitUntil: "commit", timeout: 60000 });

  // TTI: first image-layer row (seed names layers "Layer <n>").
  const rowTimeout = parseInt(arg("rowtimeout", "90000"), 10);
  let tti = null, rowError = null;
  try {
    await page.waitForFunction(
      () => !!document.body && /Layer \d+/.test(document.body.innerText),
      null,
      { timeout: rowTimeout, polling: 50 }
    );
    tti = Date.now() - t0;
  } catch (e) {
    rowError = String(e).split("\n")[0];
  }

  let bodyText = null;
  try {
    bodyText = (await page.locator("body").innerText()).replace(/\s+/g, " ").slice(0, 600);
  } catch (e) { bodyText = "<innerText failed: " + e + ">"; }
  try { await page.screenshot({ path: arg("shot", "/tmp/haste-uibench/shot.png"), fullPage: true }); } catch (e) {}

  const interactiveAt = Date.now();
  const initialCalls = gpd.filter((call) => call.startedAt <= interactiveAt);
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

  const result = {
    project: PROJECT,
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
    poll_getprojectdetails_ms: pollCalls.map((c) => c.ms),
    poll_getprojectdetails: pollCalls.map((call) => ({
      ms: call.ms,
      status: call.status ?? null,
      cache: call.cache ?? null,
    })),
    api_origins_observed: [...observedApiOrigins],
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
    row_wait_error: rowError,
    body_text_sample: bodyText,
    console_errors: consoleErrors.slice(0, 4),
  };
  console.log(JSON.stringify(result, null, 2));

  await browser.close();
})().catch((e) => { console.error("FATAL", e); process.exit(1); });
