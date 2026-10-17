// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import test from "node:test";
import assert from "node:assert/strict";
import { modelRowStatus } from "./ModelRowHelper.js";

test("pretrained rows display every inference lifecycle state without training or logs", () => {
  for (const status of ["Queued", "InProgress", "Processed", "Failed", "Cancelled"]) {
    const presentation = modelRowStatus({
      modelType: "pretrained", inferenceStatus: status,
      status: "Queued", statusMessage: "Old training log",
      inferenceCurrentStep: 0, inferenceTotalSteps: 7, inferenceProgressPct: 0,
    });
    assert.equal(presentation.isInference, true);
    assert.equal(presentation.status, status);
    assert.equal(presentation.statusMessage, "");
    assert.equal(presentation.currentStep, undefined, "use the visible legacy status fallback without logs");
  }
});

test("pretrained progress keeps zero and normalizes absent values without fabricating training", () => {
  const run = {
    modelType: "pretrained", inferenceStatus: "InProgress",
    inferenceStatusMessage: "Queued for inference", inferenceCurrentStep: 0,
    inferenceTotalSteps: 7, inferenceProgressPct: 0,
  };
  assert.deepEqual(modelRowStatus(run), {
    isInference: true, status: "InProgress", statusMessage: "Queued for inference",
    currentStep: 0, totalSteps: 7, progressPct: 0,
  });
  const sparse = modelRowStatus({ ...run, inferenceCurrentStep: null, inferenceProgressPct: null });
  assert.equal(sparse.currentStep, undefined);
  assert.equal(sparse.progressPct, undefined);
  assert.equal(modelRowStatus({ modelType: "pretrained" }).status, "Unknown");
});

test("active training is not hidden by historical inference while completed training uses inference status", () => {
  const model = {
    modelType: "trained", status: "InProgress", statusMessage: "Training",
    currentStep: 2, totalSteps: 4, progressPct: 50,
    inferenceStatus: "Processed", inferenceStatusMessage: "Historical inference",
  };
  assert.deepEqual(modelRowStatus(model), {
    isInference: false, status: "InProgress", statusMessage: "Training",
    currentStep: 2, totalSteps: 4, progressPct: 50,
  });
  assert.equal(modelRowStatus({ ...model, status: "Trained" }).isInference, true);
  assert.equal(modelRowStatus({ status: "Trained" }).isInference, false);
});
