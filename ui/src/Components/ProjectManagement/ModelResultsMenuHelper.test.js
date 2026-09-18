// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { modelResultsItems } from "./ModelResultsMenuHelper.js";

const ready = {
  status: "Processed", inferenceStatus: "Processed", gpkgUrl: "/api/raw",
  rawPredictionsReady: true, predictionsReady: true, buildingCount: 3,
};
function menu(workflow, model = ready, options = {}) {
  return modelResultsItems({
    workflow, model, validationLabelCount: 1, publishingEnabled: true, ...options,
  });
}
const item = (items, key) => items.find((entry) => entry.key === key);

for (const workflow of ["inference", "embedding"]) {
  test(`test_ready_${workflow}_enables_all_common_actions`, () => {
    assert.equal(menu(workflow).length, 5);
    assert.ok(menu(workflow).every((entry) => !entry.disabled));
  });

  test(`test_raw_only_legacy_${workflow}_preserves_download_and_reports`, () => {
    const items = menu(workflow, {
      status: "Processed", inferenceStatus: "Processed", gpkgUrl: "legacy.gpkg",
    });
    assert.equal(item(items, "viewResults").disabled, true);
    assert.match(item(items, "viewResults").tooltip, /Rerun inference/);
    for (const key of ["downloadGeopackage", "validationReport", "assessmentReport", "publishDataset"]) {
      assert.equal(item(items, key).disabled, false, key);
    }
  });

  test(`test_missing_vectors_${workflow}_does_not_disable_raw_actions`, () => {
    for (const readiness of [{ tilesReady: false }, { attrsReady: false }]) {
      const items = menu(workflow, { ...ready, predictionsReady: false, predictionsReadiness: readiness });
      assert.equal(item(items, "viewResults").disabled, true);
      assert.ok(item(items, "viewResults").tooltip);
      assert.equal(item(items, "downloadGeopackage").disabled, false);
      assert.equal(item(items, "assessmentReport").disabled, false);
    }
  });

  test(`test_raw_readiness_${workflow}_is_independent_of_view_readiness`, () => {
    const items = menu(workflow, { ...ready, rawPredictionsReady: false });
    assert.equal(item(items, "downloadGeopackage").disabled, true);
    assert.equal(item(items, "viewResults").disabled, false);
    assert.equal(item(items, "publishDataset").disabled, true);
  });

  test(`test_labels_and_publish_completion_guards_${workflow}_are_preserved`, () => {
    const noLabels = menu(workflow, ready, { validationLabelCount: 0 });
    assert.equal(item(noLabels, "validationReport").disabled, true);
    assert.equal(item(noLabels, "assessmentReport").disabled, false);
    assert.equal(item(menu(workflow, ready, { publishingEnabled: false }), "publishDataset"), undefined);
    const pending = menu(workflow, { ...ready, status: "Running", inferenceStatus: "Running" });
    assert.equal(item(pending, "publishDataset").disabled, true);
    assert.equal(item(menu(workflow, { ...ready, gpkgUrl: null }), "publishDataset").disabled, true);
    assert.equal(item(pending, "downloadGeopackage").disabled, false);
    assert.equal(item(pending, "assessmentReport").disabled, workflow === "inference");
  });

  test(`test_download_in_flight_${workflow}_only_disables_download`, () => {
    const items = menu(workflow, ready, { downloading: true });
    assert.deepEqual(items.filter((entry) => entry.disabled).map((entry) => entry.key), ["downloadGeopackage"]);
  });

  test(`test_actions_${workflow}_navigate_download_and_select_the_correct_modal`, async () => {
    const calls = [];
    const items = menu(workflow, ready, {
      onView: () => calls.push("view"),
      onDownload: async () => calls.push("download"),
      openModal: (modal) => calls.push(modal),
    });
    for (const entry of items) await entry.onClick();
    assert.deepEqual(calls, ["view", "download", "validation", "assessment", "publish"]);
  });
}

test("test_clear_embedding_disables_all_results_even_with_stale_urls", () => {
  for (const rawPredictionsReady of [false, undefined]) {
    const items = menu("embedding", {
      ...ready, rawPredictionsReady, predictionsReady: false, buildingCount: 0,
    });
    assert.ok(items.every((entry) => entry.disabled));
    assert.match(item(items, "viewResults").tooltip, /No predicted buildings/);
  }
});

test("test_standard_partial_assessment_preserves_status_based_reporting", () => {
  const items = menu("inference", { inferenceStatus: "Processed", rawPredictionsReady: false });
  assert.equal(item(items, "viewResults").disabled, true);
  assert.equal(item(items, "downloadGeopackage").disabled, true);
  assert.equal(item(items, "assessmentReport").disabled, false);
  assert.equal(item(items, "publishDataset").disabled, true);
});

test("test_standard_artifacts_remain_available_without_predictions", () => {
  const artifact = { key: "downloadTrainingArtifacts", disabled: false, onClick() {} };
  const items = menu("inference", {}, { artifactItems: [artifact] });
  assert.equal(items[2], artifact);
  assert.equal(items.every((entry) => entry.disabled), false);
  assert.equal(menu("embedding").some((entry) => entry.key === artifact.key), false);
});

test("test_rows_delegate_modals_and_preserve_layout_hooks", async () => {
  const read = (name) => readFile(new URL(name, import.meta.url), "utf8");
  const shared = await read("ModelResultsMenu.jsx");
  assert.match(shared, /modal === "validation"/);
  assert.match(shared, /modal === "assessment"/);
  assert.match(shared, /modal === "publish"/);
  assert.match(shared, /onDismiss=\{dismiss\}/);
  assert.match(shared, /if \(outcome\.error\) setDialog\("Download failed", outcome\.error\)/);
  assert.match(shared, /navigate\("\/published-datasets"\)/);
  const standard = await read("ModelResultsButton.jsx");
  const embedding = await read("EmbeddingModelRow.jsx");
  for (const row of [standard, embedding]) {
    assert.match(row, /ModelResultsMenu/);
    assert.doesNotMatch(row, /ValidationReportModal|AssessmentReportModal|PublishDatasetModal/);
  }
  assert.match(standard, /ModelResultsStatusIndicator/);
  assert.match(standard, /trainingZipUrl/);
  assert.match(standard, /inferenceZipUrl/);
  assert.match(standard, /singleModelResults/);
  assert.match(embedding, /embeddingResults/);
  assert.match(embedding, /mobile \? "dashboard-button ms-2" : "dashboard-button"/);
});
