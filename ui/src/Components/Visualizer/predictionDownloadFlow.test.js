// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { requestPredictionJson } from "./predictionHttp.js";
import { buildVersionGpkgUrl, validateSelectedSource, validateVersionManifest, versionEndpoint } from "./predictionVersions.js";
import { downloadPrediction } from "./predictionDownload.js";
import { modelResultsItems } from "../ProjectManagement/ModelResultsMenuHelper.js";

test("both rows open the existing download dialog through the shared menu with no preflight", async () => {
  for (const file of ["EmbeddingModelRow.jsx", "ModelResultsButton.jsx"]) {
    const source = await readFile(new URL(`../ProjectManagement/${file}`, import.meta.url), "utf8");
    assert.match(source, /ModelResultsMenu/);
    assert.doesNotMatch(source, /DownloadPredictionsDialog|fileDownload\(buildUrl/);
  }
  const shared = await readFile(new URL("../ProjectManagement/ModelResultsMenu.jsx", import.meta.url), "utf8");
  assert.match(shared, /onDownload: \(\) => setModal\("download"\)/);
  assert.match(shared, /modal === "download"/);
  assert.match(shared, /<DownloadPredictionsDialog/);
  assert.doesNotMatch(shared, /buildVisualizerResultsUrl|buildRawGpkgUrl|requestPredictionJson|downloadOperation|ModelResultsDownloadHelper|useRawPredictionDownload/);
  const dialog = await readFile(new URL("../OtherComponents/DownloadPredictionsDialog.jsx", import.meta.url), "utf8");
  assert.equal((dialog.match(/usePredictionVersionManifest\(ids\)/g) || []).length, 1);
  assert.equal((dialog.match(/useVisualizerResults\(ids\)/g) || []).length, 1);
  assert.match(dialog, /buildVersionGpkgUrl/);
  assert.match(dialog, /predictionRevision: version === 0 \? defaults\.results\?\.predictionRevision/);
  assert.match(dialog, /controllerRef\.current\?\.abort\(\)/);
});

for (const workflow of ["inference", "embedding"]) {
  test(`test_${workflow}_raw_and_saved_actions_only_open_the_dialog`, async (t) => {
    const fetch = t.mock.method(globalThis, "fetch", async () => { throw new Error("Unexpected preflight"); });
    const opened = [];
    for (const hasEditedPredictions of [false, true]) {
      const items = modelResultsItems({
        workflow,
        model: { rawPredictionsReady: !hasEditedPredictions, hasEditedPredictions },
        onDownload: () => opened.push("download"),
      });
      const action = items.find((entry) => entry.key === "downloadGeopackage");
      assert.equal(action.disabled, false);
      await action.onClick();
    }
    assert.deepEqual(opened, ["download", "download"]);
    assert.equal(fetch.mock.callCount(), 0);
  });
}

test("test_version_dialog_remains_the_only_discovery_owner", async () => {
  await assert.rejects(
    readFile(new URL("../ProjectManagement/ModelResultsDownloadHelper.js", import.meta.url), "utf8"),
    { code: "ENOENT" },
  );
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
      assert.equal(parsed.searchParams.get("predictionRevision"), "generation");
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
    assert.equal(requests.filter((url) => url.pathname.endsWith("GetVisualizerResults")).length, 1);
    assert.equal(requests.filter((url) => url.pathname.endsWith("GetEditedPredictionVersions")).length, 1);
    assert.deepEqual(cachedRow, { hasEdits: false, editedPredictions: [] });
    t.mock.timers.tick(1000);
  });
}
