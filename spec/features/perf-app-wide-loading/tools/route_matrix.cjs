// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
//
// Measure direct cold/warm navigation for every HASTE route against a deployed
// environment. Authentication is supplied as a Playwright storage-state file
// that must remain outside the repository with mode 0600.
//
// NODE_PATH=/tmp/haste-uibench/node_modules node route_matrix.cjs \
//   --ui https://example.azurestaticapps.net \
//   --storage-state /secure/path/state.json \
//   --project <guid> --layer <guid> --model <numeric-id>
const fs = require("node:fs");
const path = require("node:path");

function arg(name, fallback = null) {
  const index = process.argv.indexOf(`--${name}`);
  return index >= 0 && process.argv[index + 1]
    ? process.argv[index + 1]
    : fallback;
}

function percentile(values, percent) {
  if (!values.length) return null;
  const sorted = [...values].sort((left, right) => left - right);
  const index = Math.min(
    sorted.length - 1,
    Math.round((percent / 100) * (sorted.length - 1))
  );
  return sorted[index];
}

const ui = arg("ui");
const storageState = arg("storage-state");
const project = arg("project");
const layer = arg("layer");
const model = arg("model");
const repeats = Number.parseInt(arg("repeats", "3"), 10);

if (!ui || !storageState || !project || !layer || !model) {
  throw new Error(
    "Required: --ui, --storage-state, --project, --layer, and --model"
  );
}
if (!Number.isInteger(repeats) || repeats < 1) {
  throw new Error("--repeats must be a positive integer.");
}
if (!fs.existsSync(storageState)) {
  throw new Error("The Playwright storage-state file does not exist.");
}
const repositoryRoot = fs.realpathSync(path.resolve(__dirname, "../../../.."));
const resolvedStorageState = fs.realpathSync(path.resolve(storageState));
const storageRelative = path.relative(repositoryRoot, resolvedStorageState);
const storageIsOutsideRepository =
  storageRelative === ".." ||
  storageRelative.startsWith(`..${path.sep}`) ||
  path.isAbsolute(storageRelative);
if (!storageIsOutsideRepository) {
  throw new Error("The storage-state file must be outside the repository.");
}
const storageStateStats = fs.statSync(resolvedStorageState);
if (!storageStateStats.isFile()) {
  throw new Error("The storage-state path must be a regular file.");
}
if ((storageStateStats.mode & 0o777) !== 0o600) {
  throw new Error("The storage-state file must have mode 0600.");
}

const { chromium } = require("playwright");

const routes = [
  { name: "home", path: "/", ready: ".home-dashboard-page" },
  { name: "projects", path: "/projects", ready: ".pgrid-page--projects" },
  {
    name: "project",
    path: `/project/${project}`,
    ready: ".pgrid-page--layers",
  },
  {
    name: "image-layer",
    path: `/project/${project}/imageLayer/${layer}`,
    readyText: "Imagery Preview",
  },
  {
    name: "create-layer",
    path: `/create-imageLayer/${project}`,
    ready: ".pgrid-page--scroll",
  },
  {
    name: "edit-layer",
    path: `/edit-imageLayer/${project}/${layer}`,
    ready: ".pgrid-page--scroll",
  },
  {
    name: "labeling",
    path: `/labeling-tool/${project}/${layer}`,
    ready: ".labeling-tool-page",
    mapReady: '.labeling-tool-page[data-map-ready="true"]',
  },
  {
    name: "validation",
    path: `/validation/${project}/${layer}`,
    ready: ".building-validation-page",
    mapReady: '.building-validation-page[data-map-ready="true"]',
  },
  {
    name: "interactive-labeler",
    path: `/interactive-label/${project}/${layer}/${model}`,
    ready: '[data-route-map="interactive-labeler"]',
    mapReady:
      '[data-route-map="interactive-labeler"][data-map-ready="true"]',
    mapTimeoutMs: 300000,
  },
  {
    name: "visualizer",
    path: `/visualizer/${project}/${layer}/${model}`,
    ready: ".visualizer-container",
    mapReady: '.visualizer-container[data-map-ready="true"]',
  },
  { name: "help", path: "/help-docs", ready: ".help-docs" },
  {
    name: "published-datasets",
    path: "/published-datasets",
    ready: ".pgrid-page--published-datasets",
  },
  {
    name: "model-catalog",
    path: "/model-catalog",
    ready: ".pgrid-page--model-catalog",
  },
  { name: "admin-users", path: "/admin-users", ready: ".pgrid-page" },
  {
    name: "admin-source-types",
    path: "/admin-source-types",
    readyText: "Source Type Management",
  },
  {
    name: "admin-labeling",
    path: "/admin-labeling-tool",
    readyText: "Labeling Tool Settings",
  },
];

const profiles = [
  { name: "desktop", viewport: { width: 1440, height: 900 } },
  { name: "mobile", viewport: { width: 390, height: 844 }, isMobile: true },
];

const homeRoute = routes.find((route) => route.name === "home");
const helpRoute = routes.find((route) => route.name === "help");
const twoSecondRoutes = new Set([
  "help",
  "admin-users",
  "admin-source-types",
  "admin-labeling",
]);

function getInAppBaseline(route) {
  return route.name === "home" ? helpRoute : homeRoute;
}

function getContentLimitMs(route) {
  return twoSecondRoutes.has(route.name) ? 2000 : 3000;
}

function getMapLimitMs(route, mode) {
  if (
    !route.mapReady ||
    route.name === "interactive-labeler" ||
    !mode.includes("warm")
  ) {
    return null;
  }
  return 3000;
}

async function waitForRoute(page, route, started) {
  await page.waitForFunction(
    ({ ready, readyText }) => {
      const contentReady = ready
        ? document.querySelector(ready) !== null
        : readyText
        ? document.body?.innerText.includes(readyText)
        : true;
      return (
        contentReady &&
        !document.querySelector(".route-loading") &&
        !document.querySelector(".app-loading-layer")
      );
    },
    { ready: route.ready, readyText: route.readyText },
    { timeout: 60000, polling: 50 }
  );
  const contentMs = Date.now() - started;
  let mapMs = null;
  if (route.mapReady) {
    await page.waitForSelector(route.mapReady, {
      state: "attached",
      timeout: route.mapTimeoutMs || 60000,
    });
    mapMs = Date.now() - started;
  }
  return { contentMs, mapMs };
}

async function navigateInApp(page, routePath) {
  await page.evaluate((nextPath) => {
    history.pushState({}, "", nextPath);
    dispatchEvent(new PopStateEvent("popstate"));
  }, routePath);
}

async function prepare(page, route, mode) {
  if (mode === "cold-direct") return;
  if (mode === "warm-direct") {
    await page.goto(new URL(route.path, ui).toString(), {
      waitUntil: "domcontentloaded",
      timeout: 60000,
    });
    await waitForRoute(page, route, Date.now());
    return;
  }

  const baselineRoute = getInAppBaseline(route);
  await page.goto(new URL(baselineRoute.path, ui).toString(), {
    waitUntil: "domcontentloaded",
    timeout: 60000,
  });
  await waitForRoute(page, baselineRoute, Date.now());
  if (mode === "in-app-warm") {
    await navigateInApp(page, route.path);
    await waitForRoute(page, route, Date.now());
    await navigateInApp(page, baselineRoute.path);
    await waitForRoute(page, baselineRoute, Date.now());
  }
}

async function measure(browser, route, profile, mode) {
  const context = await browser.newContext({
    storageState: resolvedStorageState,
    serviceWorkers: "block",
    viewport: profile.viewport,
    isMobile: profile.isMobile || false,
  });
  const page = await context.newPage();
  const requests = [];
  const failures = [];
  const httpErrors = [];
  const consoleErrors = [];
  const pageErrors = [];
  page.on("request", (request) => requests.push(request.url()));
  page.on("requestfailed", (request) => failures.push(request.url()));
  page.on("response", (response) => {
    if (response.status() >= 400) httpErrors.push(response.status());
  });
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));

  await prepare(page, route, mode);
  requests.length = 0;
  failures.length = 0;
  httpErrors.length = 0;
  consoleErrors.length = 0;
  pageErrors.length = 0;
  await page.evaluate(() => performance.clearResourceTimings());

  const started = Date.now();
  if (mode.startsWith("in-app")) {
    await navigateInApp(page, route.path);
  } else {
    await page.goto(new URL(route.path, ui).toString(), {
      waitUntil: "domcontentloaded",
      timeout: 60000,
    });
  }
  await page.waitForSelector(".app-main", {
    state: "visible",
    timeout: 60000,
  });
  const shellMs = Date.now() - started;
  const { contentMs, mapMs } = await waitForRoute(page, route, started);
  const resources = await page.evaluate(() =>
    performance.getEntriesByType("resource").map((entry) => ({
      name: new URL(entry.name).pathname,
      duration: Math.round(entry.duration),
      transferSize: entry.transferSize,
    }))
  );
  const apiDurations = resources
    .filter((resource) => resource.name.startsWith("/api/"))
    .map((resource) => resource.duration);
  const result = {
    profile: profile.name,
    mode,
    shellMs,
    contentMs,
    mapMs,
    requests: requests.length,
    apiRequests: requests.filter((url) => url.includes("/api/")).length,
    apiTotalMs: apiDurations.reduce(
      (total, duration) => total + duration,
      0
    ),
    apiMaxMs: apiDurations.length ? Math.max(...apiDurations) : null,
    failedRequests: failures.length,
    httpErrors: httpErrors.length,
    consoleErrors: consoleErrors.length,
    pageErrors: pageErrors.length,
    transferBytes: resources.reduce(
      (total, resource) => total + resource.transferSize,
      0
    ),
  };
  if (
    result.failedRequests ||
    result.httpErrors ||
    result.consoleErrors ||
    result.pageErrors
  ) {
    throw new Error(
      `${route.name} ${profile.name} ${mode} produced browser errors`
    );
  }
  await context.close();
  return result;
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const output = [];
  const violations = [];
  try {
    for (const profile of profiles) {
      for (const mode of [
        "cold-direct",
        "warm-direct",
        "in-app-cold",
        "in-app-warm",
      ]) {
        for (const route of routes) {
          const samples = [];
          for (let repeat = 0; repeat < repeats; repeat += 1) {
            try {
              samples.push(await measure(browser, route, profile, mode));
            } catch (error) {
              throw new Error(
                `${route.name} ${profile.name} ${mode} measurement failed (${error.name || "Error"})`
              );
            }
          }
          const contentLimitMs = getContentLimitMs(route);
          const mapLimitMs = getMapLimitMs(route, mode);
          const contentP95Ms = percentile(
            samples.map((sample) => sample.contentMs),
            95
          );
          const mapP95Ms = percentile(
            samples.map((sample) => sample.mapMs).filter(Number.isFinite),
            95
          );
          if (contentP95Ms > contentLimitMs) {
            violations.push({
              profile: profile.name,
              mode,
              route: route.name,
              metric: "contentP95Ms",
              observedMs: contentP95Ms,
              limitMs: contentLimitMs,
            });
          }
          if (mapLimitMs !== null && mapP95Ms > mapLimitMs) {
            violations.push({
              profile: profile.name,
              mode,
              route: route.name,
              metric: "mapP95Ms",
              observedMs: mapP95Ms,
              limitMs: mapLimitMs,
            });
          }
          output.push({
            profile: profile.name,
            mode,
            route: route.name,
            repeats,
            contentLimitMs,
            mapLimitMs,
            shellP50Ms: percentile(
              samples.map((sample) => sample.shellMs),
              50
            ),
            shellP95Ms: percentile(
              samples.map((sample) => sample.shellMs),
              95
            ),
            contentP50Ms: percentile(
              samples.map((sample) => sample.contentMs),
              50
            ),
            contentP95Ms,
            mapP95Ms,
            apiP95Ms: percentile(
              samples
                .map((sample) => sample.apiMaxMs)
                .filter(Number.isFinite),
              95
            ),
            transferP95Bytes: percentile(
              samples.map((sample) => sample.transferBytes),
              95
            ),
            samples,
          });
        }
      }
    }
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify({ routes: output, violations }, null, 2));
  if (violations.length) {
    throw new Error(
      `Route matrix failed ${violations.length} performance limit(s).`
    );
  }
})().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});