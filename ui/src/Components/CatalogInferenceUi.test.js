// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Source wiring guards complement the request/readiness behavior tests without
// starting a browser or a live authenticated application.
import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const read = (file) => readFile(new URL(file, import.meta.url), "utf8");

test("catalog inference uses a centered dialog with automatic loading, explicit empty/error states, and failure-only Retry", async () => {
  const modal = await read("CatalogInferenceModal.jsx");
  assert.match(modal, /<DialogSurface className=\{styles.surface\}/);
  assert.doesNotMatch(modal, /Drawer|Panel|Reload|reload/i);
  assert.match(modal, /catalog.status === "error"[\s\S]*?onClick=\{retryCatalog\}/);
  assert.match(modal, /No inference models are in the catalog yet/);
  assert.match(modal, /No catalog models are compatible with this layer/);
  assert.match(modal, /Loading inference catalog/);
  assert.match(modal, /return \(\) => controller.abort\(\)/);
  assert.match(modal, /signal: controller.signal/);
  assert.match(modal, /if \(!controller.signal.aborted\) setCatalog/);
});

test("catalog acceptance retries refresh rather than submitting another run and blocks duplicate/closing actions", async () => {
  const modal = await read("CatalogInferenceModal.jsx");
  assert.match(modal, /if \(busyRef.current \|\| \(!accepted && !canSubmit\)\) return/);
  assert.match(modal, /if \(!run\) \{[\s\S]*?submission.submit/);
  assert.match(modal, /await refreshModels\(\)/);
  assert.match(modal, /accepted \? "Retry refresh"/);
  assert.match(modal, /if \(!busyRef.current\) onClose\(\)/);
  assert.doesNotMatch(modal, /dinov\d|checkpointUrl|https:\/\/.*blob/);
});

test("both layer layouts forward forced catalog refresh and reveal independent model rows only on success", async () => {
  for (const [file, setter] of [["LayerRow.jsx", "setIsExpanded"], ["LayerCard.jsx", "setModelsOpen"]]) {
    const source = await read(`ProjectManagement/${file}`);
    assert.match(source, /<CatalogInferenceButton/);
    assert.match(source, /fetchProjectDetails=\{async \(showLoading, forceRefresh\)/);
    assert.match(source, /await fetchProjectDetails\(showLoading, forceRefresh\)/);
    assert.match(source, new RegExp(`if \\(refreshed !== false && refreshed !== null\\) ${setter}\\(true\\)`));
  }
});

test("model rows keep embeddings separate, suppress pretrained training controls, and share the Results menu", async () => {
  const row = await read("ProjectManagement/ModelRow.jsx");
  const results = await read("ProjectManagement/ModelResultsButton.jsx");
  assert.match(row, /model.modelType === "embedding"[\s\S]*?<EmbeddingModelRow/);
  assert.match(row, /const inferenceOnly = isInferenceOnlyModel\(model\)/);
  assert.match(row, /!inferenceOnly && model.trainDate/);
  assert.match(row, /!inferenceOnly && model.labelsCount/);
  assert.match(row, /!isInferenceOnlyModel\(model\) \|\| action.key === "remove"/);
  assert.match(row, /modelRowStatus\(model\)/);
  assert.match(results, /<ModelResultsMenu/);
  assert.match(results, /!isInferenceOnlyModel\(model\) \|\| action.key !== "downloadTrainingArtifacts"/);
  assert.doesNotMatch(results, /inferenceJobs|model.status|ValidationReportModal|AssessmentReportModal/);
});

test("cancellation detects failed modern project refreshes and preserves synchronous duplicate protection", async () => {
  const cancel = await read("OtherComponents/ModelCancelButton.jsx");
  assert.match(cancel, /getModelCancellationLabel\(model\)/);
  assert.match(cancel, /if \(cancellingRef.current \|\| !cancelLabel\) return/);
  assert.match(cancel, /response === 409/);
  assert.match(cancel, /refreshed === false \|\| refreshed === null/);
  assert.match(cancel, /finally \{[\s\S]*?cancellingRef.current = false/);
});

test("pretrained results retain the common renderer, map readiness, editor, and exact-version report loader", async () => {
  const visualizer = await read("Visualizer/Visualizer.jsx");
  const report = await read("BuildingValidation/AssessmentReportModal.jsx");
  const loader = await read("BuildingValidation/usePredictionReport.js");
  assert.match(visualizer, /useVisualizerResults\(ids\)/);
  assert.match(visualizer, /usePredictionFootprints\(/);
  assert.match(visualizer, /usePredictionEditor\(/);
  assert.match(visualizer, /const mapsReady = scene.maps\?\.length === 2/);
  assert.doesNotMatch(visualizer, /VisualizerHelper|modelType.*pretrained|globalVisualizerResults/);
  assert.match(report, /usePredictionReport\("GetAssessmentReport"/);
  assert.match(report, /<PredictionVersionPicker/);
  assert.match(report, /label="No observation \(subset of Unknown\)"/);
  assert.doesNotMatch(report, /label="No observation \(excluded\)"/);
  assert.match(loader, /validateSelectedSource\(report, selectedVersion\)/);
  assert.match(loader, /versionEndpoint\(action, ids, selectedVersion\)/);
});
