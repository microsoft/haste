import test from "node:test";
import assert from "node:assert/strict";

import {
  collectProjectJobStates,
  findJobStatusTransitions,
  hasActiveProjectJobs,
} from "./jobNotifications.js";

function projectWithEmbeddingStatus(status) {
  return {
    imageLayer: [
      {
        imageLayerId: "layer-1",
        name: "Spokane imagery",
        status: "Processed",
        models: [
          {
            modelId: "embedding-1",
            modelType: "embedding",
            name: "mosaiks-1024",
            status,
          },
        ],
      },
    ],
  };
}

test("reports an embedding transition to processed", () => {
  const previous = collectProjectJobStates(
    projectWithEmbeddingStatus("InProgress")
  );
  const current = collectProjectJobStates(
    projectWithEmbeddingStatus("Processed")
  );

  assert.deepEqual(findJobStatusTransitions(previous, current), [
    {
      key: "embedding:embedding-1",
      status: "Processed",
      title: "Embedding",
      subject: "mosaiks-1024",
    },
  ]);
});

test("reports inference that starts and finishes between polls", () => {
  const previous = collectProjectJobStates({
    imageLayer: [
      {
        imageLayerId: "layer-1",
        status: "Processed",
        models: [
          {
            modelId: "model-1",
            name: "Fire model",
            status: "Processed",
          },
        ],
      },
    ],
  });
  const current = new Map(previous);
  current.set("inference:model-1", {
    status: "Processed",
    title: "Model inference",
    subject: "Fire model",
  });

  assert.deepEqual(findJobStatusTransitions(previous, current), [
    {
      key: "inference:model-1",
      status: "Processed",
      title: "Model inference",
      subject: "Fire model",
    },
  ]);
});

test("reports terminal failures but ignores intermediate updates", () => {
  const previous = new Map([
    ["training:model-1", { status: "Queued" }],
    ["inference:model-1", { status: "InProgress" }],
  ]);
  const current = new Map([
    ["training:model-1", { status: "InProgress", title: "Model training", subject: "Fire model" }],
    ["inference:model-1", { status: "Failed", title: "Model inference", subject: "Fire model" }],
  ]);

  assert.deepEqual(findJobStatusTransitions(previous, current), [
    {
      key: "inference:model-1",
      status: "Failed",
      title: "Model inference",
      subject: "Fire model",
    },
  ]);
});

test("detects whether project jobs still need polling", () => {
  assert.equal(
    hasActiveProjectJobs(
      new Map([
        ["done", { status: "Processed" }],
        ["active", { status: "InProgress" }],
      ])
    ),
    true
  );
  assert.equal(
    hasActiveProjectJobs(
      new Map([
        ["done", { status: "Processed" }],
        ["trained", { status: "Trained" }],
        ["failed", { status: "Failed" }],
        ["unknown", { status: null }],
      ])
    ),
    false
  );
  assert.equal(hasActiveProjectJobs(null), false);
});

test("collecting jobs ignores malformed records and uses fallback names", () => {
  assert.deepEqual([...collectProjectJobStates(null)], []);
  assert.deepEqual([...collectProjectJobStates({})], []);

  const jobs = collectProjectJobStates({
    imageLayer: [
      { name: "Missing id", models: [] },
      { imageLayerId: "layer-without-models", status: "Processed" },
      {
        imageLayerId: "layer-1",
        models: [
          { status: "Queued" },
          { modelId: "model-1", status: "Queued" },
          {
            modelId: "embedding-1",
            modelType: "embedding",
            status: "Queued",
            inferenceStatus: "InProgress",
          },
        ],
      },
    ],
  });

  assert.deepEqual(jobs.get("imagery:layer-1").subject, "Image layer");
  assert.deepEqual(jobs.get("training:model-1").subject, "Model");
  assert.deepEqual(jobs.get("embedding:embedding-1").subject, "Embedding");
  assert.deepEqual(jobs.get("inference:embedding-1").subject, "Model");
});

test("does not report unchanged or nonterminal job states", () => {
  const previous = new Map([
    ["same", { status: "Processed" }],
    ["active", { status: "Queued" }],
  ]);
  const current = new Map(previous);

  assert.deepEqual(findJobStatusTransitions(previous, current), []);
});