// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import test from "node:test";
import assert from "node:assert/strict";
import { PMTiles } from "pmtiles";
import {
  footprintArchiveUrl, getPmtilesProtocol, HttpPMTilesSource, loadFootprintArchive,
} from "./pmtiles.js";

function archiveFixture() {
  const bytes = new Uint8Array(70000);
  bytes.set(new TextEncoder().encode("PMTiles"));
  const header = new DataView(bytes.buffer);
  header.setUint8(7, 3);
  for (const [offset, value] of [[8, 127], [16, 5], [56, 65536], [64, 4], [72, 1], [80, 1], [88, 1]]) {
    header.setBigUint64(offset, BigInt(value), true);
  }
  bytes.set([1, 1, 1, 1], 96);
  bytes.set([1, 0, 1, 4, 1], 127);
  bytes.set([11, 22, 33, 44], 65536);
  return bytes;
}

function serveRanges(t, bytes = archiveFixture()) {
  const requests = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    const range = options.headers.get("range");
    const match = /^bytes=(\d+)-(\d+)$/.exec(range);
    assert.ok(match, "Every PMTiles request must specify a bounded byte range");
    const start = Number(match[1]);
    const end = Math.min(Number(match[2]), bytes.length - 1);
    requests.push({ url, range, bytes: end - start + 1, signal: options.signal });
    return new Response(bytes.slice(start, end + 1), {
      status: 206,
      headers: {
        "Content-Range": `bytes ${start}-${end}/${bytes.length}`,
        "Content-Length": String(end - start + 1),
        ETag: '"fixture-etag"',
      },
    });
  });
  globalThis.window = { atlas: { addProtocol() {} } };
  t.after(() => { delete globalThis.window; });
  return requests;
}

test("labeling and results share one protocol and archive cache", () => {
  const registrations = [];
  const atlas = { addProtocol: (...args) => registrations.push(args) };
  const labeling = getPmtilesProtocol(atlas);
  const results = getPmtilesProtocol(atlas);
  assert.equal(labeling, results);
  assert.equal(registrations.length, 1);
  assert.equal(registrations[0][0], "pmtiles");
  const archive = new PMTiles(new HttpPMTilesSource("/api/fixture"));
  labeling.add(archive);
  assert.equal(results.get("/api/fixture"), archive);
});

test("protocol registration waits for a usable SDK and can register a later SDK instance", () => {
  assert.throws(() => getPmtilesProtocol(null), /does not support/);
  const atlas = { addProtocol() {} };
  assert.ok(getPmtilesProtocol(atlas));
});

test("footprint URLs use the layer identity without model or query-order cache splits", () => {
  const expected = "/api/GetModelArtifact?imageLayerId=l&kind=footprint_pmtiles&projectId=p";
  for (const url of [
    "/api/GetModelArtifact?projectId=p&modelId=1&imageLayerId=l&kind=footprint_pmtiles",
    "/api/GetModelArtifact?kind=footprint_pmtiles&imageLayerId=l&modelId=2&projectId=p",
  ]) assert.equal(footprintArchiveUrl(url), expected);
  const modelOnly = "/api/GetModelArtifact?kind=footprint_pmtiles&modelId=1&projectId=p";
  assert.equal(footprintArchiveUrl(modelOnly), modelOnly);
  const sidecar = "/api/GetModelArtifact?kind=sidecar&modelId=1&projectId=p";
  assert.equal(footprintArchiveUrl(sidecar), sidecar);
});

test("opening footprints reads only the header; viewport requests fetch tile bytes on demand", async (t) => {
  const requests = serveRanges(t);
  const initial = new AbortController();
  const url = "/api/GetModelArtifact?projectId=p&modelId=1&imageLayerId=range-layer&kind=footprint_pmtiles";
  const loaded = await loadFootprintArchive(url, initial.signal);
  assert.equal(loaded.header.specVersion, 3);
  assert.equal(loaded.header.etag, '"fixture-etag"');
  assert.deepEqual(requests.map((request) => request.range), ["bytes=0-16383"]);
  assert.equal(requests[0].bytes, 16384);
  assert.doesNotMatch(loaded.archiveKey, /modelId/);

  initial.abort();
  const reused = await loadFootprintArchive(url.replace("modelId=1", "modelId=2"));
  assert.equal(reused.archiveKey, loaded.archiveKey);
  assert.equal(requests.length, 1);
  const archive = getPmtilesProtocol().get(loaded.archiveKey);
  const tile = await archive.getZxy(0, 0, 0);
  assert.deepEqual(new Uint8Array(tile.data), Uint8Array.from([11, 22, 33, 44]));
  assert.deepEqual(requests.map((request) => request.range), ["bytes=0-16383", "bytes=65536-65539"]);
  assert.equal(requests.reduce((total, request) => total + request.bytes, 0), 16388);
});

test("range failures reject without reading or falling back to a full response", async (t) => {
  for (const status of [200, 401, 403, 404, 500]) {
    let bodyRead = false;
    let requestSignal;
    const fetch = t.mock.method(globalThis, "fetch", async (_url, options) => {
      requestSignal = options.signal;
      assert.equal(options.headers.get("range"), "bytes=0-16383");
      return {
        status,
        headers: new Headers({ "Content-Length": "70000" }),
        arrayBuffer: async () => { bodyRead = true; return new ArrayBuffer(70000); },
      };
    });
    await assert.rejects(new HttpPMTilesSource("/api/unsupported").getBytes(0, 16384),
      status === 200 ? /Byte Serving/ : new RegExp(`Bad response code: ${status}`));
    assert.equal(fetch.mock.callCount(), 1);
    assert.equal(bodyRead, false);
    assert.equal(requestSignal.aborted, true);
    fetch.mock.restore();
  }
});

test("aborted initialization never publishes a broken archive and can be retried", async (t) => {
  const requests = serveRanges(t);
  const url = "/api/aborted-range-archive";
  const controller = new AbortController();
  const reason = new DOMException("Left results", "AbortError");
  const fetch = t.mock.method(globalThis, "fetch", async (_url, options) =>
    new Promise((_resolve, reject) => {
      options.signal.addEventListener("abort", () => reject(options.signal.reason), { once: true });
    }));
  const pending = loadFootprintArchive(url, controller.signal);
  controller.abort(reason);
  await assert.rejects(pending, (error) => error === reason);
  assert.equal(getPmtilesProtocol().get(url), undefined);
  fetch.mock.restore();
  await loadFootprintArchive(url);
  assert.equal(requests.length, 1);
});

test("already-aborted loads do not fetch or register an archive", async (t) => {
  const requests = serveRanges(t);
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(loadFootprintArchive("/api/already-aborted", controller.signal), { name: "AbortError" });
  assert.equal(requests.length, 0);
});

test("renderer cancellation and range timeouts abort the underlying fetch", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  t.mock.method(globalThis, "fetch", async (_url, options) =>
    new Promise((_resolve, reject) => {
      options.signal.addEventListener("abort", () => reject(options.signal.reason), { once: true });
    }));
  const controller = new AbortController();
  const source = new HttpPMTilesSource("/api/slow-range", { timeoutMs: 10 });
  const cancelled = source.getBytes(0, 16, controller.signal);
  controller.abort();
  await assert.rejects(cancelled, { name: "AbortError" });
  const timedOut = source.getBytes(0, 16);
  t.mock.timers.tick(10);
  await assert.rejects(timedOut, /PMTiles range request timed out/);
});

test("the HTTP source preserves PMTiles ETag mismatch detection", async (t) => {
  serveRanges(t);
  const source = new HttpPMTilesSource("/api/changed-range");
  await assert.rejects(source.getBytes(0, 16, undefined, '"older-etag"'), /non-matching ETag/);
  assert.equal(source.mustReload, true);
});
