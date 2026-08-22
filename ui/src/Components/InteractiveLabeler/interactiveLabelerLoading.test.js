import test from "node:test";
import assert from "node:assert/strict";

import {
  createProgressThrottle,
  formatBytes,
  getLoadProgress,
  parseContentLength,
  readResponseBuffer,
  waitForMapReady,
} from "./interactiveLabelerLoading.js";

// Deterministic stand-in for a streamed fetch response. `msPerChunk` advances
// the injected clock on every read so throttling can be asserted without
// real timers.
function createStreamedResponse(chunks, options = {}) {
  const { contentLength, clock, msPerChunk = 0 } = options;
  let index = 0;
  return {
    headers: {
      get: (name) =>
        name === "content-length" && contentLength !== undefined
          ? String(contentLength)
          : null,
    },
    body: {
      getReader: () => ({
        read: async () => {
          if (clock) clock.now += msPerChunk;
          if (index >= chunks.length) return { done: true, value: undefined };
          return { done: false, value: chunks[index++] };
        },
      }),
    },
  };
}

function createChunks(count, size, seed = 1) {
  return Array.from(
    { length: count },
    (_, i) => new Uint8Array(size).fill((seed + i) % 256)
  );
}

function concatChunks(chunks) {
  const total = chunks.reduce((sum, c) => sum + c.byteLength, 0);
  const merged = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return merged;
}

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
test("parseContentLength accepts positive integers and rejects the rest", () => {
  assert.equal(parseContentLength("1024"), 1024);
  assert.equal(parseContentLength(null), null);
  assert.equal(parseContentLength(""), null);
  assert.equal(parseContentLength("not-a-number"), null);
  assert.equal(parseContentLength("0"), null);
  assert.equal(parseContentLength("-5"), null);
  assert.equal(parseContentLength("1e21"), null);
});

test("createProgressThrottle coalesces reports inside the window", () => {
  const clock = { now: 0 };
  const calls = [];
  const throttle = createProgressThrottle((loaded) => calls.push(loaded), {
    throttleMs: 100,
    now: () => clock.now,
  });

  throttle.report(10, 100);
  throttle.report(20, 100);
  throttle.report(30, 100);

  assert.deepEqual(calls, [10]);
});

test("createProgressThrottle emits again once the window elapses", () => {
  const clock = { now: 0 };
  const calls = [];
  const throttle = createProgressThrottle((loaded) => calls.push(loaded), {
    throttleMs: 100,
    now: () => clock.now,
  });

  throttle.report(10, 100);
  clock.now = 150;
  throttle.report(20, 100);

  assert.deepEqual(calls, [10, 20]);
});

test("createProgressThrottle flushes the final count but never duplicates it", () => {
  const clock = { now: 0 };
  const calls = [];
  const throttle = createProgressThrottle((loaded) => calls.push(loaded), {
    throttleMs: 100,
    now: () => clock.now,
  });

  throttle.report(10, 100);
  throttle.report(100, 100);
  throttle.flush(100, 100);
  throttle.flush(100, 100);

  assert.deepEqual(calls, [10, 100]);
});

test("readResponseBuffer throttles progress but always reports the total", async () => {
  const clock = { now: 0 };
  const chunks = createChunks(50, 1024);
  const contentLength = 50 * 1024;
  const calls = [];
  const response = createStreamedResponse(chunks, {
    contentLength,
    clock,
    msPerChunk: 0,
  });

  const buffer = await readResponseBuffer(
    response,
    (loaded, total) => calls.push([loaded, total]),
    { throttleMs: 100, now: () => clock.now }
  );

  assert.equal(buffer.byteLength, contentLength);
  assert.ok(
    calls.length < chunks.length,
    `expected fewer than ${chunks.length} notifications, got ${calls.length}`
  );
  assert.deepEqual(calls.at(-1), [contentLength, contentLength]);
});

test("readResponseBuffer notifies per chunk when each read outlasts the window", async () => {
  const clock = { now: 0 };
  const chunks = createChunks(5, 16);
  const calls = [];
  const response = createStreamedResponse(chunks, {
    contentLength: 5 * 16,
    clock,
    msPerChunk: 200,
  });

  await readResponseBuffer(response, (loaded) => calls.push(loaded), {
    throttleMs: 100,
    now: () => clock.now,
  });

  assert.deepEqual(calls, [16, 32, 48, 64, 80]);
});

test("readResponseBuffer preallocates from Content-Length and preserves bytes", async () => {
  const chunks = createChunks(8, 32, 7);
  const expected = concatChunks(chunks);
  const response = createStreamedResponse(chunks, {
    contentLength: expected.byteLength,
  });

  const buffer = await readResponseBuffer(response, null);

  assert.equal(buffer.byteLength, expected.byteLength);
  assert.deepEqual(new Uint8Array(buffer), expected);
});

test("readResponseBuffer falls back to accumulation without a Content-Length", async () => {
  const chunks = createChunks(4, 64, 3);
  const expected = concatChunks(chunks);
  const response = createStreamedResponse(chunks);

  const buffer = await readResponseBuffer(response, null);

  assert.deepEqual(new Uint8Array(buffer), expected);
});

test("readResponseBuffer rejects a declared length above the cap", async () => {
  const response = createStreamedResponse(createChunks(1, 8), {
    contentLength: 4096,
  });

  await assert.rejects(
    readResponseBuffer(response, null, { maxBytes: 1024 }),
    /above the .* download limit/
  );
});

test("readResponseBuffer bounds an unknown-length body at the cap", async () => {
  const response = createStreamedResponse(createChunks(10, 512));

  await assert.rejects(
    readResponseBuffer(response, null, { maxBytes: 1024 }),
    /exceeded the .* download limit/
  );
});

test("readResponseBuffer keeps every byte when the body outruns Content-Length", async () => {
  const chunks = createChunks(4, 100, 11);
  const expected = concatChunks(chunks);
  const response = createStreamedResponse(chunks, { contentLength: 250 });

  const buffer = await readResponseBuffer(response, null);

  assert.equal(buffer.byteLength, 400);
  assert.deepEqual(new Uint8Array(buffer), expected);
});

test("readResponseBuffer trims the tail when the body is shorter than declared", async () => {
  const chunks = createChunks(2, 50, 5);
  const expected = concatChunks(chunks);
  const response = createStreamedResponse(chunks, { contentLength: 500 });

  const buffer = await readResponseBuffer(response, null);

  assert.equal(buffer.byteLength, 100);
  assert.deepEqual(new Uint8Array(buffer), expected);
});

test("readResponseBuffer handles a response without a readable body", async () => {
  const expected = createChunks(1, 24, 9)[0];
  const calls = [];
  const response = {
    headers: { get: () => null },
    arrayBuffer: async () => expected.buffer,
  };

  const buffer = await readResponseBuffer(response, (loaded, total) =>
    calls.push([loaded, total])
  );

  assert.deepEqual(new Uint8Array(buffer), expected);
  assert.deepEqual(calls, [[24, 24]]);
});
