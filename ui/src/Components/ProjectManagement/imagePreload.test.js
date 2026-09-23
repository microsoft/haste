import assert from "node:assert/strict";
import test from "node:test";

import { preloadImage } from "./imagePreload.js";

const deferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
};
const settle = () => new Promise((resolve) => setImmediate(resolve));

function harness(fetchImage) {
  const results = [];
  const created = [];
  const revoked = [];
  const sources = [];
  const image = {
    set src(value) { sources.push(value); },
    removeAttribute(name) { assert.equal(name, "src"); },
  };
  const dispose = preloadImage("https://example.test/preview.png", (result) => {
    results.push(result);
  }, {
    fetchImage,
    createImage: () => image,
    objectUrls: {
      createObjectURL(blob) { created.push(blob); return "blob:preview"; },
      revokeObjectURL(url) { revoked.push(url); },
    },
  });
  return { results, created, revoked, sources, image, dispose };
}

test("passes the signal to fetch and aborts a pending transfer without fallback", async () => {
  const pending = deferred();
  let signal;
  const state = harness((_url, options) => {
    signal = options.signal;
    return pending.promise;
  });
  state.dispose();
  assert.equal(signal.aborted, true);
  pending.reject(new TypeError("Network error after abort"));
  await settle();
  assert.deepEqual(state.results, []);
  assert.deepEqual(state.sources, []);
});

test("does not allocate or publish a Blob URL after cancellation during the body read", async () => {
  const body = deferred();
  const state = harness(async () => ({ ok: true, blob: () => body.promise }));
  await settle();
  state.dispose();
  body.resolve(new Blob(["image"]));
  await settle();
  assert.deepEqual(state.created, []);
  assert.deepEqual(state.results, []);
});

test("keeps the decoded Blob URL alive until cleanup and revokes it once", async () => {
  const blob = new Blob(["image"]);
  const state = harness(async () => ({ ok: true, blob: async () => blob }));
  await settle();
  assert.deepEqual(state.results, []);
  assert.deepEqual(state.created, [blob]);
  assert.deepEqual(state.sources, ["blob:preview"]);
  state.image.onload();
  assert.equal(state.results[0].loadedUrl, "blob:preview");
  assert.equal(state.results[0].status, "loaded");
  assert.deepEqual(state.revoked, []);
  const lateLoad = state.image.onload;
  state.dispose();
  state.dispose();
  lateLoad();
  assert.equal(state.results.length, 1);
  assert.equal(state.results[0].signal.aborted, true);
  assert.deepEqual(state.revoked, ["blob:preview"]);
  assert.equal(state.image.onload, null);
  assert.equal(state.image.onerror, null);
});

test("uses native image compatibility fallback when fetch is blocked by CORS", async () => {
  const state = harness(async () => { throw new TypeError("Failed to fetch"); });
  await settle();
  assert.deepEqual(state.sources, ["https://example.test/preview.png"]);
  state.image.onload();
  assert.equal(state.results[0].loadedUrl, "https://example.test/preview.png");
  state.dispose();
  assert.deepEqual(state.created, []);
  assert.deepEqual(state.revoked, []);
});

test("a real HTTP failure ends loading without starting another request", async () => {
  const state = harness(async () => ({ ok: false, status: 404 }));
  await settle();
  assert.equal(state.results[0].status, "error");
  assert.deepEqual(state.sources, []);
  state.dispose();
});

test("a decode failure releases its Blob URL and reports an error", async () => {
  const state = harness(async () => ({ ok: true, blob: async () => new Blob() }));
  await settle();
  state.image.onerror();
  assert.equal(state.results[0].status, "error");
  assert.deepEqual(state.revoked, ["blob:preview"]);
  state.dispose();
  assert.deepEqual(state.revoked, ["blob:preview"]);
});

test("a fresh owner can load after the previous owner was aborted", async () => {
  const first = harness(() => new Promise(() => {}));
  first.dispose();
  const second = harness(async () => ({ ok: true, blob: async () => new Blob() }));
  await settle();
  second.image.onload();
  assert.equal(second.results[0].signal.aborted, false);
  assert.equal(second.results[0].status, "loaded");
  second.dispose();
});