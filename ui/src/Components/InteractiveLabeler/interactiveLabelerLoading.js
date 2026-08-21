// Copyright (c) Microsoft Corporation. All rights reserved.
// Licensed under the MIT License.

export const MAP_READY_TIMEOUT_MS = 30000;

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