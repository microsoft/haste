// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

// Never turn an invalid response (including a login/proxy response) into an
// empty catalog. Validate before replacing the last successfully loaded list.
export function readModelCatalog(response) {
  const models = response?.modelCatalog;
  const names = new Set();
  if (!Array.isArray(models) || models.some((model) => {
    const name = model?.baseModelName;
    if (typeof name !== "string" || !name.trim() || names.has(name)) return true;
    names.add(name);
    return false;
  })) {
    throw new Error("Malformed model catalog response. Expected a modelCatalog list with unique base model names.");
  }
  return models;
}

export function hasCatalogCapability(model, capability) {
  // Missing capabilities are legacy training entries. For inference, readiness
  // from the layer-aware endpoint is authoritative for eligible legacy recipes.
  if (model?.capabilities == null) {
    return capability === "training" || model?.inferenceReady === true;
  }
  return Array.isArray(model.capabilities) && model.capabilities.includes(capability);
}

export function buildCatalogDeletionEndpoint(model) {
  return `DeleteModelCatalog?${new URLSearchParams({ baseModelName: model.baseModelName })}`;
}

export function catalogText(value, fallback = "--") {
  return typeof value === "string" || typeof value === "number"
    ? String(value) || fallback
    : fallback;
}

export function formatCatalogDate(value) {
  if (typeof value !== "string" || !value || Number.isNaN(Date.parse(value))) return "--";
  return `${value.substring(0, 10)} ${value.substring(11, 19)}`.trim();
}

export function catalogMetadataEntries(value) {
  if (value == null || value === "") return [];
  return typeof value === "object" ? Object.entries(value) : [["Metadata", value]];
}
