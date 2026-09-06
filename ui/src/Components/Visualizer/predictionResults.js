// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Pure read-only decisions adapted from PR136. No preparation or editing state.
export const FOOTPRINTS_LOADING = "loading";
export const FOOTPRINTS_READY = "ready";
export const FOOTPRINTS_EMPTY = "empty";
export const FOOTPRINTS_UNAVAILABLE = "unavailable";
export const DEFAULT_THRESHOLD = 0;
export const DEFAULT_UNKNOWN_THRESHOLD = 0;

export function hasRasterLayer(layer) {
  const url = typeof layer?.url === "string" ? layer.url.trim() : "";
  return !!url && !/[?&]url=(?:&|$)/.test(url);
}

export function canViewResults(model) {
  return model?.predictionsReady === true && model?.buildingCount !== 0;
}

export function buildVisualizerResultsUrl({ projectId, imageLayerId, modelId }) {
  return `GetVisualizerResults?${new URLSearchParams({ projectId, imageLayerId, modelId })}`;
}

// Shared by BOTH model-row families, including legacy/no-edits downloads.
// ZIP downloads deliberately keep their separate storage-download path.
export function buildRawGpkgUrl({ projectId, imageLayerId, modelId }) {
  return `GetModelArtifact?${new URLSearchParams({
    projectId, imageLayerId, modelId, kind: "gpkg", version: "0",
  })}`;
}

/** Never turn an absent protected URL into a direct storage fallback. */
export function protectedArtifactEndpoint(value, kind) {
  if (typeof value !== "string" || !/^(?:\/api\/)?GetModelArtifact\?/.test(value)) {
    throw new Error(`Missing protected ${kind} artifact URL.`);
  }
  const endpoint = value.replace(/^\/api\//, "");
  const url = new URL(endpoint, "https://haste.invalid/");
  if (url.hash || url.searchParams.get("kind") !== kind) {
    throw new Error(`Invalid protected ${kind} artifact URL.`);
  }
  return endpoint;
}

export function resolvePredictionArtifacts(results) {
  return {
    footprintTilesUrl: protectedArtifactEndpoint(results?.footprintTilesUrl, "footprint_pmtiles"),
    predictionAttrsUrl: protectedArtifactEndpoint(results?.predictionAttrsUrl, "prediction_attrs"),
  };
}

// Readiness/count are part of identity too: a clear must invalidate a loaded
// result even if a legacy producer leaves its old URLs on the response.
export function predictionRenderKey(results) {
  if (!results) return "";
  return JSON.stringify([
    results.predictionRevision, results.predictionAttrsUrl, results.footprintTilesUrl,
    results.flavor, results.buildingCount, results.predictionsReady,
    results.predictionsReadiness?.reason, results.predictionsReadiness?.tilesReady,
    results.predictionsReadiness?.attrsReady,
  ]);
}

export function validateResultsMetadata(results) {
  if (!["inference", "embedding"].includes(results?.flavor)) {
    throw new Error("Results do not identify their prediction workflow.");
  }
  if (!Number.isSafeInteger(results.buildingCount) || results.buildingCount < 0) {
    throw new Error("Results contain an invalid building count.");
  }
  if (typeof results.predictionRevision !== "string" || !results.predictionRevision.trim()) {
    throw new Error("Results do not identify their prediction revision.");
  }
  if (typeof results.supportsThreshold !== "boolean") {
    throw new Error("Results do not identify their threshold capability.");
  }
}

export function resolveFootprintStatus({ results, loaded = false, error = "", layersReady = false }) {
  if (!results) return FOOTPRINTS_LOADING;
  if (results.buildingCount === 0) return FOOTPRINTS_EMPTY;
  if (error || results.predictionsReady !== true) return FOOTPRINTS_UNAVAILABLE;
  return loaded && layersReady ? FOOTPRINTS_READY : FOOTPRINTS_LOADING;
}

export function readinessDetail(results) {
  const readiness = results?.predictionsReadiness;
  if (readiness?.detail) return readiness.detail;
  if (results?.buildingCount === 0 || readiness?.reason === "no_predictions") {
    return "No predicted buildings. Run inference or predict all buildings in the Interactive Labeler.";
  }
  if (readiness?.tilesReady === false) {
    return "The image layer's footprint tiles are not available yet. Retry after layer processing finishes.";
  }
  return "These results lack matching prediction attributes. Rerun inference or predict all buildings in the Interactive Labeler.";
}

export function describeFootprintStatus(status, detail = "") {
  if (status === FOOTPRINTS_READY) return null;
  if (status === FOOTPRINTS_LOADING) {
    return {
      intent: "info", title: "Loading predicted buildings",
      body: detail || "Loading prediction attributes and building footprints on both maps.",
    };
  }
  return {
    intent: status === FOOTPRINTS_EMPTY ? "warning" : "error",
    title: status === FOOTPRINTS_EMPTY ? "No predicted buildings" : "Predicted buildings unavailable",
    body: detail,
  };
}

export function visualizerLayerOptions({ results, footprintStatus }) {
  const options = [];
  if (hasRasterLayer(results?.predictedDamageLayer)) {
    options.push({ key: "predictedDamageLayer", label: "Predicted building damage" });
  }
  if (hasRasterLayer(results?.predictionsLayer)) {
    options.push({ key: "predictionsLayer", label: "Raw model output" });
  }
  options.push({
    key: "footprints", label: "Predicted building footprints",
    disabled: footprintStatus !== FOOTPRINTS_READY,
  });
  return options;
}
