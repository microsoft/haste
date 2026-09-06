// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Execute the same transport and commit boundary used by the labeler handlers.
import test from "node:test";
import assert from "node:assert/strict";
import {
  clearLabelsAndPredictions, createLabelerWriter, saveBuildingPredictions,
} from "./interactiveLabelerPersistence.js";

const ids = { projectId: "project", imageLayerId: "layer", modelId: "model" };
const predictions = [{ id: 0, damaged: 1, unknown: 0 }];

function response(status) {
  if (status === "network") throw new TypeError("Failed to fetch");
  if (status === 204) return new Response(null, { status });
  return Response.json(
    status === 200 ? { success: true } :
      { error: { code: status === 409 ? "save_conflict" : "write_failed", message: `Fixture HTTP ${status}` } },
    { status },
  );
}

function stateFixture() {
  return {
    labels: { 0: { label: 0, features: [1, 0] } },
    savedLabels: { a: { label: "NotDamaged", rowId: 0, n: 1 } },
    predictions: { 0: 0 },
    status: "One local label",
    mapClears: 0,
    commits: 0,
  };
}

for (const status of [200, 409, 500, "network"]) {
  test(`Predict All / ${status}: commit and saved feedback require a confirmed write`, async () => {
    const state = stateFixture();
    const before = structuredClone(state);
    const calls = [];
    const write = createLabelerWriter((endpoint) => `/api/${endpoint}`, async (url, options) => {
      calls.push({ url, options });
      return response(status);
    });
    const operation = saveBuildingPredictions(write, { ...ids, predictions }, () => {
      state.predictions = { 0: 1 };
      state.status = "Predicted 1 building and saved.";
      state.commits++;
    });
    if (status === 200) {
      await operation;
      assert.equal(state.commits, 1);
      assert.equal(state.predictions[0], 1);
      assert.match(state.status, /and saved/);
    } else {
      await assert.rejects(operation, (error) => {
        if (status === "network") assert.equal(error.outcomeUnknown, true);
        else assert.equal(error.status, status);
        return true;
      });
      assert.deepEqual(state, before);
      assert.doesNotMatch(state.status, /saved/);
    }
    assert.equal(calls.length, 1);
    assert.equal(calls[0].url, "/api/PutBuildingPredictions");
    assert.equal(calls[0].options.method, "PUT");
    assert.deepEqual(JSON.parse(calls[0].options.body), { ...ids, predictions });
  });

  test(`Clear / prediction write ${status}: preserve recovery copies until both writes succeed`, async () => {
    const state = stateFixture();
    const before = structuredClone(state);
    const calls = [];
    const write = createLabelerWriter((endpoint) => `/api/${endpoint}`, async (url, options) => {
      calls.push({ url, body: JSON.parse(options.body) });
      return response(url.endsWith("PutInteractiveLabels") ? 200 : status);
    });
    const operation = clearLabelsAndPredictions(write, ids, () => {
      state.labels = {};
      state.savedLabels = {};
      state.predictions = {};
      state.mapClears = 2;
      state.commits++;
      state.status = "Cleared all labels and predictions.";
    });
    if (status === 200) {
      await operation;
      assert.deepEqual(state.labels, {});
      assert.deepEqual(state.predictions, {});
      assert.equal(state.mapClears, 2);
      assert.equal(state.commits, 1);
      assert.equal(state.status, "Cleared all labels and predictions.");
    } else {
      await assert.rejects(operation, (error) => {
        assert.equal(error.labelsCleared, true);
        assert.match(error.message, /Partial clear: labels were cleared on the server/);
        assert.match(error.message, /Local labels and predictions have been kept/);
        assert.doesNotMatch(error.message, /Cleared all labels and predictions\./);
        if (status !== "network") assert.equal(error.status, status);
        return true;
      });
      assert.deepEqual(state, before);
    }
    assert.deepEqual(calls, [
      { url: "/api/PutInteractiveLabels", body: { ...ids, labels: {} } },
      { url: "/api/PutBuildingPredictions", body: { ...ids, predictions: [] } },
    ]);
  });
}

for (const status of [409, 500, "network"]) {
  test(`Clear / label write ${status}: do not request prediction clear or commit local state`, async () => {
    const calls = [];
    let committed = false;
    const write = createLabelerWriter((endpoint) => `/api/${endpoint}`, async (url) => {
      calls.push(url);
      return response(status);
    });
    await assert.rejects(clearLabelsAndPredictions(write, ids, () => { committed = true; }), (error) => {
      assert.equal(error.labelsCleared, false);
      assert.match(error.message, /prediction clearing was not requested/);
      assert.match(error.message, /Local labels and predictions have been kept/);
      return true;
    });
    assert.equal(committed, false);
    assert.deepEqual(calls, ["/api/PutInteractiveLabels"]);
  });
}

test("clear does not change counts, feature state or status while either write is pending", async () => {
  const pending = [];
  const state = stateFixture();
  const before = structuredClone(state);
  const write = createLabelerWriter((endpoint) => endpoint, () => new Promise((resolve) => pending.push(resolve)));
  const operation = clearLabelsAndPredictions(write, ids, () => {
    state.labels = {};
    state.predictions = {};
    state.mapClears = 2;
    state.status = "Cleared all labels and predictions.";
  });
  assert.deepEqual(state, before);
  pending[0](response(200));
  // Let the first response JSON and the following PUT start.
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(pending.length, 2);
  assert.deepEqual(state, before);
  pending[1](response(200));
  await operation;
  assert.equal(state.mapClears, 2);
  assert.equal(state.status, "Cleared all labels and predictions.");
});

test("prediction state is not published locally while persistence is pending", async () => {
  let resolve;
  let committed = false;
  const write = createLabelerWriter((endpoint) => endpoint, () => new Promise((done) => { resolve = done; }));
  const operation = saveBuildingPredictions(write, { ...ids, predictions }, () => { committed = true; });
  assert.equal(committed, false);
  resolve(response(200));
  await operation;
  assert.equal(committed, true);
});

test("label writes retain structured conflicts instead of resolving to numeric 409", async () => {
  const write = createLabelerWriter((endpoint) => endpoint, async () => response(409));
  await assert.rejects(write("PutInteractiveLabels", { ...ids, labels: {} }), {
    status: 409, code: "save_conflict", message: "Fixture HTTP 409",
  });
});

test("accepted work, error bodies and missing confirmation cannot claim success", async () => {
  for (const getResponse of [
    () => Response.json({ success: true }, { status: 202 }),
    () => Response.json({ success: false, message: "Not saved" }),
    () => Response.json({ error: "Not saved" }),
    () => new Response("not JSON", { status: 200 }),
  ]) {
    let committed = false;
    const write = createLabelerWriter((endpoint) => endpoint, async () => getResponse());
    await assert.rejects(saveBuildingPredictions(write, { ...ids, predictions }, () => { committed = true; }));
    assert.equal(committed, false);
  }
});

test("explicit 204 completion is supported without a JSON body", async () => {
  const write = createLabelerWriter((endpoint) => endpoint, async () => response(204));
  let committed = false;
  await clearLabelsAndPredictions(write, ids, () => { committed = true; });
  assert.equal(committed, true);
});

test("scoped writer cannot be used to submit unrelated work", async () => {
  let requested = false;
  const write = createLabelerWriter((endpoint) => endpoint, async () => { requested = true; });
  await assert.rejects(write("PutUnrelatedQueueMessage", {}), /Unsupported labeler write/);
  assert.equal(requested, false);
});
