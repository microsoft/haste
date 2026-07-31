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