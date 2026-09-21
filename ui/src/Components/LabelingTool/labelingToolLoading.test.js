import assert from "node:assert/strict";
import test from "node:test";

import {
  AZURE_MAPS_SATELLITE_TILES,
  getWorkspaceCameraOptions,
  getWorkspaceBounds,
  resolveImageryTileUrl,
  waitForMapIdle,
} from "./labelingToolLoading.js";

function eventTarget() {
  const listeners = new Map();
  return {
    add(name, callback) {
      listeners.set(name, callback);
    },
    remove(name) {
      listeners.delete(name);
    },
    emit(name, value) {
      listeners.get(name)?.(value);
    },
    has(name) {
      return listeners.has(name);
    },
  };
}

test("getWorkspaceBounds uses only workspace features", () => {
  const features = [{ type: "Feature", geometry: { type: "Point" } }];
  const atlas = {
    data: {
      BoundingBox: {
        fromData(value) {
          return value;
        },
      },
    },
  };

  const result = getWorkspaceBounds(atlas, { features });

  assert.deepEqual(result, { type: "FeatureCollection", features });
});

test("getWorkspaceBounds returns null for an empty workspace", () => {
  assert.equal(getWorkspaceBounds({}, { features: [] }), null);
});

test("getWorkspaceCameraOptions fits the AOI without animation", () => {
  const bounds = [-120, 30, -119, 31];

  assert.deepEqual(getWorkspaceCameraOptions(bounds), {
    bounds,
    padding: 24,
    bearing: 0,
    pitch: 0,
    duration: 0,
  });
});

test("resolveImageryTileUrl controls fallback and required imagery", () => {
  assert.equal(resolveImageryTileUrl("https://tiles.test/{z}"), "https://tiles.test/{z}");
  assert.equal(resolveImageryTileUrl(""), AZURE_MAPS_SATELLITE_TILES);
  assert.equal(
    resolveImageryTileUrl("", { allowFallback: false }),
    null
  );
  assert.throws(
    () =>
      resolveImageryTileUrl("", {
        allowFallback: false,
        required: true,
      }),
    /Required post-event imagery/
  );
});

test("waitForMapIdle resolves and removes listeners", async () => {
  const events = eventTarget();
  const loading = waitForMapIdle({ events }, { timeoutMs: 100 });

  events.emit("idle");

  await loading;
  assert.equal(events.has("idle"), false);
  assert.equal(events.has("error"), false);
});

test("waitForMapIdle aborts and removes listeners", async () => {
  const events = eventTarget();
  const controller = new AbortController();
  const loading = waitForMapIdle(
    { events },
    { signal: controller.signal, timeoutMs: 100 }
  );

  controller.abort();

  await assert.rejects(loading, (error) => error.name === "AbortError");
  assert.equal(events.has("idle"), false);
  assert.equal(events.has("error"), false);
});
