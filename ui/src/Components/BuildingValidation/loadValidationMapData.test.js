import assert from "node:assert/strict";
import test from "node:test";

import { loadValidationMapData } from "./loadValidationMapData.js";


function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

test("overlaps optional imagery with required validation data", async () => {
  const imagery = deferred();
  const validation = deferred();
  const footprints = deferred();
  const calls = [];
  const loading = loadValidationMapData({
    projectId: "project-1",
    imageLayerId: "layer-1",
    resolveSampleSize: () => 300,
    get: (endpoint) => {
      calls.push(endpoint);
      if (endpoint.startsWith("GetLayerLabelingToolData")) {
        return imagery.promise;
      }
      if (endpoint.startsWith("GetBuildingValidation")) {
        return validation.promise;
      }
      return footprints.promise;
    },
  });

  assert.equal(calls.length, 2);
  validation.resolve({ labels: {} });
  await Promise.resolve();
  assert.equal(calls.length, 3);
  imagery.resolve({ imagery: {} });
  footprints.resolve({ features: [] });

  assert.deepEqual(await loading, {
    layerData: { imagery: {} },
    validationData: { labels: {} },
    footprintsGeoJSON: { features: [] },
    sampleSize: 300,
  });
});

test("continues without optional imagery", async () => {
  const result = await loadValidationMapData({
    projectId: "project-1",
    imageLayerId: "layer-1",
    resolveSampleSize: () => 100,
    get: async (endpoint) => {
      if (endpoint.startsWith("GetLayerLabelingToolData")) {
        throw new Error("no labels");
      }
      if (endpoint.startsWith("GetBuildingValidation")) {
        return { labels: {} };
      }
      return { features: [] };
    },
  });

  assert.equal(result.layerData, null);
  assert.deepEqual(result.footprintsGeoJSON, { features: [] });
});

test("rejects when required validation data fails", async () => {
  await assert.rejects(
    loadValidationMapData({
      projectId: "project-1",
      imageLayerId: "layer-1",
      resolveSampleSize: () => 100,
      get: async (endpoint) => {
        if (endpoint.startsWith("GetBuildingValidation")) {
          throw new Error("validation unavailable");
        }
        return {};
      },
    }),
    /validation unavailable/
  );
});