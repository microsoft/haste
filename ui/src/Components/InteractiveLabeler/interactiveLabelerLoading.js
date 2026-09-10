// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

export const MAP_READY_TIMEOUT_MS = 30000;

// Progress is rendered by a component large enough that a per-chunk setState
// is visible in a profile, so notifications are coalesced into this window.
export const PROGRESS_THROTTLE_MS = 100;

// Ceiling for a single artifact download. A declared length above this is
// refused up front, and a response that arrives without a Content-Length is
// abandoned once it crosses the same line, so a runaway stream cannot grow
// until the tab dies.
export const MAX_ARTIFACT_BYTES = 1024 * 1024 * 1024;

export function throwFootprintTilesLoadError(error) {
  if (error?.name === "AbortError") throw error;
  console.error("Failed to load the footprint PMTiles archive:", error);
  throw new Error(
    "The building footprint tiles for this image layer are not ready " +
      "yet. They are built once per layer, shortly after the layer " +
      "finishes processing. Try again in a few minutes."
  );
}

export function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "";
  const units = ["B", "KB", "MB", "GB"];
  const unitIndex = Math.min(
    Math.floor(Math.log(bytes) / Math.log(1024)),
    units.length - 1
  );
  const value = bytes / 1024 ** unitIndex;
  const decimalPlaces =
    unitIndex === 2 ? 1 : unitIndex === 0 || value >= 10 ? 0 : 1;
  return `${value.toFixed(decimalPlaces)} ${units[unitIndex]}`;
}

export function getLoadProgress(step, stepCount) {
  if (!Number.isFinite(step) || !Number.isFinite(stepCount) || stepCount <= 0) {
    return 0;
  }
  return Math.min(Math.max(step + 1, 0), stepCount) / stepCount;
}

// Only a positive, exact integer is worth preallocating against — anything
// else (absent, "", NaN, 1e21) falls back to chunk accumulation.
export function parseContentLength(value) {
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}

// Coalesce download notifications so a multi-megabyte artifact cannot fire a
// state update per response chunk. `flush` bypasses the window so the final
// byte count is always reported, even when the last chunk lands mid-window.
export function createProgressThrottle(onProgress, options = {}) {
  const { throttleMs = PROGRESS_THROTTLE_MS, now = Date.now } = options;
  let lastEmitAt = -Infinity;
  let lastLoaded = null;

  const emit = (loaded, total) => {
    lastEmitAt = now();
    lastLoaded = loaded;
    onProgress(loaded, total);
  };

  return {
    report(loaded, total) {
      if (!onProgress || now() - lastEmitAt < throttleMs) return;
      emit(loaded, total);
    },
    flush(loaded, total) {
      if (!onProgress || lastLoaded === loaded) return;
      emit(loaded, total);
    },
  };
}

// Read a response body fully into one ArrayBuffer. When the response declares
// a usable Content-Length each chunk is written straight into its final
// home, so peak memory stays at a single copy of the artifact rather than the
// chunk list plus the consolidated buffer.
export async function readResponseBuffer(response, onProgress, options = {}) {
  const { maxBytes = MAX_ARTIFACT_BYTES } = options;
  const total = parseContentLength(response.headers?.get?.("content-length"));
  const progress = createProgressThrottle(onProgress, options);

  if (total !== null && total > maxBytes) {
    throw new Error(
      `Artifact is ${formatBytes(total)}, above the ` +
        `${formatBytes(maxBytes)} download limit.`
    );
  }

  if (!response.body) {
    const buffer = await response.arrayBuffer();
    progress.flush(buffer.byteLength, total ?? buffer.byteLength);
    return buffer;
  }

  const reader = response.body.getReader();
  let bytes = total !== null ? new Uint8Array(total) : null;
  const chunks = bytes ? null : [];
  let loaded = 0;

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;

    const next = loaded + value.byteLength;
    if (next > maxBytes) {
      throw new Error(
        `Artifact exceeded the ${formatBytes(maxBytes)} download limit.`
      );
    }

    if (bytes) {
      // The body outran its declared length. Grow once instead of silently
      // truncating the archive.
      if (next > bytes.length) {
        const grown = new Uint8Array(next);
        grown.set(bytes.subarray(0, loaded));
        bytes = grown;
      }
      bytes.set(value, loaded);
    } else {
      chunks.push(value);
    }

    loaded = next;
    progress.report(loaded, total);
  }

  progress.flush(loaded, total);

  if (bytes) {
    // A body shorter than its declared length leaves a zero-filled tail.
    return loaded === bytes.length
      ? bytes.buffer
      : bytes.buffer.slice(0, loaded);
  }

  const merged = new Uint8Array(loaded);
  let offset = 0;
  for (const chunk of chunks) {
    merged.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return merged.buffer;
}

function abortError() {
  const error = new Error("Azure Maps initialization was cancelled.");
  error.name = "AbortError";
  return error;
}

export function waitForMapReady(
  map,
  { signal, timeoutMs = MAP_READY_TIMEOUT_MS, onReady } = {}
) {
  return new Promise((resolve, reject) => {
    let timeoutId;

    const cleanup = () => {
      clearTimeout(timeoutId);
      map.events.remove?.("ready", handleReady);
      map.events.remove?.("error", handleError);
      signal?.removeEventListener("abort", handleAbort);
    };
    const settle = (callback, value) => {
      cleanup();
      callback(value);
    };
    const handleReady = () => {
      try {
        onReady?.();
        settle(resolve);
      } catch (error) {
        settle(reject, error);
      }
    };
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

    map.events.add("ready", handleReady);
    map.events.add("error", handleError);
    signal?.addEventListener("abort", handleAbort, { once: true });
    timeoutId = setTimeout(
      () => settle(reject, new Error("Azure Maps timed out while loading.")),
      timeoutMs
    );
  });
}