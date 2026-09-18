// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import test from "node:test";
import assert from "node:assert/strict";
import { buildRawGpkgUrl } from "./predictionResults.js";
import { downloadPrediction, predictionFilename } from "./predictionDownload.js";
import { createPredictionDownloadOperation } from "./predictionDownloadOperation.js";

const ids = {
  projectId: "11111111-1111-4111-8111-111111111111",
  imageLayerId: "22222222-2222-4222-8222-222222222222", modelId: "1001",
};

test("raw download uses only the strict artifact query fields, not a timestamp parameter", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const url = `/api/${buildRawGpkgUrl(ids)}`;
  const events = [];
  const link = { click() { events.push(this.download); }, remove() {} };
  await downloadPrediction(url, 0, {
    fetchResponse: async (requested, options) => {
      const parsed = new URL(requested, "https://haste.invalid");
      assert.equal(parsed.pathname, "/api/GetModelArtifact");
      assert.deepEqual([...parsed.searchParams.keys()].sort(), ["imageLayerId", "kind", "modelId", "projectId", "version"]);
      assert.equal(parsed.searchParams.get("version"), "0");
      assert.equal(parsed.searchParams.get("kind"), "gpkg");
      assert.equal(parsed.searchParams.has("_"), false);
      assert.equal(options.cache, "no-store");
      return new Response(new Uint8Array([1, 2]), { headers: { "content-disposition": 'attachment; filename="model_raw.gpkg"' } });
    },
    documentObject: { createElement: () => link, body: { appendChild() {} } },
    urls: { createObjectURL: () => "blob:fixture", revokeObjectURL: () => events.push("released") },
  });
  assert.deepEqual(events, ["model_raw.gpkg"]);
  t.mock.timers.tick(1000);
  assert.deepEqual(events, ["model_raw.gpkg", "released"]);
});

for (const status of [400, 404, 500]) {
  test(`raw HTTP ${status} is surfaced rather than downloaded as a JSON GeoPackage`, async () => {
    let clicked = false;
    const changes = [];
    const operation = createPredictionDownloadOperation((url, version, options) => downloadPrediction(url, version, {
      ...options,
      fetchResponse: async () => Response.json({ error: { message: `HTTP ${status} artifact error` } }, { status }),
      documentObject: { createElement: () => ({ click: () => { clicked = true; } }) },
    }), (state) => changes.push(state));
    const outcome = await operation.run(`/api/${buildRawGpkgUrl(ids)}`);
    assert.equal(outcome.error, `HTTP ${status} artifact error`);
    assert.equal(changes.at(-1).loading, false);
    assert.equal(changes.at(-1).error, outcome.error);
    assert.equal(clicked, false);
  });
}

test("repeated raw-download clicks share one pending read and always request raw version zero", async () => {
  let resolve;
  const calls = [];
  const states = [];
  const operation = createPredictionDownloadOperation((url, version) => {
    calls.push({ url, version });
    return new Promise((done) => { resolve = done; });
  }, (state) => states.push(state));
  const url = `/api/${buildRawGpkgUrl(ids)}`;
  const first = operation.run(url);
  const second = operation.run(url);
  assert.equal(first, second);
  await Promise.resolve();
  assert.deepEqual(calls, [{ url, version: 0 }]);
  assert.equal(states.at(-1).loading, true);
  resolve();
  assert.deepEqual(await first, { ok: true });
  assert.equal(states.at(-1).loading, false);
});

test("network failures are returned to the row handler for its error dialog", async () => {
  const operation = createPredictionDownloadOperation(async () => { throw new TypeError("Network failed"); }, () => {});
  const alerts = [];
  const outcome = await operation.run(`/api/${buildRawGpkgUrl(ids)}`);
  if (outcome.error) alerts.push(["Download failed", outcome.error]);
  assert.deepEqual(alerts, [["Download failed", "Network failed"]]);
});

test("unmount cancellation cannot publish a late download error", async () => {
  const states = [];
  const operation = createPredictionDownloadOperation((_url, _version, { signal }) => new Promise((_resolve, reject) => {
    signal.addEventListener("abort", () => reject(signal.reason), { once: true });
  }), (state) => states.push(state));
  const promise = operation.run("/api/artifact");
  await Promise.resolve();
  operation.cancel();
  assert.deepEqual(await promise, { cancelled: true });
  assert.deepEqual(states, [{ loading: true, error: "" }]);
});

test("the shared filename helper preserves protected filenames and safe raw fallbacks", () => {
  assert.equal(predictionFilename("", 0), "predictions_raw.gpkg");
  assert.equal(predictionFilename("attachment; filename*=UTF-8''model%20raw.gpkg", 0), "model raw.gpkg");
});
