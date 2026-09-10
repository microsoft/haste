import test from "node:test";
import assert from "node:assert/strict";

import { extractJobs } from "./ongoingJobsUtils.js";

const projectWithModel = (model) => ({
  name: "Maui",
  imageLayer: [
    {
      imageLayerId: "layer-1",
      name: "Post-event",
      status: "Processed",
      models: [model],
    },
  ],
});

test("extractJobs includes active training when historical inference is terminal", () => {
  const project = projectWithModel({
    modelId: "model-1",
    name: "Damage model",
    status: "InProgress",
    inferenceStatus: "Processed",
  });

  const jobs = extractJobs("project-1", project);

  assert.deepEqual(jobs.map((job) => job.kind), ["Training"]);
});

test("extractJobs includes simultaneous training and inference", () => {
  const project = projectWithModel({
    modelId: "model-1",
    name: "Damage model",
    status: "Queued",
    inferenceStatus: "InProgress",
  });

  const jobs = extractJobs("project-1", project);

  assert.deepEqual(jobs.map((job) => job.kind), ["Training", "Inference"]);
});

test("extractJobs excludes terminal and empty statuses", () => {
  const project = projectWithModel({
    modelId: "model-1",
    name: "Damage model",
    status: "Failed",
    inferenceStatus: "",
  });

  const jobs = extractJobs("project-1", project);

  assert.deepEqual(jobs, []);
});

test("pretrained runs with unset training status appear only as ongoing inference", () => {
  for (const inferenceStatus of ["Queued", "InProgress"]) {
    const project = projectWithModel({
      modelId: "catalog-run", modelType: "pretrained",
      name: "Catalog inference fixture", catalogModelName: "DINOv3",
      pretrainedInference: { adapter: "dinov3_upernet" },
      status: null, trainingJob: null, inferenceStatus,
      inferenceCurrentStep: 1, inferenceTotalSteps: 7, inferenceProgressPct: 15,
    });
    const jobs = extractJobs("project-1", project);

    assert.deepEqual(jobs.map((job) => job.kind), ["Inference"]);
    assert.equal(jobs[0].indicator.status, inferenceStatus);
    assert.equal(jobs[0].indicator.currentStep, 1);
    assert.equal(jobs[0].indicator.totalSteps, 7);
    assert.equal(jobs[0].indicator.progressPct, 15);
  }
});