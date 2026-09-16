const assert = require("node:assert/strict");
const { createServer } = require("node:http");
const { once } = require("node:events");
const { mkdirSync, readFileSync } = require("node:fs");
const path = require("node:path");
const { createRequire } = require("node:module");
const { pathToFileURL } = require("node:url");
const test = require("node:test");
const { chromium } = require("playwright");

const root = path.resolve(__dirname, "../../../..");
const uiRoot = process.env.CXL_UI_ROOT || path.join(root, "ui");
const uiRequire = createRequire(path.join(uiRoot, "package.json"));
const outputDir = process.env.CXL_OUTPUT_DIR;
const pixel = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aF9sAAAAASUVORK5CYII=",
  "base64"
);

const fixture = `
import React, { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter, Routes, Route, Link, useNavigate } from "react-router-dom";
import { FluentProvider, webLightTheme } from "@fluentui/react-components";
import { AppContext } from "/src/AppContext.jsx";
import ImageLayer from "/src/Components/ImageLayer.jsx";
import LayerRow from "/src/Components/ProjectManagement/LayerRow.jsx";
import LayerCard from "/src/Components/ProjectManagement/LayerCard.jsx";
import { useImagePreload } from "/src/Components/ProjectManagement/useImagePreload.js";
import "bootstrap/dist/css/bootstrap.min.css";

window.calls = [];
window.globals = [];
window.createdUrls = [];
window.revokedUrls = [];
const realFetch = window.fetch.bind(window);
window.fetch = (url, options = {}) => {
  const call = { url: String(url), aborted: options.signal?.aborted || false };
  window.calls.push(call);
  options.signal?.addEventListener("abort", () => { call.aborted = true; });
  if (window.deferReads && call.url.includes("GetProjectDetails")) {
    return new Promise((resolve) => { call.resolve = (data) => resolve(new Response(JSON.stringify(data))); });
  }
  return realFetch(url, options);
};
const createUrl = URL.createObjectURL.bind(URL);
const revokeUrl = URL.revokeObjectURL.bind(URL);
URL.createObjectURL = (blob) => { const url = createUrl(blob); window.createdUrls.push(url); return url; };
URL.revokeObjectURL = (url) => { window.revokedUrls.push(url); revokeUrl(url); };

function Preview() {
  const [url, setUrl] = useState(null);
  window.setPreview = setUrl;
  const { loadedUrl, isLoading } = useImagePreload(url);
  return React.createElement("div", {
    id: "preview", "data-url": loadedUrl || "", "data-loading": String(isLoading),
    style: { width: 120, height: 80, backgroundImage: loadedUrl ? 'url("' + loadedUrl + '")' : "none" },
  });
}
function Harness() {
  const navigate = useNavigate();
  window.navigate = navigate;
  const props = {
    item: { imageLayerId: "first", name: "Fixture layer", status: "Processed", models: [],
      creationDate: "2026-09-16T00:00:00Z", createdBy: "Fixture user",
      postEventPreviewUrls: [window.location.origin + "/__cxl/ready.png"] },
    index: 0, projectId: "project", visibleModelId: "", eventTypes: [],
    onComponentChange() {}, setModalComponent() {}, fetchProjectDetails() {},
  };
  return React.createElement(React.Fragment, null,
    React.createElement(Link, { to: "/destination" }, "Dashboard"),
    React.createElement(Routes, null,
      React.createElement(Route, { path: "/project/:projectId/imageLayer/:imageLayerId", element: React.createElement(ImageLayer) }),
      React.createElement(Route, { path: "/preview", element: React.createElement(Preview) }),
      React.createElement(Route, { path: "/consumers", element: React.createElement("div", null,
        React.createElement(LayerCard, props),
        React.createElement("table", null, React.createElement("tbody", null, React.createElement(LayerRow, props)))) }),
      React.createElement(Route, { path: "*", element: React.createElement("div", { id: "destination" }, "Destination ready") })
    )
  );
}
const context = {
  appParams: { isLoading: false, bootstrapBreakpoint: 5 },
  setIsLoading: (...args) => window.globals.push(args),
};
createRoot(document.getElementById("root")).render(
  React.createElement(StrictMode, null,
    React.createElement(FluentProvider, { theme: webLightTheme },
      React.createElement(AppContext.Provider, { value: context },
        React.createElement(MemoryRouter, null, React.createElement(Harness))
      )
    )
  )
);
`;

function projectData(name = "Current layer") {
  return {
    projectId: "project",
    name: "Fixture project",
    imageLayer: ["first", "second"].map((imageLayerId) => ({
      imageLayerId, name: `${name} ${imageLayerId}`,
      description: "Fixture imagery", labelProjectCount: 0, status: "Processed",
    })),
  };
}

test("CXL-01 browser lifecycles", { timeout: 120000 }, async (suite) => {
  const { createServer: createViteServer } = await import(pathToFileURL(uiRequire.resolve("vite")));
  const { default: react } = await import(pathToFileURL(uiRequire.resolve("@vitejs/plugin-react")));
  const pending = [];
  let apiMode = "hold";
  const crossOrigin = createServer((request, response) => {
    if (request.url === "/cors.png") response.setHeader("Access-Control-Allow-Origin", "*");
    response.setHeader("Content-Type", "image/png");
    response.end(pixel);
  });
  await new Promise((resolve) => crossOrigin.listen(0, "127.0.0.1", resolve));
  suite.after(() => { crossOrigin.closeAllConnections(); crossOrigin.close(); });
  const crossUrl = `http://127.0.0.1:${crossOrigin.address().port}`;
  const vite = await createViteServer({
    root: uiRoot, configFile: false, envDir: false, mode: "test",
    define: { "import.meta.env.VITE_API_URL": JSON.stringify("/__cxl/api/") },
    server: { host: "127.0.0.1", port: 0 },
    plugins: [react(), {
      name: "cxl-fixture",
      resolveId(id) { if (id === "/__cxl-fixture.jsx") return id; },
      load(id) { if (id === "/__cxl-fixture.jsx") return fixture; },
      configureServer(server) {
        server.middlewares.use(async (request, response, next) => {
          const url = new URL(request.url, "http://localhost");
          if (url.pathname === "/__cxl") {
            response.setHeader("Content-Type", "text/html");
            response.end(await server.transformIndexHtml(url.pathname,
              '<html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><div id="root"></div><script type="module" src="/__cxl-fixture.jsx"></script></body></html>'));
          } else if (url.pathname === "/__cxl/csp") {
            const config = JSON.parse(readFileSync(path.join(uiRoot, "public/staticwebapp.config.json")));
            response.setHeader("Content-Security-Policy", config.globalHeaders["Content-Security-Policy"]);
            response.setHeader("Content-Type", "text/html");
            response.end("<html><body></body></html>");
          } else if (url.pathname === "/__cxl/api/GetProjectDetails") {
            if (apiMode === "hold") {
              const entry = { response, closed: false };
              pending.push(entry);
              response.on("close", () => { entry.closed = true; });
              response.writeHead(200, { "Content-Type": "application/json" });
              response.flushHeaders();
            } else {
              response.setHeader("Content-Type", "application/json");
              response.statusCode = apiMode === "error" ? 500 : 200;
              response.end(JSON.stringify(apiMode === "missing" ? { ...projectData(), imageLayer: [] } : projectData()));
            }
          } else if (url.pathname === "/__cxl/slow.png") {
            response.writeHead(200, { "Content-Type": "image/png", "Content-Length": pixel.length });
            response.write(pixel.subarray(0, 16));
            const entry = { response, closed: false };
            pending.push(entry);
            response.on("close", () => { entry.closed = true; });
          } else if (url.pathname === "/__cxl/ready.png") {
            response.writeHead(200, { "Content-Type": "image/png", "Cache-Control": "public, max-age=3600" });
            response.end(pixel);
          } else if (url.pathname === "/__cxl/broken.png") {
            response.writeHead(404);
            response.end();
          } else { next(); }
        });
      },
    }],
  });
  await vite.listen();
  suite.after(() => vite.close());
  const base = `http://127.0.0.1:${vite.httpServer.address().port}`;
  const browser = await chromium.launch({ headless: true });
  suite.after(() => browser.close());

  async function open(context, viewport = { width: 1440, height: 900 }) {
    const page = await browser.newPage({ viewport });
    context.after(() => page.close());
    const failures = [];
    const errors = [];
    page.on("requestfailed", (request) => failures.push({ url: request.url(), error: request.failure().errorText }));
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(`${base}/__cxl`);
    await page.waitForFunction(() => Boolean(window.navigate));
    return { page, failures, errors };
  }
  async function go(page, pathname) {
    await page.evaluate((value) => window.navigate(value), pathname);
  }
  async function preview(page, url) {
    await page.evaluate((value) => window.setPreview(value), url);
  }
  async function snapshot(page, name) {
    if (!outputDir) return;
    mkdirSync(outputDir, { recursive: true });
    await page.screenshot({ path: path.join(outputDir, `${name}.png`) });
  }

  await suite.test("navigation aborts pending ImageLayer reads and preserves destination state", async (context) => {
    apiMode = "hold";
    const { page, failures, errors } = await open(context);
    const responseStarted = page.waitForResponse((response) => response.url().includes("GetProjectDetails"));
    await go(page, "/project/project/imageLayer/first");
    await responseStarted;
    await page.waitForFunction(() => window.calls.some((call) => call.url.includes("GetProjectDetails") && !call.aborted));
    await snapshot(page, "image-layer-loading-desktop");
    const firstIndex = pending.length;
    const aborted = page.waitForEvent("requestfailed", { predicate: (request) => request.url().includes("GetProjectDetails") });
    await page.getByRole("link", { name: "Dashboard", exact: true }).click();
    await aborted;
    await page.waitForSelector("#destination");
    assert.equal(await page.evaluate(() => window.calls.filter((call) => call.url.includes("GetProjectDetails")).every((call) => call.aborted)), true);
    assert.deepEqual(await page.evaluate(() => window.globals), []);
    assert.equal(await page.getByText("Image layer details could not be loaded.").count(), 0);
    assert.ok(failures.some((failure) => failure.url.includes("GetProjectDetails") && failure.error.includes("ABORTED")));
    await Promise.all(pending.slice(0, firstIndex).map((entry) => entry.closed
      ? Promise.resolve()
      : once(entry.response, "close", { signal: AbortSignal.timeout(5000) })));
    assert.ok(pending.slice(0, firstIndex).every((entry) => entry.closed));
    apiMode = "ready";
    await go(page, "/project/project/imageLayer/first");
    await page.getByRole("heading", { name: "Current layer first", exact: true }).waitFor();
    assert.deepEqual(errors, []);
  });

  await suite.test("layer replacement rejects late results even when transport ignores abort", async (context) => {
    const { page, errors } = await open(context);
    await page.evaluate(() => { window.deferReads = true; });
    await go(page, "/project/project/imageLayer/first");
    await page.waitForFunction(() => window.calls.some((call) => call.resolve && !call.aborted));
    await go(page, "/project/project/imageLayer/second");
    await page.waitForFunction(() => window.calls.filter((call) => call.resolve).length >= 3);
    await page.evaluate((data) => {
      for (const call of window.calls.filter((entry) => entry.resolve && !entry.aborted)) call.resolve(data);
    }, projectData());
    await page.getByRole("heading", { name: "Current layer second", exact: true }).waitFor();
    await page.evaluate((data) => {
      for (const call of window.calls.filter((entry) => entry.resolve && entry.aborted)) call.resolve(data);
    }, projectData("Obsolete layer"));
    await page.evaluate(() => new Promise(requestAnimationFrame));
    assert.equal(await page.getByRole("heading", { name: "Current layer second", exact: true }).count(), 1);
    assert.equal(await page.getByText("Obsolete layer", { exact: false }).count(), 0);
    assert.deepEqual(await page.evaluate(() => window.globals), []);
    assert.deepEqual(errors, []);
  });

  await suite.test("failure and missing-layer states can retry with a fresh request", async (context) => {
    const { page, errors } = await open(context, { width: 390, height: 844 });
    apiMode = "error";
    await go(page, "/project/project/imageLayer/first");
    await page.getByText("Image layer details could not be loaded.", { exact: true }).waitFor();
    await snapshot(page, "image-layer-error-mobile");
    apiMode = "missing";
    await page.getByRole("button", { name: "Retry", exact: true }).click();
    await page.getByText("Image layer details could not be loaded.", { exact: true }).waitFor();
    apiMode = "ready";
    await page.getByRole("button", { name: "Retry", exact: true }).click();
    await page.getByRole("heading", { name: "Current layer first", exact: true }).waitFor();
    assert.deepEqual(await page.evaluate(() => window.globals), []);
    assert.deepEqual(errors, []);
  });

  await suite.test("thumbnail transfer aborts on navigation and on URL replacement", async (context) => {
    const { page, failures, errors } = await open(context);
    await go(page, "/preview");
    const firstResponse = page.waitForResponse((response) => response.url().includes("slow.png?first"));
    await preview(page, "/__cxl/slow.png?first");
    await firstResponse;
    await preview(page, "/__cxl/ready.png");
    await page.waitForFunction(() => document.getElementById("preview").dataset.url.startsWith("blob:"));
    assert.equal(await page.evaluate(() => window.calls.find((call) => call.url.includes("slow.png?first")).aborted), true);
    const secondResponse = page.waitForResponse((response) => response.url().includes("slow.png?second"));
    await preview(page, "/__cxl/slow.png?second");
    await secondResponse;
    const aborted = page.waitForEvent("requestfailed", { predicate: (request) => request.url().includes("slow.png?second") });
    await page.getByRole("link", { name: "Dashboard", exact: true }).click();
    await aborted;
    await page.waitForSelector("#destination");
    assert.equal(await page.evaluate(() => window.calls.filter((call) => call.url.includes("slow.png")).every((call) => call.aborted)), true);
    assert.ok(failures.some((failure) => failure.url.includes("slow.png?second") && failure.error.includes("ABORTED")));
    assert.deepEqual(await page.evaluate(() => window.createdUrls), await page.evaluate(() => window.revokedUrls));
    assert.deepEqual(errors, []);
  });

  await suite.test("thumbnail empty, broken, warm-cache and repeated URL states release resources", async (context) => {
    const { page, errors } = await open(context, { width: 390, height: 844 });
    await go(page, "/preview");
    assert.equal(await page.locator("#preview").getAttribute("data-loading"), "false");
    await preview(page, "/__cxl/broken.png");
    await page.waitForFunction(() => document.getElementById("preview").dataset.loading === "false");
    assert.equal(await page.locator("#preview").getAttribute("data-url"), "");
    for (const url of ["/__cxl/ready.png", "/__cxl/ready.png?other", "/__cxl/ready.png"]) {
      await preview(page, url);
      await page.waitForFunction(() => document.getElementById("preview").dataset.url.startsWith("blob:"));
    }
    assert.equal(await page.evaluate(() => window.createdUrls.length), 3);
    assert.equal(await page.evaluate(() => window.revokedUrls.length), 2);
    await preview(page, null);
    await page.waitForFunction(() => window.revokedUrls.length === window.createdUrls.length);
    assert.equal(await page.locator("#preview").getAttribute("data-url"), "");
    assert.deepEqual(errors, []);
  });

  await suite.test("cross-origin CORS fetch and native no-CORS fallback both display", async (context) => {
    const { page, errors } = await open(context);
    await go(page, "/preview");
    await preview(page, `${crossUrl}/cors.png`);
    await page.waitForFunction(() => document.getElementById("preview").dataset.url.startsWith("blob:"));
    await preview(page, `${crossUrl}/native.png`);
    await page.waitForFunction((url) => document.getElementById("preview").dataset.url === url, `${crossUrl}/native.png`);
    assert.equal(await page.evaluate(() => window.createdUrls.length), 1);
    assert.equal(await page.evaluate(() => window.revokedUrls.length), 1);
    assert.deepEqual(errors, []);
  });

  await suite.test("real layer rows and cards render Blob thumbnails and release them on departure", async (context) => {
    const { page, errors } = await open(context);
    await go(page, "/consumers");
    await page.waitForSelector(".lcard-thumb--image", { state: "attached" });
    await page.waitForSelector(".lrow-thumb--image", { state: "attached" });
    assert.match(await page.locator(".lcard-thumb--image").getAttribute("style"), /blob:/);
    assert.match(await page.locator(".lrow-thumb--image").getAttribute("style"), /blob:/);
    assert.equal(await page.evaluate(() => window.createdUrls.length), 2);
    await page.getByRole("link", { name: "Dashboard", exact: true }).click();
    await page.waitForSelector("#destination");
    assert.deepEqual(await page.evaluate(() => window.createdUrls.toSorted()), await page.evaluate(() => window.revokedUrls.toSorted()));
    assert.deepEqual(errors, []);
  });

  await suite.test("checked-in CSP allows same-origin image fetch and decoded Blob display", async (context) => {
    const page = await browser.newPage();
    context.after(() => page.close());
    await page.goto(`${base}/__cxl/csp`);
    const dimensions = await page.evaluate(async () => {
      const response = await fetch("/__cxl/ready.png");
      const url = URL.createObjectURL(await response.blob());
      const image = new Image();
      image.src = url;
      document.body.append(image);
      await image.decode();
      const result = [image.naturalWidth, image.naturalHeight];
      URL.revokeObjectURL(url);
      return result;
    });
    assert.deepEqual(dimensions, [1, 1]);
  });
});