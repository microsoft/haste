import test from "node:test";
import assert from "node:assert/strict";

import {
  formatBytes,
  getLoadProgress,
  waitForMapReady,
} from "./interactiveLabelerLoading.js";

function createMapEvents() {
  const handlers = new Map();
  return {
    add(name, handler) {
      handlers.set(name, handler);
    },
    remove(name, handler) {
      if (handlers.get(name) === handler) handlers.delete(name);
    },
    emit(name, event) {
      handlers.get(name)?.(event);
    },
    has(name) {
      return handlers.has(name);
    },
  };
}

test("formatBytes keeps one decimal for megabytes", () => {
  assert.equal(formatBytes(31 * 1024 * 1024), "31.0 MB");
  assert.equal(formatBytes(330 * 1024 * 1024), "330.0 MB");
});

test("getLoadProgress reaches one on the final step", () => {
  assert.equal(getLoadProgress(0, 6), 1 / 6);
  assert.equal(getLoadProgress(5, 6), 1);
});

test("waitForMapReady resolves and removes listeners on ready", async () => {
  const events = createMapEvents();
  let readyCalls = 0;
  const result = waitForMapReady(
    { events },
    { timeoutMs: 100, onReady: () => readyCalls++ }
  );

  events.emit("ready");
  await result;

  assert.equal(readyCalls, 1);
  assert.equal(events.has("ready"), false);
  assert.equal(events.has("error"), false);
});

test("waitForMapReady rejects an Azure Maps error", async () => {
  const events = createMapEvents();
  const result = waitForMapReady({ events }, { timeoutMs: 100 });

  events.emit("error", { error: new Error("authentication failed") });

  await assert.rejects(result, /authentication failed/);
});

test("waitForMapReady rejects when loading times out", async () => {
  const events = createMapEvents();

  await assert.rejects(
    waitForMapReady({ events }, { timeoutMs: 1 }),
    /timed out/
  );
  assert.equal(events.has("ready"), false);
  assert.equal(events.has("error"), false);
});

test("waitForMapReady rejects when initialization is aborted", async () => {
  const events = createMapEvents();
  const controller = new AbortController();
  const result = waitForMapReady(
    { events },
    { signal: controller.signal, timeoutMs: 100 }
  );

  controller.abort();

  await assert.rejects(result, { name: "AbortError" });
  assert.equal(events.has("ready"), false);
  assert.equal(events.has("error"), false);
});