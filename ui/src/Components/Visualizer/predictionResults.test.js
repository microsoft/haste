// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Read-only cases adapted from PR136; obsolete backfill/editor cases excluded.
import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { normalizeAttrs, indexById, classifyAll } from "./predictionClassify.js";
import {
  buildRawGpkgUrl, buildVisualizerResultsUrl, canViewResults, DEFAULT_THRESHOLD,
  DEFAULT_UNKNOWN_THRESHOLD, describeFootprintStatus, hasRasterLayer,
  predictionRenderKey, protectedArtifactEndpoint, readinessDetail,
  resolveFootprintStatus, resolvePredictionArtifacts, visualizerLayerOptions,
} from "./predictionResults.js";
import {
  dividerPositionForKey, isMobileResultsLayout, RESULTS_DESKTOP_MIN_WIDTH, swipeLeftPaneLabel,
} from "./visualizerSwipe.js";
import { fetchArtifactBuffer, loadPredictionAttributes } from "./predictionArtifactLoader.js";
import { readResponseBuffer } from "../InteractiveLabeler/interactiveLabelerLoading.js";

function sampleAttrs(overrides = {}) {
  return {
    schemaVersion: 1, predictionRevision: "generation-1", flavor: "inference", n: 3,
    ids: [0, 1, 2], overtureIds: ["a", "b", "c"],
    damage: [0.8, 0, null], unknown: [0, 0, null], damaged: [1, 0, null],
    classes: ["Damaged", "NotDamaged", "Unknown"], ...overrides,
  };
}
function sampleResults(overrides = {}) {
  return {
    flavor: "inference", supportsThreshold: true,
    defaultThreshold: 0, defaultUnknownThreshold: 0, buildingCount: 3,
    predictionRevision: "generation-1", predictionsReady: true,
    predictionsReadiness: { reason: "ready", tilesReady: true, attrsReady: true },
    footprintTilesUrl: "GetModelArtifact?kind=footprint_pmtiles&imageLayerId=layer",
    predictionAttrsUrl: "GetModelArtifact?kind=prediction_attrs&predictionRevision=generation-1",
    ...overrides,
  };
}

test("raw sidecars carry authoritative classes, including null-score Unknown rows", () => {
  const attrs = normalizeAttrs(sampleAttrs(), sampleResults());
  assert.deepEqual(classifyAll(attrs), {
    classes: ["Damaged", "NotDamaged", "Unknown"],
    counts: { Damaged: 1, NotDamaged: 1, Unknown: 1 }, total: 3,
  });
  assert.equal(indexById(attrs).get(2), 2);
  assert.equal(attrs.damage[2], null);
  assert.equal(DEFAULT_THRESHOLD, 0);
  assert.equal(DEFAULT_UNKNOWN_THRESHOLD, 0);
});

test("binary scores do not change a standard model's flavor", () => {
  const attrs = sampleAttrs({ damage: [1, 0, null] });
  assert.equal(normalizeAttrs(attrs, sampleResults()).flavor, "inference");
  attrs.flavor = "embedding";
  assert.equal(normalizeAttrs(attrs, sampleResults({ flavor: "embedding", supportsThreshold: false })).flavor, "embedding");
});

test("empty sidecars preserve zero without inventing rows", () => {
  const attrs = sampleAttrs({
    n: 0, ids: [], overtureIds: [], damage: [], unknown: [], damaged: [], classes: [],
  });
  assert.equal(normalizeAttrs(attrs, sampleResults({ buildingCount: 0 })).n, 0);
});

test("column lengths and all required fields are strict", () => {
  for (const column of ["ids", "overtureIds", "damage", "unknown", "damaged", "classes"]) {
    assert.throws(() => normalizeAttrs(sampleAttrs({ [column]: [] })), /exactly 3 rows/);
    assert.throws(() => normalizeAttrs(sampleAttrs({ [column]: undefined })), /exactly 3 rows/);
  }
  for (const n of [-1, 1.5, "3", NaN]) {
    assert.throws(() => normalizeAttrs(sampleAttrs({ n })), /invalid row count/);
  }
  assert.throws(() => normalizeAttrs(sampleAttrs({ schemaVersion: 2 })), /schema version/);
  assert.throws(() => normalizeAttrs(sampleAttrs({ predictionRevision: "" })), /revision/);
});

test("source IDs must be unique and contiguous; alignment does not depend on array order", () => {
  for (const ids of [[0, 0, 2], [0, 2, 3], [1, 2, 3], [0, 1, "2"], [0, -1, 2]]) {
    assert.throws(() => normalizeAttrs(sampleAttrs({ ids })), /unique and contiguous/);
  }
  const attrs = normalizeAttrs(sampleAttrs({ ids: [2, 0, 1] }));
  assert.equal(indexById(attrs).get(2), 0);
  assert.throws(() => normalizeAttrs(sampleAttrs({ overtureIds: ["a", null, "c"] })), /Overture identity/);
});

test("invalid classes/scores are not coerced to NotDamaged", () => {
  for (const value of [-1, 2, undefined, NaN, Infinity, "0.4"]) {
    assert.throws(() => normalizeAttrs(sampleAttrs({ damage: [value, 0, null] })), /invalid score/);
  }
  assert.throws(() => normalizeAttrs(sampleAttrs({ classes: ["damaged", "NotDamaged", "Unknown"] })), /invalid class/);
  assert.throws(() => normalizeAttrs(sampleAttrs({ classes: ["Damaged", "NotDamaged", "NotDamaged"] })), /unscored row/);
  assert.throws(() => normalizeAttrs(sampleAttrs({ damaged: [true, 0, null] })), /damaged flag/);
});

test("metadata/sidecar revision, flavor and count must match", () => {
  for (const change of [
    { predictionRevision: "older" }, { flavor: "embedding" }, { buildingCount: 2 },
  ]) {
    assert.throws(() => normalizeAttrs(sampleAttrs(), sampleResults(change)), /differ/);
  }
});

test("server readiness gates both workflows, independently from a downloadable raw file", () => {
  assert.equal(canViewResults({ gpkgUrl: "legacy.gpkg" }), false);
  assert.equal(canViewResults({ predictionsReady: false, gpkgUrl: "empty.gpkg", buildingCount: 0 }), false);
  assert.equal(canViewResults({ predictionsReady: true, buildingCount: 0 }), false);
  for (const flavor of ["inference", "embedding"]) {
    assert.equal(canViewResults(sampleResults({ flavor })), true);
  }
});

test("missing, invalid and empty results cannot retain a ready footprint status", () => {
  assert.equal(resolveFootprintStatus({ results: null }), "loading");
  assert.equal(resolveFootprintStatus({ results: sampleResults(), loaded: true, layersReady: false }), "loading");
  assert.equal(resolveFootprintStatus({ results: sampleResults(), loaded: true, layersReady: true }), "ready");
  assert.equal(resolveFootprintStatus({
    results: sampleResults({ buildingCount: 0 }), loaded: true, layersReady: true,
  }), "empty");
  assert.equal(resolveFootprintStatus({
    results: sampleResults({ predictionsReady: false }), loaded: true, layersReady: true,
  }), "unavailable");
  assert.equal(resolveFootprintStatus({ results: sampleResults(), error: "renderer failed" }), "unavailable");
  for (const status of ["loading", "empty", "unavailable"]) {
    assert.ok(describeFootprintStatus(status, "Explanation").title);
  }
  assert.equal(describeFootprintStatus("ready"), null);
});

test("legacy guidance requires an explicit rerun; tile guidance does not start work", () => {
  assert.match(readinessDetail({ predictionsReadiness: { attrsReady: false } }), /Rerun inference/);
  assert.match(readinessDetail({ predictionsReadiness: { tilesReady: false } }), /Retry after layer processing/);
  assert.match(readinessDetail({ buildingCount: 0 }), /No predicted buildings/);
  assert.equal(readinessDetail({ predictionsReadiness: { detail: "Backend explanation" } }), "Backend explanation");
});

test("generation, artifact URLs, count and clear state all invalidate render identity", () => {
  const initial = sampleResults();
  const key = predictionRenderKey(initial);
  assert.equal(key, predictionRenderKey({ ...initial }));
  for (const change of [
    { predictionRevision: "generation-2" }, { predictionAttrsUrl: "new" },
    { footprintTilesUrl: "new" }, { buildingCount: 0 }, { predictionsReady: false },
    { predictionsReadiness: { reason: "missing_attrs", attrsReady: false } },
  ]) {
    assert.notEqual(predictionRenderKey({ ...initial, ...change }), key);
  }
});

test("raw downloads are explicitly pinned to version zero and preserve all identifiers", () => {
  const ids = { projectId: "project&a", imageLayerId: "layer", modelId: "model" };
  const endpoint = buildRawGpkgUrl(ids);
  assert.ok(endpoint.startsWith("GetModelArtifact?"));
  const params = new URL(endpoint, "https://haste.invalid").searchParams;
  assert.equal(params.get("kind"), "gpkg");
  assert.equal(params.get("version"), "0");
  for (const [key, value] of Object.entries(ids)) assert.equal(params.get(key), value);
  assert.ok(buildVisualizerResultsUrl(ids).startsWith("GetVisualizerResults?"));
});

test("artifact endpoints preserve backend revision pinning and reject direct storage fallback", () => {
  const results = sampleResults();
  assert.equal(resolvePredictionArtifacts(results).predictionAttrsUrl, results.predictionAttrsUrl);
  assert.equal(protectedArtifactEndpoint("/api/GetModelArtifact?kind=gpkg", "gpkg"), "GetModelArtifact?kind=gpkg");
  for (const url of ["", null, "https://storage.invalid/a.json", "//host/GetModelArtifact?kind=prediction_attrs", "GetModelArtifact?kind=gpkg"]) {
    assert.throws(() => protectedArtifactEndpoint(url, "prediction_attrs"), /protected/);
  }
});

test("raster availability does not invent layers for embedding models", () => {
  for (const layer of [null, {}, { url: "" }, { url: "/tiles?url=&x={x}" }]) {
    assert.equal(hasRasterLayer(layer), false);
  }
  assert.equal(hasRasterLayer({ url: "/tiles/{z}/{x}/{y}" }), true);
  assert.deepEqual(visualizerLayerOptions({ results: sampleResults(), footprintStatus: "ready" }),
    [{ key: "footprints", label: "Predicted building footprints", disabled: false }]);
  const options = visualizerLayerOptions({
    results: sampleResults({ predictedDamageLayer: { url: "/damage" }, predictionsLayer: { url: "/scores" } }),
    footprintStatus: "loading",
  });
  assert.deepEqual(options.map((option) => option.key), ["predictedDamageLayer", "predictionsLayer", "footprints"]);
  assert.equal(options[2].disabled, true);
});

test("A/S/D and labels preserve PR136's swipe orientation and null imagery support", () => {
  assert.equal(dividerPositionForKey("A", 800), 0);
  assert.equal(dividerPositionForKey("s", 800), 400);
  assert.equal(dividerPositionForKey("d", 800), 800);
  assert.equal(dividerPositionForKey("e", 800), null);
  assert.equal(dividerPositionForKey("s", 0), null);
  assert.equal(swipeLeftPaneLabel({ preDisasterImagery: null }), "Basemap");
});

test("comparison controls share the 992px boundary without a 992–1199px gap", () => {
  assert.equal(RESULTS_DESKTOP_MIN_WIDTH, 992);
  for (const width of [390, 991, 992, 1100, 1199, 1200, 1440]) {
    // Mobile uses the same exported width in its media query; desktop uses
    // this executable predicate for divider/zoom and keyboard behavior.
    const mobileSwitchVisible = width < RESULTS_DESKTOP_MIN_WIDTH;
    const dividerVisible = !isMobileResultsLayout(width);
    assert.equal(Number(mobileSwitchVisible) + Number(dividerVisible), 1, `width ${width}`);
    assert.equal(dividerVisible, width >= 992);
  }
});

test("protected attribute loading is GET-only and validates the response revision", async (t) => {
  const requests = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    requests.push({ url, options });
    return Response.json(sampleAttrs());
  });
  const result = await loadPredictionAttributes(sampleResults(), (endpoint) => `/api/${endpoint}`);
  assert.equal(result.attrs.n, 3);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].options.method, undefined);
  assert.equal(requests[0].options.cache, "no-store");
  assert.match(requests[0].url, /predictionRevision=generation-1/);
  await assert.rejects(
    loadPredictionAttributes(sampleResults({ predictionRevision: "generation-2" }), (url) => url),
    /revisions differ/,
  );
});

test("attribute 404 is actionable and does not issue another request", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () => new Response("", { status: 404 }));
  await assert.rejects(loadPredictionAttributes(sampleResults(), (url) => url), /Rerun inference/);
  assert.equal(fetch.mock.callCount(), 1);
});

test("artifact cancellation retains AbortError and prevents a fetch when already aborted", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () => Response.json(sampleAttrs()));
  const controller = new AbortController();
  const reason = new DOMException("User left results", "AbortError");
  controller.abort(reason);
  await assert.rejects(fetchArtifactBuffer("/api/artifact", { signal: controller.signal }), (error) => error === reason);
  assert.equal(fetch.mock.callCount(), 0);
});

test("bounded readers cancel oversized streams and enforce the cap without a stream", async () => {
  let cancelled = false;
  const body = new ReadableStream({
    start(controller) { controller.enqueue(new Uint8Array(8)); },
    cancel() { cancelled = true; },
  });
  await assert.rejects(readResponseBuffer(new Response(body), undefined, { maxBytes: 4 }), /download limit/);
  assert.equal(cancelled, true);
  await assert.rejects(readResponseBuffer({
    arrayBuffer: async () => new ArrayBuffer(8),
  }, undefined, { maxBytes: 4 }), /download limit/);
});

test("cancelling a pending stream read cannot return partial attributes", async () => {
  const controller = new AbortController();
  const response = new Response(new ReadableStream({}));
  const read = readResponseBuffer(response, undefined, { signal: controller.signal });
  controller.abort();
  await assert.rejects(read, { name: "AbortError" });
});

test("read-only modules do not import editor or preparation machinery", async () => {
  for (const file of [
    "Visualizer.jsx", "usePredictionArtifacts.js", "usePredictionFootprints.js",
    "useVisualizerResults.js", "predictionArtifactLoader.js", "PredictionStatusNote.jsx",
  ]) {
    const source = await readFile(new URL(file, import.meta.url), "utf8");
    assert.doesNotMatch(source, /predictionPrep|PutPreparePrediction|GetPredictionEditSession|apiPut|PredictionEditPanel|PredictionVersionControls|setInterval/);
  }
  const source = await readFile(new URL("Labels.jsx", import.meta.url), "utf8");
  assert.doesNotMatch(source, /visualizerEditButton/);
  for (const file of ["ModelResultsButton.jsx", "EmbeddingModelRow.jsx"]) {
    const row = await readFile(new URL(`../ProjectManagement/${file}`, import.meta.url), "utf8");
    assert.match(row, /buildRawGpkgUrl/);
    assert.doesNotMatch(row, /handleDownload\(model\.gpkgUrl\)/);
  }
});
