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
  const starts = new Map();
  page.on("request", (req) => {
    if (req.url().includes("GetProjectDetails")) starts.set(req.url() + req.method() + Date.now(), Date.now());
  });
  page.on("requestfinished", async (req) => {
    if (!req.url().includes("GetProjectDetails")) return;
    const t = req.timing();
    // responseEnd is ms since request start (fetchStart); use it as duration.
    gpd.push({ url: req.url(), ms: Math.round(t.responseEnd) });
  });

  const observedApiOrigins = new Set();
  page.on("request", (req) => {
    const u = req.url();
    if (u.includes("/api/GetProjectDetails")) observedApiOrigins.add(new URL(u).origin);
  });

  const t0 = Date.now();
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

  const initialGpdMs = gpd.length ? gpd[0].ms : null;
  const gpdCountAfterLoad = gpd.length;

  // Observe the 20s background poll.
  const pollStart = Date.now();
  await page.waitForTimeout(POLL_WAIT_MS);
  const pollCalls = gpd.slice(gpdCountAfterLoad);

  const result = {
    project: PROJECT,
    time_to_interactive_ms: tti,
    initial_getprojectdetails_ms: initialGpdMs,
    getprojectdetails_calls_during_load: gpdCountAfterLoad,
    poll_window_ms: POLL_WAIT_MS,
    poll_getprojectdetails_calls: pollCalls.length,
    poll_getprojectdetails_ms: pollCalls.map((c) => c.ms),
    api_origins_observed: [...observedApiOrigins],
    row_wait_error: rowError,
    body_text_sample: bodyText,
    console_errors: consoleErrors.slice(0, 4),
  };
  console.log(JSON.stringify(result, null, 2));

  await browser.close();
})().catch((e) => { console.error("FATAL", e); process.exit(1); });
