import test from "node:test";
import assert from "node:assert/strict";

import {
  TILE_CREDENTIAL_FALLBACK_REFRESH_MS,
  TILE_CREDENTIAL_REFRESH_BUFFER_MS,
  TILE_CREDENTIAL_RETRY_MS,
  applyTileCredentialUpdate,
  createTileCredentialRefreshController,
  getTileCredentialRefreshAt,
  getTileCredentialRefreshDelay,
} from "./tileCredentialRefresh.js";

function fakeScheduler() {
  let nextId = 1;
  const timers = new Map();
  const cleared = [];
  return {
    timers,
    cleared,
    setTimer(callback, delay) {
      const id = nextId;
      nextId += 1;
      timers.set(id, { callback, delay });
      return id;
    },
    clearTimer(id) {
      cleared.push(id);
      timers.delete(id);
    },
  };
}

function fakeDocument() {
  const listeners = new Set();
  return {
    visibilityState: "hidden",
    listeners,
    addEventListener(eventName, listener) {
      if (eventName === "visibilitychange") listeners.add(listener);
    },
    removeEventListener(eventName, listener) {
      if (eventName === "visibilitychange") listeners.delete(listener);
    },
    async dispatchVisibilityChange() {
      await Promise.all([...listeners].map((listener) => listener()));
    },
  };
}

test("calculates expiry refresh five minutes early and a 45-minute fallback", () => {
  const now = Date.parse("2026-08-07T12:00:00.000Z");
  const expiresAt = "2026-08-07T13:00:00.000Z";

  assert.equal(
    getTileCredentialRefreshAt(expiresAt, now),
    Date.parse(expiresAt) - TILE_CREDENTIAL_REFRESH_BUFFER_MS
  );
  assert.equal(
    getTileCredentialRefreshDelay(expiresAt, now),
    55 * 60 * 1000
  );
  assert.equal(
    getTileCredentialRefreshAt(undefined, now),
    now + TILE_CREDENTIAL_FALLBACK_REFRESH_MS
  );
});

test("refreshes on visible when the scheduled refresh time is due", async () => {
  let clock = Date.parse("2026-08-07T12:00:00.000Z");
  const scheduler = fakeScheduler();
  const documentTarget = fakeDocument();
  let fetchCount = 0;
  let applyCount = 0;
  const initialData = {
    tileCredentialExpiresAt: "2026-08-07T13:00:00.000Z",
  };

  const controller = createTileCredentialRefreshController({
    fetchCredentials: async () => {
      fetchCount += 1;
      return {
        ...initialData,
        tileCredentialExpiresAt: "2026-08-07T14:00:00.000Z",
      };
    },
    applyCredentials: () => {
      applyCount += 1;
    },
    now: () => clock,
    setTimer: scheduler.setTimer,
    clearTimer: scheduler.clearTimer,
    documentTarget,
  });

  controller.start(initialData);
  clock = getTileCredentialRefreshAt(initialData.tileCredentialExpiresAt, clock);
  documentTarget.visibilityState = "visible";
  await documentTarget.dispatchVisibilityChange();

  assert.equal(fetchCount, 1);
  assert.equal(applyCount, 1);
  assert.equal(scheduler.timers.size, 1);
  controller.dispose();
});

test("updates existing layers without replacing unsaved state", () => {
  const unsavedLabels = [{ id: "unsaved-label" }];
  const validationSelections = new Set(["building-7"]);
  const dataRef = {
    current: {
      imagery: {
        preEventTileUrl: "https://tiles.example/pre-old/{z}/{x}/{y}",
        postEventTileUrl: "https://tiles.example/post-old/{z}/{x}/{y}",
      },
      labels: unsavedLabels,
      validationSelections,
      unsavedEdits: true,
    },
  };
  const preLayer = {
    calls: [],
    setOptions(options) {
      this.calls.push(options);
    },
  };
  const postLayer = {
    calls: [],
    setOptions(options) {
      this.calls.push(options);
    },
  };
  let appliedData = null;

  applyTileCredentialUpdate({
    dataRef,
    nextData: {
      imagery: {
        preEventTileUrl: "https://tiles.example/pre-new/{z}/{x}/{y}",
        postEventTileUrl: "https://tiles.example/post-new/{z}/{x}/{y}",
      },
      labels: [{ id: "stale-server-label" }],
      tileCredentialExpiresAt: "2026-08-07T14:00:00.000Z",
    },
    layerBindings: [
      { layerRef: { current: preLayer }, imageryKey: "preEventTileUrl" },
      { layerRef: { current: postLayer }, imageryKey: "postEventTileUrl" },
    ],
    onApplied: (data) => {
      appliedData = data;
    },
  });

  assert.strictEqual(dataRef.current.labels, unsavedLabels);
  assert.strictEqual(
    dataRef.current.validationSelections,
    validationSelections
  );
  assert.equal(dataRef.current.unsavedEdits, true);
  assert.deepEqual(preLayer.calls, [
    { tileUrl: "https://tiles.example/pre-new/{z}/{x}/{y}" },
  ]);
  assert.deepEqual(postLayer.calls, [
    { tileUrl: "https://tiles.example/post-new/{z}/{x}/{y}" },
  ]);
  assert.strictEqual(appliedData, dataRef.current);
});

test("updates the data ref when a TileLayer has not been created yet", () => {
  const dataRef = {
    current: {
      imagery: {
        preEventTileUrl: "old-pre",
        postEventTileUrl: "old-post",
      },
    },
  };

  applyTileCredentialUpdate({
    dataRef,
    nextData: {
      imagery: {
        preEventTileUrl: "new-pre",
        postEventTileUrl: "new-post",
      },
    },
    layerBindings: [
      { layerRef: { current: null }, imageryKey: "preEventTileUrl" },
    ],
  });

  assert.equal(dataRef.current.imagery.preEventTileUrl, "new-pre");
  assert.equal(dataRef.current.imagery.postEventTileUrl, "new-post");
});

test("a missing pre-event URL is treated as empty, not as a failure", () => {
  const dataRef = {
    current: { imagery: { postEventTileUrl: "old-post" } },
  };

  applyTileCredentialUpdate({
    dataRef,
    nextData: { imagery: { postEventTileUrl: "new-post" } },
  });

  assert.equal(dataRef.current.imagery.preEventTileUrl, "");
  assert.equal(dataRef.current.imagery.postEventTileUrl, "new-post");
});

test("a response without imagery is rejected and current data is kept", () => {
  const previousData = { imagery: { postEventTileUrl: "old-post" } };
  const dataRef = { current: previousData };

  assert.throws(() =>
    applyTileCredentialUpdate({ dataRef, nextData: {} })
  );
  assert.strictEqual(dataRef.current, previousData);
});

test("a TileLayer update failure rolls back URLs and retains current data", () => {
  const previousData = {
    imagery: {
      preEventTileUrl: "old-pre",
      postEventTileUrl: "old-post",
    },
    labels: [{ id: "unsaved" }],
  };
  const dataRef = { current: previousData };
  const preCalls = [];
  const postCalls = [];
  const preLayer = {
    setOptions(options) {
      preCalls.push(options);
    },
  };
  const postLayer = {
    setOptions(options) {
      postCalls.push(options);
      if (options.tileUrl === "new-post") {
        throw new Error("renderer rejected update");
      }
    },
  };

  assert.throws(() =>
    applyTileCredentialUpdate({
      dataRef,
      nextData: {
        imagery: {
          preEventTileUrl: "new-pre",
          postEventTileUrl: "new-post",
        },
      },
      layerBindings: [
        { layerRef: { current: preLayer }, imageryKey: "preEventTileUrl" },
        { layerRef: { current: postLayer }, imageryKey: "postEventTileUrl" },
      ],
    })
  );

  assert.strictEqual(dataRef.current, previousData);
  assert.deepEqual(preCalls, [
    { tileUrl: "new-pre" },
    { tileUrl: "old-pre" },
  ]);
  assert.deepEqual(postCalls, [
    { tileUrl: "new-post" },
    { tileUrl: "old-post" },
  ]);
});

test("failed refresh retains current data and schedules a recoverable retry", async () => {
  const scheduler = fakeScheduler();
  const documentTarget = fakeDocument();
  const currentData = {
    imagery: {
      preEventTileUrl: "current-pre",
      postEventTileUrl: "current-post",
    },
    labels: [{ id: "unsaved" }],
  };
  let errorCount = 0;
  let applyCount = 0;

  const controller = createTileCredentialRefreshController({
    fetchCredentials: async () => {
      throw new Error("network unavailable");
    },
    applyCredentials: () => {
      applyCount += 1;
    },
    onError: () => {
      errorCount += 1;
    },
    setTimer: scheduler.setTimer,
    clearTimer: scheduler.clearTimer,
    documentTarget,
  });

  controller.start(currentData);
  const refreshed = await controller.refresh();

  assert.equal(refreshed, false);
  assert.equal(applyCount, 0);
  assert.equal(errorCount, 1);
  assert.strictEqual(currentData.labels[0].id, "unsaved");
  assert.deepEqual(
    [...scheduler.timers.values()].map((timer) => timer.delay),
    [TILE_CREDENTIAL_RETRY_MS]
  );
  controller.dispose();
});

test("cleanup clears the timer, removes visibility listener, and blocks updates", async () => {
  const scheduler = fakeScheduler();
  const documentTarget = fakeDocument();
  let fetchCount = 0;
  const controller = createTileCredentialRefreshController({
    fetchCredentials: async () => {
      fetchCount += 1;
      return {};
    },
    applyCredentials: () => {},
    setTimer: scheduler.setTimer,
    clearTimer: scheduler.clearTimer,
    documentTarget,
  });

  controller.start({});
  assert.equal(documentTarget.listeners.size, 1);
  assert.equal(scheduler.timers.size, 1);

  controller.dispose();
  documentTarget.visibilityState = "visible";
  await documentTarget.dispatchVisibilityChange();
  const refreshed = await controller.refresh();

  assert.equal(documentTarget.listeners.size, 0);
  assert.equal(scheduler.timers.size, 0);
  assert.equal(scheduler.cleared.length, 1);
  assert.equal(fetchCount, 0);
  assert.equal(refreshed, false);
});
