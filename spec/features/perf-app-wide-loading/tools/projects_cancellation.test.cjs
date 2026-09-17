const assert = require("node:assert/strict");
const { once } = require("node:events");
const { mkdirSync, mkdtempSync, rmSync } = require("node:fs");
const { tmpdir } = require("node:os");
const path = require("node:path");
const { createRequire } = require("node:module");
const { pathToFileURL } = require("node:url");
const test = require("node:test");
const { chromium } = require("playwright");

const uiRoot = process.env.PROJECTS_UI_ROOT || path.resolve(__dirname, "../../../../ui");
const fromUi = createRequire(path.join(uiRoot, "package.json"));
const outputDir = process.env.PROJECTS_OUTPUT_DIR;
const projectData = (name = "Current project") => ({
  projects: [{ projectId: "fixture", name, description: "Synthetic project",
    creationDate: "2026-09-16T00:00:00Z", affectedCountries: ["USA"],
    imageLayerCount: 4, modelsCount: 4, labelsCount: 9 }],
});
const countries = { type: "FeatureCollection", features: [
  { type: "Feature", id: "USA", properties: { name: "United States" }, geometry: null },
] };

const fixture = `
import React, { StrictMode, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter, Routes, Route, Link, useNavigate } from 'react-router-dom';
import { FluentProvider, webLightTheme } from '@fluentui/react-components';
import { AppContext } from '/src/AppContext.jsx';
import Projects from '/src/Components/Projects.jsx';
import Loading from '/src/Components/OtherComponents/Loading.jsx';
import { loadCountryNames } from '/src/util/countries.js';
import 'bootstrap/dist/css/bootstrap.min.css';
import '/src/assets/css/style.css';

window.calls = []; window.events = [];
const nativeFetch = window.fetch.bind(window);
window.fetch = (url, options = {}) => {
  const call = { url: String(url), signal: options.signal, aborted: options.signal?.aborted || false };
  window.calls.push(call);
  options.signal?.addEventListener('abort', () => { call.aborted = true; });
  if (window.deferDashboard && call.url.includes('GetDashboardData')) {
    return new Promise((resolve, reject) => {
      call.resolve = data => resolve(new Response(JSON.stringify(data)));
      call.reject = () => reject(new Error('Obsolete response failure'));
    });
  }
  return nativeFetch(url, options);
};
window.sharedCountries = loadCountryNames;
function Destination() {
  const [names, setNames] = useState({});
  useEffect(() => {
    let active = true;
    loadCountryNames().then(value => { if (active) setNames(value); });
    return () => { active = false; };
  }, []);
  return React.createElement('div', { id: 'destination' }, 'Destination ready ', names.USA || '');
}
function Harness() {
  const navigate = useNavigate(); window.navigate = navigate;
  const [params, setParams] = useState({ userId: 'fixture-user', userSettings: {},
    bootstrapBreakpoint: window.innerWidth < 600 ? 2 : 5, guidedTourProperties: [], isLoading: false });
  const [header, setHeader] = useState('');
  const [tour, setTour] = useState('');
  const [dialog, setDialog] = useState(null);
  const setLoading = (value, message) => {
    window.events.push({ type: 'loading', value });
    setParams(previous => ({ ...previous, isLoading: value, loadingMessage: message }));
  };
  window.startDestinationAction = () => { setHeader('Destination header'); setTour('Destination tour'); setLoading(true, 'Destination action'); };
  const context = { appParams: params, setAppParams: setParams, setIsLoading: setLoading,
    initCurrentTour: value => { window.events.push({ type: 'tour', value }); setTour(value || ''); },
    setAppHeaderRightButtons: value => { window.events.push({ type: 'header', count: value.length }); setHeader(value[0]?.title || ''); },
    setDialog: (title, message, buttons) => setDialog(title ? { title, message, buttons } : null),
  };
  return React.createElement(AppContext.Provider, { value: context },
    React.createElement('nav', null, React.createElement(Link, { to: '/projects' }, 'Projects link'),
      React.createElement(Link, { to: '/destination' }, 'Destination link')),
    React.createElement('span', { id: 'header-state' }, header),
    React.createElement('span', { id: 'tour-state' }, tour),
    React.createElement('span', { id: 'setting-state' }, String(params.userSettings.itemsPerPageProjects || '')),
    React.createElement('div', { className: params.isLoading ? 'app-body-shell--blocked' : '' },
      React.createElement(Loading),
      React.createElement(Routes, null,
        React.createElement(Route, { path: '/projects', element: React.createElement(Projects) }),
        React.createElement(Route, { path: '/destination', element: React.createElement(Destination) }),
        React.createElement(Route, { path: '*', element: React.createElement('div', null, 'Start') }))),
    dialog && React.createElement('div', { role: 'dialog' }, dialog.title,
      ...(dialog.buttons || []).map(button => React.createElement('button', { key: button.key, onClick: button.onClick }, button.text)))
  );
}
createRoot(document.getElementById('root')).render(React.createElement(StrictMode, null,
  React.createElement(FluentProvider, { theme: webLightTheme }, React.createElement(MemoryRouter, null, React.createElement(Harness)))));
`;

test("Projects request ownership", { timeout: 120000 }, async (suite) => {
  const { createServer } = await import(pathToFileURL(fromUi.resolve("vite")));
  const { default: react } = await import(pathToFileURL(fromUi.resolve("@vitejs/plugin-react")));
  const cacheDir = mkdtempSync(path.join(tmpdir(), "haste-projects-vite-"));
  suite.after(() => rmSync(cacheDir, { recursive: true, force: true }));
  let mode = "hold";
  let holdCountries = false;
  let holdWrites = false;
  let data = projectData();
  const pending = [];
  const countryReads = [];
  const mutations = [];
  function json(response, body, status = 200) {
    response.writeHead(status, { "Content-Type": "application/json" });
    response.end(JSON.stringify(body));
  }
  function hold(response, list) {
    const entry = { response, closed: false };
    list.push(entry);
    response.once("close", () => { entry.closed = true; });
    response.writeHead(200, { "Content-Type": "application/json" });
    response.flushHeaders();
  }
  const server = await createServer({ root: uiRoot, configFile: false, envDir: false, cacheDir,
    define: { "import.meta.env.VITE_API_URL": JSON.stringify("/__projects/") },
    server: { host: "127.0.0.1", port: 0 }, plugins: [react(), {
      name: "projects-fixture",
      resolveId(id) { if (id === "/__projects-fixture.jsx") return id; },
      load(id) { if (id === "/__projects-fixture.jsx") return fixture; },
      configureServer(vite) {
        vite.middlewares.use(async (request, response, next) => {
          const url = new URL(request.url, "http://localhost");
          if (url.pathname === "/__projects-test") {
            response.setHeader("Content-Type", "text/html");
            response.end(await vite.transformIndexHtml(url.pathname,
              '<html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><div id="root"></div><script type="module" src="/__projects-fixture.jsx"></script></body></html>'));
          } else if (url.pathname === "/__projects/GetDashboardData") {
            if (mode === "hold") hold(response, pending);
            else if (mode === "error") json(response, {}, 500);
            else json(response, mode === "invalid" ? {} : data);
          } else if (url.pathname === "/assets/json/world.geojson") {
            if (holdCountries) hold(response, countryReads);
            else json(response, countries);
          } else if (url.pathname === "/__projects/GetUserById") {
            json(response, { userId: "fixture-user", settings: {} });
          } else if (["/__projects/PutUser", "/__projects/DeleteProject"].includes(url.pathname)) {
            let body = "";
            for await (const chunk of request) body += chunk;
            const entry = { method: request.method, body: body ? JSON.parse(body) : null, response };
            mutations.push(entry);
            if (!holdWrites) json(response, {});
          } else next();
        });
      },
    }] });
  await server.listen();
  suite.after(() => server.close());
  const base = `http://127.0.0.1:${server.httpServer.address().port}`;
  const browser = await chromium.launch({ headless: true });
  suite.after(() => browser.close());

  async function open(context, width = 1440) {
    mode = "hold"; holdCountries = false; holdWrites = false; data = projectData();
    const page = await browser.newPage({ viewport: { width, height: width < 600 ? 844 : 900 } });
    context.after(() => page.close());
    const errors = [];
    page.on("pageerror", error => errors.push(error.message));
    context.after(() => assert.deepEqual(errors, []));
    await page.goto(`${base}/__projects-test`);
    await page.waitForFunction(() => Boolean(window.navigate));
    return page;
  }
  async function enterPending(page) {
    const response = page.waitForResponse(value => value.url().includes("GetDashboardData"));
    await page.getByRole("link", { name: "Projects link", exact: true }).click();
    await response;
    await page.getByText("Loading projects", { exact: true }).waitFor();
  }
  async function leave(page) {
    const aborted = page.waitForEvent("requestfailed", { predicate: request =>
      request.url().includes("GetDashboardData") && request.failure().errorText.includes("ABORTED") });
    await page.getByRole("link", { name: "Destination link", exact: true }).click();
    await aborted;
    await page.locator("#destination").waitFor();
  }
  async function snapshot(page, name) {
    if (!outputDir) return;
    mkdirSync(outputDir, { recursive: true });
    await page.screenshot({ path: path.join(outputDir, `${name}.png`) });
  }

  await suite.test("repeated interrupted visits abort actual requests without global loading writes", async context => {
    const page = await open(context);
    const first = pending.length;
    for (let visit = 0; visit < 5; visit++) {
      await enterPending(page);
      assert.equal(await page.locator(".app-loading-layer").count(), 0);
      if (visit === 0) await snapshot(page, "projects-loading-desktop");
      await leave(page);
      assert.equal(await page.locator(".route-loading").count(), 0);
      assert.equal(await page.evaluate(() => window.calls.filter(call => call.url.includes("GetDashboardData")).every(call => call.aborted)), true);
    }
    await Promise.all(pending.slice(first).map(entry => entry.closed ? Promise.resolve()
      : once(entry.response, "close", { signal: AbortSignal.timeout(5000) })));
    assert.deepEqual(await page.evaluate(() => window.events.filter(event => event.type === "loading")), []);
    mode = "ready";
    await page.getByRole("link", { name: "Projects link", exact: true }).click();
    await page.getByRole("link", { name: "Current project", exact: true }).waitFor();
  });

  await suite.test("obsolete success and failure cannot change a destination action or a fresh Projects mount", async context => {
    const page = await open(context);
    await page.evaluate(() => { window.deferDashboard = true; });
    await page.getByRole("link", { name: "Projects link", exact: true }).click();
    await page.waitForFunction(() => window.calls.filter(call => call.resolve).length === 2);
    await page.getByRole("link", { name: "Destination link", exact: true }).click();
    await page.waitForFunction(() => window.calls.filter(call => call.resolve).every(call => call.aborted));
    await page.evaluate(() => window.startDestinationAction());
    const count = await page.evaluate(() => window.events.length);
    await page.evaluate(value => { window.calls.find(call => call.resolve).resolve(value); }, projectData("Obsolete project"));
    await page.evaluate(() => new Promise(requestAnimationFrame));
    assert.equal(await page.evaluate(() => window.events.length), count);
    assert.equal(await page.locator("#header-state").textContent(), "Destination header");
    assert.equal(await page.locator("#tour-state").textContent(), "Destination tour");
    assert.equal(await page.getByText("Destination action", { exact: true }).count(), 1);
    await page.evaluate(() => window.navigate('/projects'));
    await page.waitForFunction(() => window.calls.filter(call => call.resolve).length === 4);
    const pendingCount = await page.evaluate(() => window.events.length);
    await page.evaluate(() => { window.calls.filter(call => call.reject && call.aborted).forEach(call => call.reject()); });
    await page.evaluate(() => new Promise(requestAnimationFrame));
    assert.equal(await page.evaluate(() => window.events.length), pendingCount);
    assert.equal(await page.locator(".route-loading").count(), 1);
    assert.equal(await page.getByText("Projects could not be loaded.", { exact: true }).count(), 0);
    await page.evaluate(value => { window.calls.filter(call => call.resolve && !call.aborted).forEach(call => call.resolve(value)); }, projectData());
    await page.getByRole("link", { name: "Current project", exact: true }).waitFor();
    const loadedCount = await page.evaluate(() => window.events.length);
    await page.evaluate(() => { window.calls.filter(call => call.reject && call.aborted).forEach(call => call.reject()); });
    await page.evaluate(() => new Promise(requestAnimationFrame));
    assert.equal(await page.evaluate(() => window.events.length), loadedCount);
    assert.equal(await page.getByText("Obsolete project", { exact: true }).count(), 0);
    assert.equal(await page.getByText("Projects could not be loaded.", { exact: true }).count(), 0);
    assert.equal(await page.getByText("Destination action", { exact: true }).count(), 1);
  });

  await suite.test("HTTP and malformed response errors recover through a fresh Retry", async context => {
    const page = await open(context, 390);
    mode = "error";
    await page.getByRole("link", { name: "Projects link", exact: true }).click();
    await page.getByText("Projects could not be loaded.", { exact: true }).waitFor();
    await snapshot(page, "projects-error-mobile");
    mode = "invalid";
    await page.getByRole("button", { name: "Retry", exact: true }).click();
    await page.getByText("Projects could not be loaded.", { exact: true }).waitFor();
    mode = "hold";
    const response = page.waitForResponse(value => value.url().includes("GetDashboardData"));
    await page.getByRole("button", { name: "Retry", exact: true }).click();
    await response;
    await page.getByText("Loading projects", { exact: true }).waitFor();
    await snapshot(page, "projects-loading-mobile");
    pending.at(-1).response.end(JSON.stringify(projectData()));
    await page.getByRole("link", { name: "Current project", exact: true }).waitFor();
    assert.deepEqual(await page.evaluate(() => window.events.filter(event => event.type === "loading")), []);
  });

  await suite.test("shared country data survives navigation and is reused by the next consumer", async context => {
    const page = await open(context);
    holdCountries = true;
    const countryStarted = page.waitForResponse(value => value.url().includes("world.geojson"));
    await enterPending(page);
    const countryResponse = await countryStarted;
    await leave(page);
    assert.equal(await page.evaluate(() => window.calls.filter(call => call.url.includes("world.geojson")).length), 1);
    assert.equal(await page.evaluate(() => window.calls.find(call => call.url.includes("world.geojson")).aborted), false);
    countryReads.at(-1).response.end(JSON.stringify(countries));
    await countryResponse.finished();
    await page.getByText("Destination ready United States", { exact: true }).waitFor();
    mode = "ready";
    await page.getByRole("link", { name: "Projects link", exact: true }).click();
    await page.getByText("United States", { exact: true }).waitFor();
    assert.equal(await page.evaluate(() => window.calls.filter(call => call.url.includes("world.geojson")).length), 1);
  });

  await suite.test("an empty project list is a successful non-loading state", async context => {
    const page = await open(context);
    mode = "ready"; data = { projects: [] };
    await page.getByRole("link", { name: "Projects link", exact: true }).click();
    await page.locator(".pgrid-page--projects").waitFor();
    assert.equal(await page.locator(".route-loading, .app-loading-layer").count(), 0);
    assert.equal(await page.getByText("Projects could not be loaded.", { exact: true }).count(), 0);
  });

  await suite.test("preference saves retain their explicit-action lifetime", async context => {
    const page = await open(context);
    mode = "ready"; holdWrites = true;
    await page.getByRole("link", { name: "Projects link", exact: true }).click();
    await page.locator(".pgrid-rows-dropdown").click();
    const saving = page.waitForRequest(request => request.url().includes("PutUser"));
    await page.getByRole("option", { name: "10", exact: true }).click();
    await saving;
    await page.getByText("Updating Items Per Page...", { exact: true }).waitFor();
    assert.equal(await page.evaluate(() => window.calls.find(call => call.url.includes("PutUser")).signal == null), true);
    await page.evaluate(() => window.navigate('/destination'));
    assert.equal(await page.evaluate(() => window.calls.find(call => call.url.includes("PutUser")).aborted), false);
    await page.waitForFunction(() => window.calls.some(call => call.url.includes('PutUser')));
    const mutation = mutations.at(-1);
    assert.equal(mutation.body.user.settings.itemsPerPageProjects, 10);
    json(mutation.response, {});
    await page.waitForFunction(() => document.getElementById('setting-state').textContent === '10');
    assert.equal(await page.locator(".app-loading-layer").count(), 0);
  });

  for (const width of [1440, 390]) {
    await suite.test(`post-delete refresh preserves the awaitable callback at width ${width}`, async context => {
      const page = await open(context, width);
      mode = "ready";
      await page.getByRole("link", { name: "Projects link", exact: true }).click();
      await page.getByRole("button", { name: "Menu", exact: true }).first().click();
      await page.getByRole("menuitem", { name: "Remove", exact: true }).click();
      mode = "hold";
      const refreshed = page.waitForResponse(response => response.url().includes("GetDashboardData"));
      await page.getByRole("button", { name: "Yes", exact: true }).click();
      await refreshed;
      assert.equal(await page.evaluate(() => window.calls.find(call => call.url.includes("DeleteProject")).signal == null), true);
      assert.equal(await page.locator(".app-loading-layer").count(), 1);
      assert.equal(await page.locator(".route-loading").isVisible(), false);
      pending.at(-1).response.end(JSON.stringify(projectData("Refreshed project")));
      await page.getByRole("link", { name: "Refreshed project", exact: true }).waitFor();
      await page.waitForFunction(() => !document.querySelector('.app-loading-layer'));
      assert.equal(await page.locator(".route-loading").count(), 0);
    });
  }
});