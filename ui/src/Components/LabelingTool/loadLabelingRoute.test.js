import assert from "node:assert/strict";
import test from "node:test";

import { loadLabelingRoute } from "./loadLabelingRoute.js";

function deferred() {
  let resolve;
  const promise = new Promise((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

test("starts route, Maps, and workspace requests concurrently", async () => {
  const route = deferred();
  const maps = deferred();
  const workspace = deferred();
  const calls = [];
  const controller = new AbortController();

  const loading = loadLabelingRoute({
    importRoute: () => {
      calls.push("route");
      return route.promise;
    },
    loadMaps: () => {
      calls.push("maps");
      return maps.promise;
    },
    get: (endpoint, options) => {
      calls.push({ endpoint, options });
      return workspace.promise;
    },
    projectId: "project-1",
    imageLayerId: "layer-1",
    signal: controller.signal,
  });

  assert.deepEqual(calls.slice(0, 2), ["route", "maps"]);
  assert.equal(
    calls[2].endpoint,
    "GetLabelingWorkspace?projectId=project-1&imageLayerId=layer-1"
  );
  assert.equal(calls[2].options.signal, controller.signal);

  route.resolve({ default: "LabelingTool" });
  maps.resolve();
  workspace.resolve({ imageLayer: { imageLayerId: "layer-1" } });

  assert.deepEqual(await loading, {
    Component: "LabelingTool",
    workspace: { imageLayer: { imageLayerId: "layer-1" } },
  });
});
