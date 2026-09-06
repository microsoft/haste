// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
// Protected, bounded GETs only. Fetch logic is independent of React/Atlas.
import { readResponseBuffer } from "../InteractiveLabeler/interactiveLabelerLoading.js";
import { normalizeAttrs } from "./predictionClassify.js";
import { resolvePredictionArtifacts, validateResultsMetadata } from "./predictionResults.js";
import { PMTiles } from "pmtiles";
import { getPmtilesProtocol, InMemoryPMTilesSource } from "../../util/pmtiles.js";

export const MAX_ATTRIBUTES_BYTES = 64 * 1024 * 1024;
export const MAX_ARCHIVE_BYTES = 1024 * 1024 * 1024;
const DOWNLOAD_TIMEOUT_MS = 120000;

export async function fetchArtifactBuffer(url, { signal, maxBytes = MAX_ARCHIVE_BYTES } = {}) {
  const controller = new AbortController();
  const cancel = () => controller.abort(signal.reason);
  signal?.throwIfAborted();
  signal?.addEventListener("abort", cancel, { once: true });
  const timer = setTimeout(() => controller.abort(new Error("Artifact download timed out.")), DOWNLOAD_TIMEOUT_MS);
  try {
    const response = await fetch(url, { signal: controller.signal, cache: "no-store" });
    if (!response.ok) {
      const error = new Error(`Artifact download failed (HTTP ${response.status}).`);
      error.status = response.status;
      throw error;
    }
    const buffer = await readResponseBuffer(response, undefined, {
      maxBytes, signal: controller.signal,
    });
    controller.signal.throwIfAborted();
    return buffer;
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", cancel);
    controller.abort();
  }
}

export async function loadPredictionAttributes(results, buildUrl, signal) {
  validateResultsMetadata(results);
  const urls = resolvePredictionArtifacts(results);
  let buffer;
  try {
    buffer = await fetchArtifactBuffer(buildUrl(urls.predictionAttrsUrl), {
      signal, maxBytes: MAX_ATTRIBUTES_BYTES,
    });
  } catch (error) {
    if (error.status === 404) {
      throw new Error(results.predictionVersion > 0
        ? "This saved version's attributes are missing. Choose another version; its GeoPackage may still be downloaded."
        : "Prediction attributes are missing. Rerun inference or predict all buildings in the Interactive Labeler.");
    }
    throw error;
  }
  signal?.throwIfAborted();
  const attrs = normalizeAttrs(JSON.parse(new TextDecoder().decode(buffer)), results);
  return { attrs, archiveUrl: buildUrl(urls.footprintTilesUrl) };
}

export async function loadPredictionArtifacts(results, buildUrl, signal) {
  const { attrs, archiveUrl } = await loadPredictionAttributes(results, buildUrl, signal);
  const protocol = getPmtilesProtocol();
  let archive = protocol.get(archiveUrl);
  if (!archive) {
    const buffer = await fetchArtifactBuffer(archiveUrl, { signal });
    signal?.throwIfAborted();
    archive = new PMTiles(new InMemoryPMTilesSource(archiveUrl, buffer));
  }
  const header = await archive.getHeader();
  signal?.throwIfAborted();
  protocol.add(archive);
  return {
    attrs, archiveKey: archiveUrl,
    bounds: [header.minLon, header.minLat, header.maxLon, header.maxLat],
  };
}
