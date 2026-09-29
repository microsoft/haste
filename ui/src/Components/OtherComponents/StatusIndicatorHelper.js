// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

const activeStates = new Set(["Queued", "InProgress"]);
// Statuses with a .modelStatus-* color in style.css; any other label uses the
// neutral "Unknown" color so white badge text never lacks a background.
const styledStates = new Set([...activeStates, "Processed", "Completed", "Failed", "Cancelled"]);

export function statusPresentation({ status, currentStep, totalSteps, progressPct }) {
  const label = typeof status === "string" && status ? status : "Unknown";
  const active = activeStates.has(label);
  const hasCounters =
    Number.isFinite(currentStep) && currentStep >= 0 &&
    Number.isFinite(totalSteps) && totalSteps > 0;
  const hasProgress =
    label !== "Queued" && Number.isFinite(progressPct) &&
    (progressPct > 0 || (hasCounters && currentStep > 0));

  return {
    label,
    tone: styledStates.has(label) ? label : "Unknown",
    active,
    indeterminate: active && !hasProgress,
    progress: hasProgress ? Math.min(100, Math.max(0, progressPct)) : null,
    stepText: hasProgress && hasCounters ? `${currentStep}/${totalSteps}` : "",
  };
}
