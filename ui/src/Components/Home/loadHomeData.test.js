import assert from "node:assert/strict";
import test from "node:test";

import { loadHomeData } from "./loadHomeData.js";


function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

test("starts dashboard and catalog requests concurrently", () => {
  const dashboard = deferred();
  const catalog = deferred();
  const calls = [];
  const options = { signal: new AbortController().signal };
  const loading = loadHomeData((endpoint, receivedOptions) => {
    calls.push([endpoint, receivedOptions]);
    return endpoint === "GetDashboardData"
      ? dashboard.promise
      : catalog.promise;
  }, options);

  assert.deepEqual(calls, [
    ["GetDashboardData", options],
    ["GetModelCatalog", options],
  ]);
  assert.equal(loading.dashboard, dashboard.promise);
});

test("dashboard resolves without waiting for the optional catalog", async () => {
  const dashboard = deferred();
  const catalog = deferred();
  const loading = loadHomeData((endpoint) => {
    return endpoint === "GetDashboardData"
      ? dashboard.promise
      : catalog.promise;
  });

  dashboard.resolve({ projects: [] });

  assert.deepEqual(await loading.dashboard, { projects: [] });
  catalog.resolve({ modelCatalog: [{ modelId: "model-1" }] });
  assert.deepEqual(await loading.catalog, [{ modelId: "model-1" }]);
});

test("preserves independent dashboard and catalog failures", async () => {
  const loading = loadHomeData(async (endpoint) => {
    throw new Error(`${endpoint} unavailable`);
  });

  await assert.rejects(loading.dashboard, /GetDashboardData unavailable/);
  await assert.rejects(loading.catalog, /GetModelCatalog unavailable/);
});