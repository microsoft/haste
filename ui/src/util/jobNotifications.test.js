import test from "node:test";
import assert from "node:assert/strict";

import {
  collectProjectJobStates,
  findJobStatusTransitions,
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