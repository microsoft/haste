import assert from "node:assert/strict";
import test from "node:test";

import { loadInteractiveArtifacts } from "./loadInteractiveArtifacts.js";
import { HttpPMTilesSource } from "../../util/pmtiles.js";
import { readResponseBuffer } from "./interactiveLabelerLoading.js";


function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

test("starts PMTiles and sidecar loads concurrently", async () => {
  const pmtiles = deferred();
  const sidecar = deferred();
  const calls = [];
  const loading = loadInteractiveArtifacts({
    loadPmtiles: () => {
      calls.push("pmtiles");
      return pmtiles.promise;
    },
    loadSidecar: () => {
      calls.push("sidecar");
      return sidecar.promise;
    },
  });

  assert.deepEqual(calls, ["pmtiles", "sidecar"]);
  sidecar.resolve({ matrix: [] });
  pmtiles.resolve({ centerLon: 0 });

  assert.deepEqual(await loading, {
    pmtilesHeader: { centerLon: 0 },
    sidecar: { matrix: [] },
  });
});

test("rejects when the required PMTiles archive fails", async () => {
  await assert.rejects(
    loadInteractiveArtifacts({
      loadPmtiles: async () => {
        throw new Error("tiles unavailable");
      },
      loadSidecar: async () => ({ matrix: [] }),
    }),
    /tiles unavailable/
  );
});

test("rejects when the required sidecar fails", async () => {
  await assert.rejects(
    loadInteractiveArtifacts({
      loadPmtiles: async () => null,
      loadSidecar: async () => {
        throw new Error("features unavailable");
      },
    }),
    /features unavailable/
  );
});

test("aborts the sibling transfer when a required artifact fails", async () => {
  let sidecarAborted = false;

  await assert.rejects(
    loadInteractiveArtifacts({
      loadPmtiles: async () => {
        throw new Error("tiles unavailable");
      },
      loadSidecar: (signal) =>
        new Promise((resolve, reject) => {
          signal.addEventListener(
            "abort",
            () => {
              sidecarAborted = true;
              reject(new DOMException("Aborted", "AbortError"));
            },
            { once: true }
          );
        }),
    }),
    /tiles unavailable/
  );

  assert.equal(sidecarAborted, true);
});

test("waits for the aborted sibling to settle before rejecting", async () => {
  let settleSidecar;
  const events = [];
  const loading = loadInteractiveArtifacts({
    loadPmtiles: async () => {
      throw new Error("tiles unavailable");
    },
    loadSidecar: (signal) =>
      new Promise((resolve, reject) => {
        signal.addEventListener("abort", () => {
          events.push("aborted");
          settleSidecar = () => {
            events.push("settled");
            reject(new DOMException("Aborted", "AbortError"));
          };
        });
      }),
  });

  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(events, ["aborted"]);
  settleSidecar();
  await assert.rejects(loading, /tiles unavailable/);
  assert.deepEqual(events, ["aborted", "settled"]);
});

test("test_sidecar_failure_cancels_the_pending_header_range", async (t) => {
  let rangeSignal;
  t.mock.method(globalThis, "fetch", async (_url, { signal, headers }) => {
    rangeSignal = signal;
    assert.equal(headers.get("Range"), "bytes=0-16383");
    return new Promise((_resolve, reject) => {
      signal.addEventListener("abort", () => reject(signal.reason), { once: true });
    });
  });
  await assert.rejects(loadInteractiveArtifacts({
    loadPmtiles: (signal) => new HttpPMTilesSource("/api/header", { signal }).getBytes(0, 16384),
    loadSidecar: async () => { throw new Error("missing feature sidecar"); },
  }), /missing feature sidecar/);
  assert.equal(rangeSignal.aborted, true);
});

test("test_header_failure_cancels_the_full_feature_sidecar_body", async (t) => {
  let sidecarCancelled = false;
  t.mock.method(globalThis, "fetch", async () => new Response(null, { status: 404 }));
  const body = new ReadableStream({ cancel() { sidecarCancelled = true; } });
  await assert.rejects(loadInteractiveArtifacts({
    loadPmtiles: (signal) => new HttpPMTilesSource("/api/header", { signal }).getBytes(0, 16384),
    loadSidecar: (signal) => readResponseBuffer(new Response(body), undefined, { signal }),
  }), /Bad response code: 404/);
  assert.equal(sidecarCancelled, true);
});

test("test_route_cancellation_aborts_both_required_transfers", async (t) => {
  let rangeSignal;
  let sidecarCancelled = false;
  t.mock.method(globalThis, "fetch", async (_url, { signal }) => {
    rangeSignal = signal;
    return new Promise((_resolve, reject) => {
      signal.addEventListener("abort", () => reject(signal.reason), { once: true });
    });
  });
  const controller = new AbortController();
  const pending = loadInteractiveArtifacts({
    signal: controller.signal,
    loadPmtiles: (signal) => new HttpPMTilesSource("/api/header", { signal }).getBytes(0, 16384),
    loadSidecar: (signal) => readResponseBuffer(new Response(new ReadableStream({
      cancel() { sidecarCancelled = true; },
    })), undefined, { signal }),
  });
  controller.abort();
  await assert.rejects(pending, { name: "AbortError" });
  assert.equal(rangeSignal.aborted, true);
  assert.equal(sidecarCancelled, true);
});