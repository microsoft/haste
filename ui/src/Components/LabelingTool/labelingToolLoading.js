export const MAP_IDLE_TIMEOUT_MS = 30000;
export const AZURE_MAPS_SATELLITE_TILES =
  "https://atlas.microsoft.com/map/tile?api-version=2.1&tilesetId=microsoft.imagery&zoom={z}&x={x}&y={y}";

function abortError() {
  const error = new Error("Labeling workspace initialization was cancelled.");
  error.name = "AbortError";
  return error;
}

export function getWorkspaceBounds(atlas, labelProject) {
  const features = labelProject?.features || [];
  if (!features.length) return null;
  return atlas.data.BoundingBox.fromData({
    type: "FeatureCollection",
    features,
  });
}

export function getWorkspaceCameraOptions(bounds) {
  return {
    ...(bounds ? { bounds, padding: 24 } : {}),
    bearing: 0,
    pitch: 0,
    duration: 0,
  };
}

export function resolveImageryTileUrl(
  tileUrl,
  { allowFallback = true, required = false } = {}
) {
  if (tileUrl) return tileUrl;
  if (allowFallback) return AZURE_MAPS_SATELLITE_TILES;
  if (required) {
    throw new Error("Required post-event imagery is unavailable.");
  }
  return null;
}

export function waitForMapIdle(
  map,
  { signal, timeoutMs = MAP_IDLE_TIMEOUT_MS } = {}
) {
  return new Promise((resolve, reject) => {
    let timeoutId;
    const cleanup = () => {
      clearTimeout(timeoutId);
      map.events.remove?.("idle", handleIdle);
      map.events.remove?.("error", handleError);
      signal?.removeEventListener("abort", handleAbort);
    };
    const settle = (callback, value) => {
      cleanup();
      callback(value);
    };
    const handleIdle = () => settle(resolve);
    const handleError = (event) => {
      const message =
        event?.error?.message || event?.message || "Azure Maps failed to load.";
      settle(reject, new Error(message));
    };
    const handleAbort = () => settle(reject, abortError());

    if (signal?.aborted) {
      reject(abortError());
      return;
    }
    map.events.add("idle", handleIdle);
    map.events.add("error", handleError);
    signal?.addEventListener("abort", handleAbort, { once: true });
    timeoutId = setTimeout(
      () => settle(reject, new Error("Azure Maps timed out while rendering.")),
      timeoutMs
    );
  });
}
