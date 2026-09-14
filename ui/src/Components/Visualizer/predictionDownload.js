// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.
import { readResponseBuffer } from "../InteractiveLabeler/interactiveLabelerLoading.js";

export function predictionFilename(disposition, version) {
  const encoded = /filename\*=UTF-8''([^;]+)/i.exec(disposition || "")?.[1];
  const plain = /filename="?([^";]+)"?/i.exec(disposition || "")?.[1];
  let filename = plain;
  try { if (encoded) filename = decodeURIComponent(encoded); } catch { /* use plain/fallback */ }
  return filename?.split(/[\\/]/).pop() || (version === 0 ? "predictions_raw.gpkg" : `predictions_v${version}.gpkg`);
}
export async function downloadPrediction(url, version, { signal, fetchResponse = fetch, documentObject = document, urls = URL } = {}) {
  const response = await fetchResponse(url, { signal, cache: "no-store" });
  if (!response.ok) {
    let data;
    try { data = await response.json(); } catch { /* use status */ }
    throw new Error(typeof data?.error === "string" ? data.error :
      data?.error?.message || `Prediction download failed (HTTP ${response.status}).`);
  }
  const buffer = await readResponseBuffer(response, undefined, { signal, maxBytes: 1024 * 1024 * 1024 });
  const objectUrl = urls.createObjectURL(new Blob([buffer], { type: "application/geopackage+sqlite3" }));
  try {
    const link = documentObject.createElement("a");
    link.href = objectUrl;
    link.download = predictionFilename(response.headers.get("content-disposition"), version);
    documentObject.body.appendChild(link);
    link.click();
    link.remove();
  } finally {
    // Allow the browser to acquire the blob before releasing this bounded buffer.
    setTimeout(() => urls.revokeObjectURL(objectUrl), 1000);
  }
}
