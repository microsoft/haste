import assert from "node:assert/strict";
import test from "node:test";

import { loadInteractiveMetadata } from "./loadInteractiveMetadata.js";


function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

test("starts imagery, model, and saved-label requests concurrently", async () => {
  const requests = [deferred(), deferred(), deferred()];
  const calls = [];
  const controller = new AbortController();
  const loading = loadInteractiveMetadata({
    projectId: "project-1",
    imageLayerId: "layer-1",
    modelId: "42",
    signal: controller.signal,
    get: (endpoint, options) => {
      calls.push({ endpoint, options });
      return requests[calls.length - 1].promise;
    },
  });

  assert.equal(calls.length, 3);
  calls.forEach((call) => {
    assert.equal(call.options.signal, controller.signal);
  });
  requests[0].resolve({ imagery: {} });
  requests[1].resolve([{ modelId: "42", pmtilesUrl: "tiles" }]);
  requests[2].resolve({ labels: { building: { label: 1 } } });

  const result = await loading;
  assert.equal(result.model.modelId, "42");
  assert.equal(result.savedLabelsLoaded, true);
  assert.deepEqual(result.savedLabels, { building: { label: 1 } });
});

test("tolerates optional imagery and saved-label failures", async () => {
  const result = await loadInteractiveMetadata({
    projectId: "project-1",
    imageLayerId: "layer-1",
    modelId: "42",
    get: async (endpoint) => {
      if (endpoint.startsWith("GetLayerModelsDetails")) {
        return [{ modelId: "42" }];
      }
      throw new Error("optional unavailable");
    },
  });

  assert.equal(result.layerData, null);
  assert.equal(result.savedLabelsLoaded, false);
  assert.deepEqual(result.savedLabels, {});
});

test("rejects when required model metadata fails", async () => {
  await assert.rejects(
    loadInteractiveMetadata({
      projectId: "project-1",
      imageLayerId: "layer-1",
      modelId: "42",
      get: async (endpoint) => {
        if (endpoint.startsWith("GetLayerModelsDetails")) {
          throw new Error("models unavailable");
        }
        return {};
      },
    }),
    /models unavailable/
  );
});