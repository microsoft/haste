// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { requestPredictionJson } from "./predictionHttp.js";
import { buildVersionGpkgUrl, validateSelectedSource, validateVersionManifest, versionEndpoint } from "./predictionVersions.js";
import { downloadPrediction } from "./predictionDownload.js";
import { buildRawGpkgUrl, buildVisualizerResultsUrl } from "./predictionResults.js";
import { createModelResultsDownload } from "../ProjectManagement/ModelResultsDownloadHelper.js";

test("both rows delegate fresh discovery to the shared Results menu", async () => {
  for (const file of ["EmbeddingModelRow.jsx", "ModelResultsButton.jsx"]) {
    const source = await readFile(new URL(`../ProjectManagement/${file}`, import.meta.url), "utf8");
    assert.match(source, /ModelResultsMenu/);
    assert.doesNotMatch(source, /DownloadPredictionsDialog|fileDownload\(buildUrl/);
  }
  const shared = await readFile(new URL("../ProjectManagement/ModelResultsMenu.jsx", import.meta.url), "utf8");
  assert.match(shared, /createModelResultsDownload/);
  assert.match(shared, /downloadOperation\.run\(buildUrl\(buildVisualizerResultsUrl\(ids\)\)\)/);
  assert.match(shared, /downloadOperation\.cancel\(\)/);
});

for (const serverVersion of [0, 2]) {
  test(`test_fresh_version_${serverVersion}_uses_raw_download_or_version_dialog_without_trusting_cached_rows`, async () => {
    const ids = { projectId: "project", imageLayerId: "layer", modelId: "1001" };
    const rawUrl = `/api/${buildRawGpkgUrl(ids)}`;
    const resultsUrl = `/api/${buildVisualizerResultsUrl(ids)}`;
    const requests = [];
    const actions = [];
    const operation = createModelResultsDownload({
      rawUrl, onChange() {},
      onChooseVersion: () => actions.push("dialog"),
      fetchResponse: async (url, options) => {
        requests.push(url);
        assert.equal(options.method, "GET");
        return Response.json({
          predictionVersion: serverVersion, predictionRevision: "current",
          predictionVersions: serverVersion
            ? [{ version: serverVersion, gpkgUrl: "/api/edited", predictionRevision: "current" }] : [],
        });
      },
      download: async (url, version, { signal }) => {
        assert.equal(url, rawUrl);
        assert.equal(version, 0);
        assert.equal(signal.aborted, false);
        actions.push("raw");
      },
    });
    assert.deepEqual(await operation.run(resultsUrl), { ok: true });
    assert.deepEqual(requests, [resultsUrl]);
    assert.deepEqual(actions, [serverVersion ? "dialog" : "raw"]);
  });
}

test("test_discovery_failure_does_not_silently_download_raw", async () => {
  let acted = false;
  const operation = createModelResultsDownload({
    rawUrl: "/api/raw", onChange() {},
    onChooseVersion: () => { acted = true; },
    download: async () => { acted = true; },
    fetchResponse: async () => Response.json({ error: "Discovery failed" }, { status: 500 }),
  });
  assert.deepEqual(await operation.run("/api/results"), { error: "Discovery failed" });
  assert.equal(acted, false);
});

test("test_unmount_cancellation_and_duplicate_clicks_cover_discovery_too", async () => {
  let acted = false;
  let calls = 0;
  const operation = createModelResultsDownload({
    rawUrl: "/api/raw", onChange() {},
    onChooseVersion: () => { acted = true; },
    download: async () => { acted = true; },
    fetchResponse: async (_url, { signal }) => {
      calls++;
      return new Promise((_resolve, reject) => {
        signal.addEventListener("abort", () => reject(signal.reason), { once: true });
      });
    },
  });
  const first = operation.run("/api/results");
  assert.equal(operation.run("/api/results"), first);
  await Promise.resolve();
  operation.cancel();
  assert.deepEqual(await first, { cancelled: true });
  assert.equal(calls, 1);
  assert.equal(acted, false);
});

for (const serverVersion of [0, 1]) {
  test(`fresh discovery from a cached no-edits row downloads server version ${serverVersion} without extra query fields`, async (t) => {
    t.mock.timers.enable({ apis: ["setTimeout"] });
    // This row can have been loaded before another analyst saved version 1.
    const cachedRow = { hasEdits: false, editedPredictions: [] };
    const ids = { projectId: "project", imageLayerId: "layer", modelId: "1001" };
    const versions = serverVersion ? [{
      version: 1, predictionRevision: "generation", gpkgUrl: "protected-pointer", predictionAttrsUrl: "protected-attributes",
    }] : [];
    const requests = [];
    const fetchResponse = async (url) => {
      const parsed = new URL(url, "https://haste.invalid");
      requests.push(parsed);
      assert.equal(parsed.searchParams.has("_"), false);
      if (parsed.pathname.endsWith("GetEditedPredictionVersions")) return Response.json({ versions });
      if (parsed.pathname.endsWith("GetVisualizerResults")) {
        assert.equal(parsed.searchParams.has("version"), false);
        return Response.json({ predictionVersion: serverVersion, predictionRevision: "generation", predictionVersions: versions });
      }
      assert.equal(parsed.pathname, "/api/GetModelArtifact");
      assert.equal(parsed.searchParams.get("version"), String(serverVersion));
      assert.deepEqual([...parsed.searchParams.keys()].sort(), ["imageLayerId", "kind", "modelId", "predictionRevision", "projectId", "version"]);
      return new Response("gpkg", {
        headers: { "content-disposition": `attachment; filename=predictions_${serverVersion ? "v1" : "raw"}.gpkg` },
      });
    };
    // These are the fresh reads and protected downloader used by the dialog;
    // the stale row is never used to decide a version or skip discovery.
    const manifest = await requestPredictionJson(`/api/${versionEndpoint("GetEditedPredictionVersions", ids)}`, { fetchResponse });
    validateVersionManifest(manifest.versions);
    const selected = validateSelectedSource(await requestPredictionJson(
      `/api/${versionEndpoint("GetVisualizerResults", ids)}`, { fetchResponse },
    ));
    let filename;
    const link = { click() { filename = this.download; }, remove() {} };
    await downloadPrediction(`/api/${buildVersionGpkgUrl({
      ...ids, version: selected.predictionVersion, predictionRevision: selected.predictionRevision,
    })}`, selected.predictionVersion, {
      fetchResponse,
      documentObject: { createElement: () => link, body: { appendChild() {} } },
      urls: { createObjectURL: () => "blob:fixture", revokeObjectURL() {} },
    });
    assert.equal(filename, serverVersion ? "predictions_v1.gpkg" : "predictions_raw.gpkg");
    assert.equal(requests.length, 3);
    assert.deepEqual(cachedRow, { hasEdits: false, editedPredictions: [] });
    t.mock.timers.tick(1000);
  });
}
