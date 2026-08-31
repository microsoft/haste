// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

export function buildModelCatalogEndpoint(imageLayer = {}, eventTypes) {
  const params = new URLSearchParams();
  const definedEventTypes = Array.isArray(eventTypes)
    ? eventTypes.filter(Boolean)
    : [];

  if (definedEventTypes.length > 0) {
    params.set("eventTypes", definedEventTypes.join(","));
  }

  const imagerySource = imageLayer?.sourceTypePostEvent;
  if (imagerySource !== "" && imagerySource != null) {
    params.set("imagerySource", imagerySource);
  }

  const query = params.toString();
  return query ? `GetModelCatalog?${query}` : "GetModelCatalog";
}

export function normalizeBaseModelOptions(cataloguedModels = []) {
  return cataloguedModels.map((model) => {
    const value = model?.value ?? {};
    const baseModelName = value.baseModelName || "";
    const description = value.description == null
      ? ""
      : String(value.description);

    return {
      key: model?.key || baseModelName,
      baseModelName,
      description: description ? `${description.substring(0, 30)}...` : "",
      checkpointFilePath: value.checkpointFilePath || "",
      eventTypes: value.eventTypes || [],
      imagerySource: value.imagerySource || "",
    };
  });
}

export function resolveBaseModelId(cataloguedModels, initialWeightsUrl) {
  if (!initialWeightsUrl) return "";

  const matchingOption = normalizeBaseModelOptions(cataloguedModels).find(
    (option) => option.checkpointFilePath === initialWeightsUrl
  );
  return matchingOption?.key || "";
}

export function applyBaseModelSelection(componentState, selectedOption) {
  return {
    ...componentState,
    baseModelId: selectedOption?.key || "",
    baseModelIdError: "",
    initialWeightsUrl: selectedOption?.checkpointFilePath || "",
  };
}
