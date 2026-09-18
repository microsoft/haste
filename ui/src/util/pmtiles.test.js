// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Range/cache regression fixtures ported from #201 (51d1ab8).
import test from "node:test";
import assert from "node:assert/strict";
import { PMTiles } from "pmtiles";
import {
  footprintArchiveUrl, getPmtilesProtocol, HttpPMTilesSource, loadFootprintArchive,
  MAX_PMTILES_RANGE_BYTES,
} from "./pmtiles.js";
import { loadPredictionArtifacts } from "../Components/Visualizer/predictionArtifactLoader.js";

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
  const previousWindow = globalThis.window;
  globalThis.window = { atlas: { addProtocol() {} } };
  t.after(() => {
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
  });
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

test("opening footprints reads only the header/root; viewport requests fetch tile bytes on demand", async (t) => {
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

test("even a small or lengthless HTTP 200 is rejected before reading its body", async (t) => {
  for (const headers of [{ "Content-Length": "4" }, {}]) {
    let read = false;
    const fetch = t.mock.method(globalThis, "fetch", async () => ({
      status: 200, headers: new Headers(headers),
      arrayBuffer: async () => { read = true; return new ArrayBuffer(4); },
    }));
    await assert.rejects(new HttpPMTilesSource("/api/full").getBytes(0, 16384), /HTTP 206/);
    assert.equal(read, false);
    assert.equal(fetch.mock.callCount(), 1);
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

test("range timeout includes body streaming, not just response headers", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  let cancelled = false;
  t.mock.method(globalThis, "fetch", async () => new Response(new ReadableStream({
    cancel() { cancelled = true; },
  }), { status: 206, headers: { "Content-Range": "bytes 0-15/70000" } }));
  const pending = new HttpPMTilesSource("/api/slow-body", { timeoutMs: 10 }).getBytes(0, 16);
  await new Promise((resolve) => setImmediate(resolve));
  t.mock.timers.tick(10);
  await assert.rejects(pending, /timed out/);
  assert.equal(cancelled, true);
});

test("the HTTP source preserves PMTiles ETag mismatch detection", async (t) => {
  serveRanges(t);
  const source = new HttpPMTilesSource("/api/changed-range");
  await assert.rejects(source.getBytes(0, 16, undefined, '"older-etag"'), /non-matching ETag/);
  assert.equal(source.mustReload, true);
});

test("test_range_source_preserves_conditional_headers_and_response_cache_metadata", async (t) => {
  t.mock.method(globalThis, "fetch", async (_url, { headers }) => {
    assert.equal(headers.get("Range"), "bytes=0-3");
    assert.equal(headers.get("If-None-Match"), '"cached"');
    return new Response(new Uint8Array(4), {
      status: 206,
      headers: {
        "Content-Range": "bytes 0-3/70000", ETag: '"current"',
        "Cache-Control": "private, max-age=60", Expires: "Wed, 23 Sep 2026 12:00:00 GMT",
      },
    });
  });
  const source = new HttpPMTilesSource("/api/conditional");
  source.setHeaders(new Headers({ "If-None-Match": '"cached"' }));
  const result = await source.getBytes(0, 4);
  assert.equal(result.etag, '"current"');
  assert.equal(result.cacheControl, "private, max-age=60");
  assert.equal(result.expires, "Wed, 23 Sep 2026 12:00:00 GMT");
});

test("test_weak_etags_do_not_trigger_a_false_generation_mismatch", async (t) => {
  t.mock.method(globalThis, "fetch", async () => new Response(new Uint8Array(4), {
    status: 206, headers: { "Content-Range": "bytes 0-3/70000", ETag: 'W/"weak"' },
  }));
  const source = new HttpPMTilesSource("/api/weak-etag");
  const result = await source.getBytes(0, 4, undefined, '"strong"');
  assert.equal(result.etag, undefined);
  assert.equal(source.mustReload, false);
});

test("ETag changes invalidate cached headers and retry viewport reads with reload", async (t) => {
  serveRanges(t);
  const archive = new PMTiles(new HttpPMTilesSource("/api/etag-retry"));
  await archive.getHeader();
  const originalFetch = globalThis.fetch;
  const requests = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    requests.push({ range: options.headers.get("Range"), cache: options.cache });
    const response = await originalFetch(url, options);
    response.headers.set("ETag", '"new-etag"');
    return response;
  });
  const tile = await archive.getZxy(0, 0, 0);
  assert.equal(tile.data.byteLength, 4);
  assert.deepEqual(requests, [
    { range: "bytes=65536-65539", cache: undefined },
    { range: "bytes=0-16383", cache: "reload" },
    { range: "bytes=65536-65539", cache: "reload" },
  ]);
});

test("short archives retry a bounded range after 416, never an unconditional GET", async (t) => {
  const ranges = [];
  t.mock.method(globalThis, "fetch", async (_url, options) => {
    ranges.push(options.headers.get("Range"));
    return ranges.length === 1
      ? new Response(null, { status: 416, headers: { "Content-Range": "bytes */4" } })
      : new Response(new Uint8Array(4), { status: 206, headers: { "Content-Range": "bytes 0-3/4" } });
  });
  const result = await new HttpPMTilesSource("/api/small").getBytes(0, 16384);
  assert.equal(result.data.byteLength, 4);
  assert.deepEqual(ranges, ["bytes=0-16383", "bytes=0-3"]);
});

test("malformed 416 cannot expand a read beyond the requested range", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () =>
    new Response(null, { status: 416, headers: { "Content-Range": "bytes */999999999" } }));
  await assert.rejects(new HttpPMTilesSource("/api/bad-416").getBytes(0, 16384), /Invalid PMTiles/);
  assert.equal(fetch.mock.callCount(), 1);
});

test("test_short_archive_retry_validates_the_reduced_range_not_the_original", async (t) => {
  let count = 0;
  t.mock.method(globalThis, "fetch", async () => ++count === 1
    ? new Response(null, { status: 416, headers: { "Content-Range": "bytes */4" } })
    : new Response(new Uint8Array(16384), { status: 206, headers: { "Content-Range": "bytes 0-16383/70000" } }));
  await assert.rejects(new HttpPMTilesSource("/api/invalid-retry").getBytes(0, 16384), /Content-Range/);
  assert.equal(count, 2);
});

test("invalid and excessive range sizes fail before fetching", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () => { throw new Error("must not fetch"); });
  for (const [offset, length] of [[-1, 1], [0, 0], [0, 1.5], [0, MAX_PMTILES_RANGE_BYTES + 1], [Number.MAX_SAFE_INTEGER, 2]]) {
    await assert.rejects(new HttpPMTilesSource("/api/invalid").getBytes(offset, length), /Invalid or oversized/);
  }
  assert.equal(fetch.mock.callCount(), 0);
});

test("206 response ranges and byte counts must match the bounded request", async (t) => {
  for (const [range, bytes, message] of [
    [null, 4, /Content-Range/],
    ["bytes 1-4/70000", 4, /Content-Range/],
    ["bytes 0-9/70000", 10, /Content-Range/],
    ["bytes 0-3/70000", 3, /Incomplete/],
    ["bytes 0-3/70000", 5, /download limit/],
  ]) {
    const fetch = t.mock.method(globalThis, "fetch", async () => new Response(new Uint8Array(bytes), {
      status: 206, headers: range ? { "Content-Range": range } : {},
    }));
    await assert.rejects(new HttpPMTilesSource("/api/bad-range").getBytes(0, 4), message);
    assert.equal(fetch.mock.callCount(), 1);
    fetch.mock.restore();
  }
});

test("Visualizer uses the same layer archive as labeling without refetching its header", async (t) => {
  const requests = serveRanges(t);
  const archiveUrl = "/api/GetModelArtifact?projectId=p&modelId=labeler&imageLayerId=shared&kind=footprint_pmtiles";
  const labeler = await loadFootprintArchive(archiveUrl);
  const attrs = {
    schemaVersion: 1, predictionRevision: "revision", flavor: "embedding", n: 1,
    ids: [0], overtureIds: ["a"], damage: [1], unknown: [0], damaged: [1], classes: ["Damaged"],
  };
  const results = {
    flavor: "embedding", supportsThreshold: false, predictionRevision: "revision", buildingCount: 1,
    footprintTilesUrl: "GetModelArtifact?kind=footprint_pmtiles&imageLayerId=shared&modelId=viewer&projectId=p",
    predictionAttrsUrl: "GetModelArtifact?kind=prediction_attrs&modelId=viewer&predictionRevision=revision",
  };
  const rangesFetch = globalThis.fetch;
  const attributeRequests = [];
  t.mock.method(globalThis, "fetch", (url, options) => {
    if (url.includes("kind=prediction_attrs")) {
      attributeRequests.push(url);
      return Promise.resolve(Response.json(attrs));
    }
    return rangesFetch(url, options);
  });
  const viewer = await loadPredictionArtifacts(results, (url) => `/api/${url}`);
  assert.equal(viewer.archiveKey, labeler.archiveKey);
  assert.equal(viewer.attrs.n, 1);
  assert.equal(attributeRequests.length, 1);
  assert.deepEqual(viewer.bounds, [0, 0, 0, 0]);
  assert.equal(requests.length, 1);
});
