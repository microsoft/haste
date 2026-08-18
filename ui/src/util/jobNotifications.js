// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

const TERMINAL_STATUSES = new Set(["Processed", "Failed", "Cancelled"]);

export function collectProjectJobStates(project) {
  const jobs = new Map();

  for (const layer of project?.imageLayer || []) {
    const layerId = layer.imageLayerId;
    if (!layerId) continue;

    jobs.set(`imagery:${layerId}`, {
      status: layer.status,
      title: "Imagery processing",
      subject: layer.name || "Image layer",
    });

    for (const model of layer.models || []) {
      const modelId = model.modelId;
      if (!modelId) continue;
      const isEmbedding = model.modelType === "embedding";

      jobs.set(`${isEmbedding ? "embedding" : "training"}:${modelId}`, {
        status: model.status,
        title: isEmbedding ? "Embedding" : "Model training",
        subject: model.name || (isEmbedding ? "Embedding" : "Model"),
      });

      if (model.inferenceStatus) {
        jobs.set(`inference:${modelId}`, {
          status: model.inferenceStatus,
          title: "Model inference",
          subject: model.name || "Model",
        });
      }
    }
  }

  return jobs;
}

export function findJobStatusTransitions(previousJobs, currentJobs) {
  const transitions = [];

  for (const [key, current] of currentJobs) {
    const previous = previousJobs.get(key);
    if (
      TERMINAL_STATUSES.has(current.status) &&
      (!previous || previous.status !== current.status)
    ) {
      transitions.push({ key, ...current });
    }
  }

  return transitions;
}