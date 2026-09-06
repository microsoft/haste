// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// PR136's selection/download helpers, without preparation/backfill semantics.
export const RAW_VERSION = 0;
export const RAW_VERSION_LABEL = "Raw model output";

export function normalizeVersion(value) {
  if (!Number.isSafeInteger(value) || value < 0) throw new Error("Invalid prediction version.");
  return value;
}
export const versionLabel = (value) => value === 0 ? RAW_VERSION_LABEL : `Version ${normalizeVersion(value)}`;
export const sortVersionsDescending = (versions = []) => [...versions].sort((a, b) => b.version - a.version);

export function validateVersionManifest(versions) {
  if (!Array.isArray(versions)) throw new Error("The server returned invalid prediction version history.");
  const seen = new Set();
  for (const entry of versions) {
    if (!entry || !Number.isSafeInteger(entry.version) || entry.version <= 0 || seen.has(entry.version)) {
      throw new Error("The server returned ambiguous prediction version history.");
    }
    seen.add(entry.version);
  }
  return versions;
}

export function predictionSourceOptions(versions = [], currentRevision, map = false) {
  const entries = sortVersionsDescending(versions).filter((entry) => Number.isSafeInteger(entry.version) && entry.version > 0 && entry.gpkgUrl);
  const newest = entries.find((entry) => !currentRevision || entry.predictionRevision === currentRevision);
  return [
    ...entries.map((entry) => ({
      version: entry.version,
      text: `${versionLabel(entry.version)}${entry === newest ? " · newest for current predictions" : ""}`,
      disabled: map && (!entry.predictionAttrsUrl || entry.attrsReady === false),
      reason: "This version has no prediction attributes. Its GeoPackage remains available; select another version to view the map.",
      predictionRevision: entry.predictionRevision,
    })),
    { version: 0, text: RAW_VERSION_LABEL, disabled: false, predictionRevision: currentRevision },
  ];
}

export function defaultPredictionVersion(versions = [], currentRevision) {
  return sortVersionsDescending(versions).find(
    (entry) => entry.gpkgUrl && entry.predictionRevision === currentRevision && entry.version > 0,
  )?.version ?? 0;
}

export function buildVersionGpkgUrl({ projectId, imageLayerId, modelId, version, predictionRevision }) {
  const params = new URLSearchParams({ projectId, imageLayerId, modelId, kind: "gpkg", version: String(normalizeVersion(version)) });
  if (predictionRevision) params.set("predictionRevision", predictionRevision);
  return `GetModelArtifact?${params}`;
}

export function versionEndpoint(action, { projectId, imageLayerId, modelId }, version) {
  const params = new URLSearchParams({ projectId, imageLayerId, modelId });
  if (version !== undefined && version !== null) params.set("version", String(normalizeVersion(version)));
  return `${action}?${params}`;
}

export function validateSelectedSource(data, version, revision) {
  const served = normalizeVersion(data.predictionVersion);
  if (data.predictionVersions !== undefined) validateVersionManifest(data.predictionVersions);
  if (version != null && served !== version) throw new Error("The server returned a different prediction version.");
  if (revision && data.predictionRevision !== revision) throw new Error("The server returned a different prediction generation.");
  return data;
}

export function savedClassNote(version) {
  return `Version ${version} stores the class each building was saved with. Switch to raw model output to work from the model's scores again.`;
}
