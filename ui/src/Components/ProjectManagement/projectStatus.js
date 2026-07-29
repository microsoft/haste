// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

/**
 * Derive a display status for a project from its aggregate counts.
 * - "Modeled": has at least one trained model
 * - "Active": has imagery but no models yet
 * - "Draft": no imagery layers yet
 */
export function getProjectStatus(project) {
  if ((project?.modelsCount ?? 0) > 0) {
    return { key: "modeled", label: "Modeled", tone: "modeled" };
  }
  if ((project?.imageLayerCount ?? 0) > 0) {
    return { key: "active", label: "Active", tone: "active" };
  }
  return { key: "draft", label: "Draft", tone: "draft" };
}

/** Format an ISO timestamp as YYYY-MM-DD, tolerant of missing values. */
export function formatProjectDate(value) {
  if (!value || typeof value !== "string") {
    return "—";
  }
  return value.substring(0, 10);
}
