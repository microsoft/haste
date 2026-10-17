// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { isInferenceOnlyModel } from "../CatalogInferenceHelper.js";

export function modelRowStatus(model) {
  const trainingActive = ["Queued", "InProgress"].includes(model.status);
  const isInference = isInferenceOnlyModel(model) || (!trainingActive && !!model.inferenceStatus);
  const statusMessage = isInference ? model.inferenceStatusMessage : model.statusMessage;
  // The shared status indicator's legacy fallback displays the status even
  // before logs/progress arrive. Never pass null progress to its numeric path.
  return {
    isInference,
    status: (isInference ? model.inferenceStatus : model.status) || "Unknown",
    statusMessage: statusMessage || "",
    currentStep: statusMessage ? (isInference ? model.inferenceCurrentStep : model.currentStep) ?? undefined : undefined,
    totalSteps: (isInference ? model.inferenceTotalSteps : model.totalSteps) ?? undefined,
    progressPct: (isInference ? model.inferenceProgressPct : model.progressPct) ?? undefined,
  };
}
