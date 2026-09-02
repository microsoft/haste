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

test("starts dashboard and catalog requests concurrently", async () => {
  const dashboard = deferred();
  const catalog = deferred();
  const calls = [];
  const loading = loadHomeData((endpoint) => {
    calls.push(endpoint);
    return endpoint === "GetDashboardData"
      ? dashboard.promise
      : catalog.promise;
  });

  assert.deepEqual(calls, ["GetDashboardData", "GetModelCatalog"]);
  catalog.resolve({ modelCatalog: [{ modelId: "model-1" }] });
  dashboard.resolve({ projects: [{ projectId: "project-1" }] });

  assert.deepEqual(await loading, {
    dashboardData: { projects: [{ projectId: "project-1" }] },
    dashboardError: null,
    catalog: [{ modelId: "model-1" }],
    catalogError: null,
  });
});

test("keeps dashboard data when the optional catalog fails", async () => {
  const result = await loadHomeData(async (endpoint) => {
    if (endpoint === "GetModelCatalog") {
      throw new Error("catalog unavailable");
    }
    return { projects: [] };
  });

  assert.deepEqual(result.dashboardData, { projects: [] });
  assert.deepEqual(result.catalog, []);
  assert.match(result.catalogError.message, /catalog unavailable/);
});

test("reports a required dashboard failure independently", async () => {
  const result = await loadHomeData(async (endpoint) => {
    if (endpoint === "GetDashboardData") {
      throw new Error("dashboard unavailable");
    }
    return { modelCatalog: [] };
  });

  assert.equal(result.dashboardData, null);
  assert.match(result.dashboardError.message, /dashboard unavailable/);
  assert.deepEqual(result.catalog, []);
});