const TERMINAL_STATES = new Set([
  "Processed",
  "Completed",
  "Failed",
  "Cancelled",
]);

const isOngoing = (status) =>
  typeof status === "string" &&
  status.length > 0 &&
  !TERMINAL_STATES.has(status);

export function extractJobs(projectId, project) {
  const jobs = [];
  const projectName = project.name || "Project";

  (project.imageLayer || []).forEach((layer) => {
    const target = `/project/${projectId}/${layer.imageLayerId}`;

    if (isOngoing(layer.status)) {
      jobs.push({
        key: `layer-${layer.imageLayerId}`,
        kind: "Imagery",
        projectName,
        name: layer.name,
        target,
        indicator: {
          id: `ongoingImagery-${layer.imageLayerId}`,
          currentStep: layer.currentStep,
          totalSteps: layer.totalSteps,
          progressPct: layer.progressPct,
          status: layer.status,
          statusMessage: layer.statusMessage || "",
          prefix: "Imagery",
          contextLabel: `Image Layer: ${layer.name}`,
        },
      });
    }

    (layer.models || []).forEach((model) => {
      if (isOngoing(model.status)) {
        jobs.push({
          key: `training-${model.modelId}`,
          kind: "Training",
          projectName,
          name: model.name,
          target,
          indicator: {
            id: `ongoingTraining-${model.modelId}`,
            currentStep: model.currentStep,
            totalSteps: model.totalSteps,
            progressPct: model.progressPct,
            status: model.status,
            statusMessage: model.statusMessage || "",
            prefix: "Training",
            contextLabel: `Model: ${model.name} · Training`,
          },
        });
      }

      if (isOngoing(model.inferenceStatus)) {
        jobs.push({
          key: `inference-${model.modelId}`,
          kind: "Inference",
          projectName,
          name: model.name,
          target,
          indicator: {
            id: `ongoingInference-${model.modelId}`,
            currentStep: model.inferenceCurrentStep,
            totalSteps: model.inferenceTotalSteps,
            progressPct: model.inferenceProgressPct,
            status: model.inferenceStatus,
            statusMessage: model.inferenceStatusMessage || "",
            prefix: "Inference",
            contextLabel: `Model: ${model.name} · Inference`,
          },
        });
      }
    });
  });

  return jobs;
}