import assert from "node:assert/strict";
import test from "node:test";

import { loadInteractiveArtifacts } from "./loadInteractiveArtifacts.js";


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